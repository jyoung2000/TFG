"""Whole-body pose (DWPose) on ONNX Runtime: who stands how in an image.

The weights (`ckpts/pose/yolox_l.onnx` person detector + `dw-ll_ucoco_384.onnx`
RTMPose whole-body model) and the pre/post-processing (`preprocessing/dwpose/
onnxdet.py`, `onnxpose.py`, Apache-2.0, Alibaba) come from the WanGP checkout,
which ships them for its pose-guided video. Only those two helper files are
loaded - by path, so neither WanGP's package nor torch is imported here.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from types import ModuleType
from typing import Any

from PIL import Image

from services.vision.protocol import PosePerson, PoseResult

logger = logging.getLogger(__name__)

POSE_MODEL = "dwpose-ll-ucoco-384"
POSE_ESTIMATED_MB = 900
#: Body (17) + feet (6) of the 133 whole-body points: what the figure rig uses.
BODY_AND_FEET = 23
_DETECTOR = "yolox_l.onnx"
_POSE = "dw-ll_ucoco_384.onnx"


def _load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"tfg_dwpose_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DwposeEstimator:
    def __init__(self, wangp_root: Path | None, device: str = "auto") -> None:
        self._root = wangp_root
        self._device = device
        self._det: Any = None
        self._pose: Any = None
        self._detect: Any = None
        self._estimate: Any = None

    @property
    def weights_dir(self) -> Path | None:
        return self._root / "ckpts" / "pose" if self._root is not None else None

    @property
    def available(self) -> bool:
        folder = self.weights_dir
        return folder is not None and (folder / _DETECTOR).is_file() and (folder / _POSE).is_file()

    @property
    def loaded(self) -> bool:
        return self._pose is not None

    def load(self) -> None:
        if self.loaded:
            return
        folder = self.weights_dir
        if folder is None or self._root is None or not self.available:
            raise RuntimeError(f"DWPose weights not found in {folder} (pose/{_DETECTOR}, pose/{_POSE})")
        code = self._root / "preprocessing" / "dwpose"
        if not (code / "onnxdet.py").is_file() or not (code / "onnxpose.py").is_file():
            raise RuntimeError(f"DWPose code not found in {code}")
        import onnxruntime as ort  # pyright: ignore[reportMissingImports, reportMissingTypeStubs]

        ort_any: Any = ort
        providers = ["CPUExecutionProvider"]
        if self._device != "cpu" and "CUDAExecutionProvider" in ort_any.get_available_providers():
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        self._detect = _load_module(code / "onnxdet.py").inference_detector
        self._estimate = _load_module(code / "onnxpose.py").inference_pose
        self._det = ort_any.InferenceSession(str(folder / _DETECTOR), providers=providers)
        self._pose = ort_any.InferenceSession(str(folder / _POSE), providers=providers)
        logger.info("Loaded DWPose on %s", providers[0])

    def unload(self) -> None:
        self._det = self._pose = None

    def estimate(self, image: Image.Image) -> PoseResult:
        import numpy as np

        self.load()
        rgb = np.asarray(image.convert("RGB"))
        height, width = rgb.shape[:2]
        boxes = self._detect(self._det, rgb)
        if len(boxes) == 0:
            return PoseResult(model=POSE_MODEL, people=[])
        keypoints, scores = self._estimate(self._pose, boxes, rgb)
        people: list[PosePerson] = []
        for box, points, point_scores in zip(boxes, keypoints, scores):
            x1, y1, x2, y2 = (float(v) for v in box)
            body = [[round(float(p[0]) / width, 4), round(float(p[1]) / height, 4), round(float(s), 3)] for p, s in zip(points[:BODY_AND_FEET], point_scores[:BODY_AND_FEET])]
            people.append(
                PosePerson(
                    bbox=[round(x1 / width, 4), round(y1 / height, 4), round((x2 - x1) / width, 4), round((y2 - y1) / height, 4)],
                    score=round(float(sum(float(s) for s in point_scores[:17]) / 17), 3),
                    keypoints=body,
                )
            )
        return PoseResult(model=POSE_MODEL, people=people)
