# Community components and attribution

Original Centerstage glue code and UI: Copyright 2026 Centerstage contributors, Apache-2.0. No third-party trained weights or user videos are bundled in this repository.

| Component | Role | Installed package license |
|---|---|---|
| [RTMLib](https://github.com/Tau-J/rtmlib) 0.0.16 | RTMO preprocessing and NMS | Apache-2.0 |
| [MMPose / RTMO](https://github.com/open-mmlab/mmpose/tree/main/projects/rtmo) | Official RTMO-s ONNX model | Upstream MMPose project: Apache-2.0; training datasets retain their own terms |
| [Roboflow trackers](https://github.com/roboflow/trackers) 2.6.1 | OC-SORT, ByteTrack, CBIoU implementation | Apache-2.0 |
| [supervision](https://github.com/roboflow/supervision) 0.31.0 | Detection data structures | MIT |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) 1.31.0 | Local inference | MIT |
| [PyAV](https://github.com/PyAV-Org/PyAV) 19.0.1 | FFmpeg-backed decoding | BSD-3-Clause; bundled FFmpeg libraries have separate licenses/build options |
| [OpenCV](https://github.com/opencv/opencv-python) | Image preprocessing | Apache-2.0; wheel third-party notices also apply |
| [FastAPI](https://github.com/fastapi/fastapi) | Local API | MIT |
| [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) 0.7.2 | Adaptive shot detection, called as a dependency | BSD-3-Clause |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) 3.10.0 | Optional local subtitle OCR with PP-OCRv6 small | Apache-2.0; downloaded model artifacts retain upstream terms |

This table is not a substitute for the license files shipped with dependencies. Python dependencies are locked in `uv.lock`, including transitive packages. RTMLib's published preprocessing and NMS functions are called as dependencies rather than copied into this repository. Tracking algorithm attribution is retained by the upstream package.

The model is fetched from OpenMMLab's official `rtmo-s_8xb32-600e_body7-640x640-dac2bf74_20231211.zip`, as linked by RTMLib. Its verified ONNX SHA-256 is `d0703d40d19f3921da51ae725402d5fdae4d2478c7442072d3101bd396f370d8`. Local download provenance is stored alongside the model. Apache licensing of source code should not be read as a blanket grant over every training dataset or input video.

Research background: [POINT, CVPR 2019 — Learning to Learn Relation for Important People Detection in Still Images](https://openaccess.thecvf.com/content_CVPR_2019/papers/Li_Learning_to_Learn_Relation_for_Important_People_Detection_in_Still_CVPR_2019_paper.pdf). Centerstage's current C-position scorer is an experimental geometric baseline, not a POINT implementation or an accuracy-equivalent replacement.
