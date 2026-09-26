"""Request/response models for the 3D scene routes (phase 6)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from film.film_models import CameraMove, CompositionScene
from film.shot_spec import ShotSpec, SpecLayout3D


class SceneBuildRequest(BaseModel):
    spec: ShotSpec
    duration_seconds: float = 4.0
    #: Overrides the move derived from `spec.camera.move`.
    camera_move: CameraMove | None = None


class SceneBuildResponse(BaseModel):
    layout3d: SpecLayout3D
    composition: CompositionScene
    camera_words: dict[str, str] = Field(default_factory=dict[str, str])
    camera_sentence: str = ""
    #: Largest reprojection deviation of the layout against the spec's boxes (fraction of the frame).
    reprojection_error: float = 0.0
    svg: str = ""


class DescribeSceneRequest(BaseModel):
    layout3d: SpecLayout3D


class DescribeSceneResponse(BaseModel):
    camera_words: dict[str, str] = Field(default_factory=dict[str, str])
    camera_sentence: str = ""


class ShotSpecUpdateRequest(BaseModel):
    sections: dict[str, Any] = Field(default_factory=dict[str, Any])
    locks: dict[str, bool] | None = None
    #: A composer scene to fold back into `layout3d` (takes precedence over `sections.layout3d`).
    composition: CompositionScene | None = None


class Storyboard3DRequest(BaseModel):
    project_id: str = ""
    name: str = ""
