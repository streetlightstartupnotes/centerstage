"""Timestamp-preserving sampling and bounded-lookahead community shot detection."""
from collections import deque
from dataclasses import dataclass
import math

import av
import cv2
import numpy as np
from scenedetect import FrameTimecode
from scenedetect.detectors import AdaptiveDetector


@dataclass
class Sample:
    t: float
    image: np.ndarray
    caption: np.ndarray | None = None
    cut: bool = False


@dataclass
class DecodeProgress:
    end: float = 0.0


def samples(path, fps, source_fps, captions=False, cancelled=lambda: False, progress=None):
    if not math.isfinite(fps) or not math.isfinite(source_fps) or min(fps, source_fps) <= 0:
        raise ValueError('Video sample rates must be finite and positive')
    next_sample = next_caption = 0.0
    last_credit_submit = -1.0
    last_credit = None
    first_pts = None
    with av.open(str(path)) as container:
        for index, decoded in enumerate(container.decode(container.streams.video[0])):
            if cancelled(): break
            pts = float(decoded.pts * decoded.time_base) if decoded.pts is not None else index / source_fps
            if first_pts is None: first_pts = pts
            timestamp = max(0, pts - first_pts)
            if progress is not None:
                frame_duration = float(decoded.duration * decoded.time_base) if decoded.duration else 1 / source_fps
                progress.end = max(progress.end, timestamp + frame_duration)
            if timestamp + 1e-5 < next_sample: continue
            # Keep a global sampling clock. Advancing from the rounded source
            # timestamp undersamples 24/29.97 fps sources (e.g. 10 becomes 8).
            next_sample = (math.floor(timestamp * fps + 1e-5) + 1) / fps
            ratio = min(1.0, 640 / max(decoded.width, decoded.height))
            image = decoded.reformat(width=max(1, round(decoded.width * ratio)),
                                     height=max(1, round(decoded.height * ratio)), format='bgr24').to_ndarray()
            rotation = decoded.rotation
            if rotation % 90:
                raise ValueError('暂不支持非直角视频旋转，请转为方向已固定的 H.264 MP4')
            if rotation: image = np.ascontiguousarray(np.rot90(image, rotation // 90))
            caption = None
            if captions and timestamp + 1e-5 >= next_caption:
                # Check the already-resized frame every sample. Read the full
                # frame only when the lower band changes, or once a second while
                # it stays still, so a credit is not held for a whole second
                # after the printed name has changed.
                band_h, band_w = image.shape[:2]
                band = image[int(band_h * .62):int(band_h * .98), :]
                gray = cv2.resize(cv2.cvtColor(band, cv2.COLOR_BGR2GRAY), (160, 48)) if band.size else None
                delta = 1e9 if last_credit is None or gray is None else float(np.mean(cv2.absdiff(gray, last_credit)))
                if gray is not None and (delta >= 8 or timestamp - last_credit_submit >= 1.0):
                    last_credit = gray
                    last_credit_submit = timestamp
                    next_caption = timestamp + 0.2
                    original = decoded.to_ndarray(format='bgr24')
                    if rotation: original = np.ascontiguousarray(np.rot90(original, rotation // 90))
                    oh, ow = original.shape[:2]
                    caption = original[int(oh * .62):int(oh * .98), :].copy()
                else:
                    next_caption = timestamp + 0.1
            yield Sample(timestamp, image, caption)


def scene_samples(source, fps):
    # The detector emits a cut two samples late. Hold those samples so the reset
    # is applied to the actual first frame of the shot, never the emission frame.
    detector = AdaptiveDetector(adaptive_threshold=2.0, min_scene_len=max(2, round(fps * .35)),
                                window_width=2, min_content_val=15.0)
    pending = deque()
    recent = deque(maxlen=5)
    for index, sample in enumerate(source):
        pending.append((index, sample))
        thumb = cv2.resize(sample.image, (160, 90))
        recent.append((index,cv2.cvtColor(thumb,cv2.COLOR_BGR2GRAY).astype(np.float32)))
        cuts = {c.frame_num for c in detector.process_frame(FrameTimecode(index, float(fps)), thumb)}
        gray=dict(recent)
        for number in list(cuts):
            # A global exposure change preserves spatial structure. Suppress
            # those candidates so a stage flash does not reset every identity.
            if number-1 in gray and number in gray:
                a,b=gray[number-1],gray[number]
                # Near-gray pixels have unstable HSV hue; tiny luminance
                # differences alone cannot justify resetting every track.
                if np.mean(np.abs(a-b))<8 or (a.std()>2 and b.std()>2 and float(np.corrcoef(a.ravel(),b.ravel())[0,1])>.94):
                    cuts.remove(number)
        for number, buffered in pending:
            if number in cuts: buffered.cut = True
        if len(pending) > 2: yield pending.popleft()[1]
    yield from (sample for _, sample in pending)
