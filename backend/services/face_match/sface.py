"""OpenCV SFace + YuNet (opencv_zoo, Apache-2.0), run with the backend's own OpenCV.

Models: `<models>/face/face_recognition_sface_2021dec.onnx` and
`face_detection_yunet_2023mar.onnx`; without them the matcher is unavailable
and callers skip face matching.
"""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any, cast

RECOGNIZER = "face_recognition_sface_2021dec.onnx"
DETECTOR = "face_detection_yunet_2023mar.onnx"


class SFaceMatcher:
    def __init__(self, folder: Path) -> None:
        self._folder = folder
        self._lock = Lock()
        self._models: tuple[Any, Any] | None = None

    def available(self) -> bool:
        return (self._folder / RECOGNIZER).is_file() and (self._folder / DETECTOR).is_file()

    def _load(self) -> tuple[Any, Any]:
        import cv2

        if self._models is None:
            detector = cv2.FaceDetectorYN.create(str(self._folder / DETECTOR), "", (320, 320), 0.7)
            recognizer = cv2.FaceRecognizerSF.create(str(self._folder / RECOGNIZER), "")
            self._models = (detector, recognizer)
        return self._models

    def embedding(self, image_path: str) -> list[float] | None:
        if not self.available():
            return None
        import cv2
        import numpy as np

        with self._lock:
            detector, recognizer = self._load()
            image = cast(Any, cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR))
            if image is None:
                return None
            height, width = int(image.shape[0]), int(image.shape[1])
            scale = 1280 / max(height, width)
            if scale < 1.0:
                width, height = int(width * scale), int(height * scale)
                resized = cast(Any, cv2.resize(image, (width, height)))
                image = resized
            detector.setInputSize((width, height))
            _, faces = detector.detect(image)
            if faces is None or len(faces) == 0:
                return None
            face = max(faces, key=lambda f: float(f[2]) * float(f[3]))
            feature = recognizer.feature(recognizer.alignCrop(image, face))
            return [float(v) for v in feature.flatten()]
