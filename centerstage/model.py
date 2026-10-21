"""RTMO inference using RTMLib preprocessing/NMS, preserving model boxes.

The RTMLib high-level API only returns keypoints. This adapter keeps the actual
detector boxes and confidence for the community tracker (not pose min/max boxes).
"""
import hashlib
import json
import os
import shutil
import time
import urllib.request
import zipfile
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
from rtmlib import RTMO
from rtmlib.tools.object_detection.post_processings import multiclass_nms

from .config import MODEL_URL, MODEL_SHA256, get_config


def prepare_model(directory: Path, progress=lambda message: None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "rtmo-s.onnx"
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_SHA256:
            raise RuntimeError("缓存模型校验失败，请移走 rtmo-s.onnx 后重新准备")
        return path
    progress("首次准备：下载 RTMO-s 模型")
    archive = directory / "rtmo-s.zip.part"
    with urllib.request.urlopen(MODEL_URL, timeout=60) as response, archive.open("wb") as out:
        shutil.copyfileobj(response, out, 1024 * 1024)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    with zipfile.ZipFile(archive) as z:
        candidates = [n for n in z.namelist() if n.endswith(".onnx")]
        if len(candidates) != 1:
            raise RuntimeError("模型包结构不符合预期")
        temp = path.with_suffix(".part")
        with z.open(candidates[0]) as source, temp.open("wb") as out:
            shutil.copyfileobj(source, out)
        if hashlib.sha256(temp.read_bytes()).hexdigest() != MODEL_SHA256:
            raise RuntimeError("下载模型校验失败，未加载该文件")
        temp.replace(path)
    (directory / "provenance.json").write_text(json.dumps({
        "url": MODEL_URL, "archive_sha256": digest,
        "model_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "downloaded_at": time.time(),
    }, indent=2))
    archive.unlink()
    return path


def load_model(path, provider="auto"):
    """Load the live single-frame contract, with accelerator-to-CPU fallback."""
    config = get_config()
    if config.model.use_batch_inference:
        raise ValueError('Batch inference is not supported by the live pipeline')
    try:
        return PoseModel(path, provider)
    except Exception:
        if provider == "cpu":
            raise
        # Acceleration availability differs between OS/driver versions.
        # A failed accelerator must not block local CPU use or run.sh.
        return PoseModel(path, "cpu")


class PoseModel:
    def __init__(self, path: Path, provider="auto", batch_size: int = 1):
        cv2.setNumThreads(1)
        options = ort.SessionOptions()
        self.batch_size = batch_size
        # We only infer one frame at a time. Fixing the exported dynamic batch
        # enables CoreML to compile the backbone instead of rejecting it.
        options.add_free_dimension_override_by_name("batch", 1)
        options.intra_op_num_threads = int(os.environ.get("CENTERSTAGE_THREADS", "2"))
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        options.log_severity_level = 3
        available = ort.get_available_providers()
        providers = ["CPUExecutionProvider"]
        if provider in ("coreml","auto") and "CoreMLExecutionProvider" in available:
            providers.insert(0, ("CoreMLExecutionProvider", {"ModelFormat": "MLProgram",
                "RequireStaticInputShapes":"1", "MLComputeUnits":"ALL",
                "ModelCacheDirectory":str(path.parent/"coreml-batch1-ALL")}))
        elif provider in ("cuda","auto") and "CUDAExecutionProvider" in available:
            providers.insert(0, "CUDAExecutionProvider")
        self.session = ort.InferenceSession(str(path), sess_options=options, providers=providers)
        self.providers = self.session.get_providers()
        self.input_name = self.session.get_inputs()[0].name
        # Reuse the published preprocessing implementation without a second session.
        self.preprocessor = object.__new__(RTMO)
        self.preprocessor.model_input_size = (640, 640)
        self.preprocessor.mean = None
        self.preprocessor.std = None
        self.predict(np.zeros((640, 640, 3), dtype=np.uint8))

    def predict(self, image):
        padded, ratio = self.preprocessor.preprocess(image)
        tensor = np.ascontiguousarray(padded.transpose(2, 0, 1)[None], dtype=np.float32)
        det, pose = self.session.run(None, {self.input_name: tensor})
        boxes = det[0, :, :4].copy() / ratio
        confidence = det[0, :, 4]
        _, keep = multiclass_nms(boxes, confidence[:, None], nms_thr=.45, score_thr=.35)
        if keep is None or not len(keep):
            return np.empty((0, 4), np.float32), np.empty(0, np.float32), np.empty((0, 17, 3), np.float32)
        boxes, confidence, poses = boxes[keep], confidence[keep], pose[0, keep].copy()
        poses[:, :, :2] /= ratio
        h, w = image.shape[:2]
        boxes[:, [0, 2]] = np.clip(boxes[:, [0, 2]], 0, w)
        boxes[:, [1, 3]] = np.clip(boxes[:, [1, 3]], 0, h)
        valid = (np.isfinite(boxes).all(1) & np.isfinite(confidence) & np.isfinite(poses).all((1, 2))
                 & ((boxes[:, 2]-boxes[:, 0]) > 8) & ((boxes[:, 3]-boxes[:, 1]) > 25))
        return boxes[valid], confidence[valid], poses[valid]
