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

    def _largest_face(self, image_path: str) -> tuple[Any, Any, float] | None:
        """(image as detected on, the largest face row, the scale it was resized by). Call under the lock."""
        import cv2
        import numpy as np

        detector, _ = self._load()
        image = cast(Any, cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR))
        if image is None:
            return None
        height, width = int(image.shape[0]), int(image.shape[1])
        scale = min(1.0, 1280 / max(height, width))
        if scale < 1.0:
            width, height = int(width * scale), int(height * scale)
            resized = cast(Any, cv2.resize(image, (width, height)))
            image = resized
        detector.setInputSize((width, height))
        _, faces = detector.detect(image)
        if faces is None or len(faces) == 0:
            return None
        return image, max(faces, key=lambda f: float(f[2]) * float(f[3])), scale

    def embedding(self, image_path: str) -> list[float] | None:
        if not self.available():
            return None
        with self._lock:
            found = self._largest_face(image_path)
            if found is None:
                return None
            image, face, _ = found
            _, recognizer = self._load()
            feature = recognizer.feature(recognizer.alignCrop(image, face))
            return [float(v) for v in feature.flatten()]

    def face_points(self, image_path: str) -> tuple[tuple[float, float, float, float], list[tuple[float, float]]] | None:
        if not self.available():
            return None
        with self._lock:
            found = self._largest_face(image_path)
        if found is None:
            return None
        _, face, scale = found
        box = (float(face[0]) / scale, float(face[1]) / scale, float(face[2]) / scale, float(face[3]) / scale)
        points = [(float(face[4 + 2 * i]) / scale, float(face[5 + 2 * i]) / scale) for i in range(5)]
        return box, points

    def face_box(self, image_path: str) -> tuple[float, float, float, float] | None:
        if not self.available():
            return None
        with self._lock:
            found = self._largest_face(image_path)
        if found is None:
            return None
        _, face, scale = found
        return (float(face[0]) / scale, float(face[1]) / scale, float(face[2]) / scale, float(face[3]) / scale)
