"""3D shot analysis → editable storyboard (phase 6).

Builds `spec.layout3d` and a composer `CompositionScene` from a ShotSpec's
subjects, depth and FOV (pure maths in `film/scene_solver.py`), turns an
analysed video into a film project whose shots open the composer pre-seeded
with figures, props, the solved camera and keyframes from optical flow, and
folds composer edits back into the shot's spec so the prompt follows the 3D
scene (`describe_camera`).
"""

from __future__ import annotations

import hashlib
import json
import logging
from threading import RLock
from typing import Any

from _routes._errors import HTTPError
from film.film_models import CompositionScene, FilmProject, FilmShot
from film.scene_api_types import DescribeSceneResponse, SceneBuildRequest, SceneBuildResponse, ShotSpecUpdateRequest
from film.scene_solver import (
    blockout_svg,
    camera_move_for,
    composer_scene_from_layout,
    layout_from_composition,
    layout_from_spec,
    reprojection_error,
)
from film.shot_spec import ShotSpec, SpecLayout3D
from film.shot_spec_fusion import apply_pose_result, apply_user
from film.shot_vocabulary import camera_sentence, describe_camera
from film.video_analysis_models import AnalyzedShot, VideoAnalysis
from handlers.base import StateHandlerBase
from handlers.film_handler import FilmHandler
from handlers.jobs_handler import JobsHandler
from handlers.video_analysis_handler import VideoAnalysisHandler
from handlers.vision_handler import VisionHandler
from state.app_state_types import AppState

logger = logging.getLogger(__name__)


#: Bumped when seeding improves, so untouched older seeds are re-seeded.
#: 2: close-ups, groups and body parts (r21). 3: worn items, extra faces (r22).
#: 4: whole-body boxes overrule the shot-size words; face figures are "person" (r23).
#: 5: figures take the people's poses (DWPose).
SEED_VERSION = 5


def seed_fingerprint(composition: CompositionScene) -> str:
    data = composition.model_dump(mode="json", exclude={"seed"})
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def untouched_seed(composition: CompositionScene) -> bool:
    """An app seed (any version) that nobody has edited since."""
    _, _, fingerprint = composition.seed.partition(":")
    return bool(fingerprint) and fingerprint == seed_fingerprint(composition)


def stale_seed(composition: CompositionScene) -> bool:
    """An app seed from an older SEED_VERSION that nobody has edited since."""
    version, _, fingerprint = composition.seed.partition(":")
    return bool(fingerprint) and version != f"v{SEED_VERSION}" and fingerprint == seed_fingerprint(composition)


class SceneHandler(StateHandlerBase):
    def __init__(
        self,
        state: AppState,
        lock: RLock,
        video_analysis: VideoAnalysisHandler,
        film: FilmHandler,
        jobs: JobsHandler | None = None,
        vision: VisionHandler | None = None,
    ) -> None:
        super().__init__(state, lock)
        self._analysis = video_analysis
        self._film = film
        self._jobs = jobs
        self._vision = vision

    # ---- pure builds ---------------------------------------------------------------

    def build(self, req: SceneBuildRequest) -> SceneBuildResponse:
        spec = req.spec
        layout = spec.layout3d if spec.is_locked("layout3d") and spec.layout3d.objects else layout_from_spec(spec)
        layout.depth_map_path = spec.layout3d.depth_map_path
        move = req.camera_move or camera_move_for(spec)
        composition = composer_scene_from_layout(layout, duration=req.duration_seconds, move=move, motion=spec.motion)
        words = describe_camera(layout)
        return SceneBuildResponse(
            layout3d=layout,
            composition=composition,
            camera_words=words,
            camera_sentence=camera_sentence(words),
            reprojection_error=reprojection_error(spec, layout) if spec.subjects else 0.0,
            svg=blockout_svg(layout),
        )

    @staticmethod
    def describe(layout: SpecLayout3D) -> DescribeSceneResponse:
        words = describe_camera(layout)
        return DescribeSceneResponse(camera_words=words, camera_sentence=camera_sentence(words))

    # ---- storyboard from an analysed video -------------------------------------------

    def storyboard3d(self, analysis_id: str, *, project_id: str = "", name: str = "") -> FilmProject:
        """Reconstruct (or reuse) the film project and seed every shot with a
        composer scene + isometric thumbnail from its spec. One `scene_build` job."""
        analysis = self._analysis.load(analysis_id)
        if not analysis.shots:
            raise HTTPError(400, "Detect shots before building a 3D storyboard.")
        job_id = ""
        if self._jobs is not None:
            job_id = self._jobs.start(
                "scene_build",
                title=analysis.title or analysis.source.file_name,
                inputs={"analysis_id": analysis_id},
                params={"shots": len(analysis.shots)},
            ).id
        try:
            project = self._project_for(analysis, project_id=project_id, name=name)
            built = 0
            with self.lock:
                project = self._film.store.load(project.id)
                by_source = {s.source_ref.analysis_shot_id: s for _, s in _walk(project) if s.source_ref is not None}
                for analysed in analysis.shots:
                    film_shot = by_source.get(analysed.id)
                    if film_shot is None:
                        continue
                    self._seed_shot(project, film_shot, analysed.spec, analysed.duration)
                    built += 1
                self._film.store.save(project)
            if self._jobs is not None and job_id:
                self._jobs.complete(job_id, [str(self._film.store.captures_dir(project.id) / s.blockout_path.split("/")[-1]) for _, s in _walk(project) if s.blockout_path], metrics={"shots_built": built})
            analysis.reconstructed_project_id = project.id
            self._analysis.store.save(analysis)
            return project
        except HTTPError as exc:
            if self._jobs is not None and job_id:
                self._jobs.fail(job_id, str(exc.detail))
            raise

    def _project_for(self, analysis: VideoAnalysis, *, project_id: str, name: str) -> FilmProject:
        wanted = project_id or analysis.reconstructed_project_id
        if wanted and self._film.store.exists(wanted):
            project = self._film.store.load(wanted)
            linked = {s.source_ref.analysis_shot_id for _, s in _walk(project) if s.source_ref is not None}
            if all(shot.id in linked for shot in analysis.shots):
                return project
        return self._analysis.reconstruct(analysis.id, project_id=project_id, name=name)

    def seed_missing(self, project_id: str, analysis: VideoAnalysis) -> int:
        """Seed a composer scene + blockout into every shot of `project_id`
        that came from `analysis` and has none yet, or only an untouched seed
        from an older SEED_VERSION; a shot the user composed is left alone.
        Returns how many shots were seeded."""
        by_id = {s.id: s for s in analysis.shots}
        seeded = 0
        posed = False
        with self.lock:
            project = self._film.store.load(project_id)
            for _, film_shot in _walk(project):
                ref = film_shot.source_ref
                if (film_shot.composition is not None and not stale_seed(film_shot.composition)) or ref is None or ref.analysis_shot_id not in by_id:
                    continue
                analysed = by_id[ref.analysis_shot_id]
                posed = self._backfill_poses(analysis, analysed) or posed
                self._seed_shot(project, film_shot, analysed.spec, analysed.duration)
                seeded += 1
            if seeded:
                self._film.store.save(project)
        if posed:
            self._analysis.store.save(analysis)
        return seeded

    def _backfill_poses(self, analysis: VideoAnalysis, shot: AnalyzedShot) -> bool:
        """Shots analysed before the pose component have no poses: read them
        once from the frame the subjects came from (the middle one)."""
        spec = shot.spec
        if self._vision is None or spec.poses or "poses" in spec.provenance or not shot.frames:
            return False
        frame = self._analysis.store.directory(analysis.id) / shot.frames[len(shot.frames) // 2].path
        if not frame.is_file():
            return False
        result = self._vision.pose(str(frame))
        if result is None:
            return False
        apply_pose_result(spec, result)
        return True

    def seed_shot(self, project: FilmProject, film_shot: FilmShot, spec: ShotSpec, duration: float) -> None:
        """Seed one shot's composer scene + blockout from a spec (image reproduce)
        unless the user has composed it: only a missing scene or one still as
        the app seeded it is (re)seeded."""
        if film_shot.composition is not None and not untouched_seed(film_shot.composition):
            return
        self._seed_shot(project, film_shot, spec, duration)

    def _seed_shot(self, project: FilmProject, film_shot: FilmShot, spec: ShotSpec, duration: float) -> None:
        # The stored layout is what the solver gave at analysis time; seeding
        # solves again unless the user set or locked it.
        kept = spec.layout3d.objects and (spec.is_locked("layout3d") or spec.provenance.get("layout3d") == "user")
        layout = spec.layout3d
        if not kept and any(len(s.bbox) == 4 for s in spec.subjects):
            try:
                layout = layout_from_spec(spec)
            except (ValueError, ZeroDivisionError):
                layout = spec.layout3d
        elif not spec.layout3d.objects:
            layout = layout_from_spec(spec)
        move = camera_move_for(spec)
        composition = composer_scene_from_layout(layout, duration=max(0.5, duration), move=move, motion=spec.motion, framing=film_shot.framing)
        # Figures stand for the shot's cast: link them in order, so the
        # composer shows (and continuity checks) the right character.
        cast = [c.asset_id for c in film_shot.characters]
        for figure, asset_id in zip((o for o in composition.objects if o.type == "figure"), cast):
            figure.asset_id = asset_id
        composition.seed = f"v{SEED_VERSION}:{seed_fingerprint(composition)}"
        film_shot.composition = composition
        film_shot.framing = composition.framing
        film_shot.camera_move = move
        captures = self._film.store.captures_dir(project.id)
        captures.mkdir(parents=True, exist_ok=True)
        name = f"{film_shot.id}-blockout.svg"
        (captures / name).write_text(blockout_svg(layout, title=film_shot.title), encoding="utf-8")
        film_shot.blockout_path = f"captures/{name}"
        if film_shot.status == "draft":
            film_shot.status = "composed"

    # ---- composer edits back into the spec ---------------------------------------------

    def update_shot_spec(self, analysis_id: str, shot_id: str, req: ShotSpecUpdateRequest) -> VideoAnalysis:
        """Apply section edits (or a composer scene) to an analysed shot's spec;
        the camera words are re-derived from the 3D layout and the prompt follows."""
        analysis = self._analysis.load(analysis_id)
        shot = analysis.shot(shot_id)
        if shot is None:
            raise HTTPError(404, f"No shot {shot_id} in this analysis")
        patch: dict[str, Any] = dict(req.sections)
        if req.composition is not None:
            layout = layout_from_composition(req.composition, base=shot.spec.layout3d)
            patch["layout3d"] = layout.model_dump(mode="json")
        if patch:
            apply_user(shot.spec, patch)
        if req.locks:
            for section, locked in req.locks.items():
                shot.spec.locks[section] = bool(locked)
        if "layout3d" in patch and not shot.spec.is_locked("camera"):
            words = describe_camera(shot.spec.layout3d)
            camera = shot.spec.camera
            camera.shot_size = words.get("shot_size", camera.shot_size)
            camera.angle = words.get("angle", camera.angle)
            camera.height = words.get("height", camera.height)
            if words.get("lens_estimate"):
                camera.lens_estimate = words["lens_estimate"]
            if words.get("focal_mm"):
                try:
                    camera.focal_mm = float(words["focal_mm"])
                except ValueError:
                    pass
            shot.spec.set_section("camera", "user", 1.0)
            shot.visual.shot_size = camera.shot_size or shot.visual.shot_size
            shot.visual.angle = camera.angle or shot.visual.angle
            shot.visual.camera_height = camera.height or shot.visual.camera_height
        shot.provenance = "user"
        if not shot.prompts.edited:
            shot.prompts = self._analysis.compose_prompts(analysis, shot)
        self._analysis.store.save(analysis)
        return analysis


def _walk(project: FilmProject):  # type: ignore[no-untyped-def]
    for scene in sorted(project.scenes, key=lambda s: s.order):
        for shot in sorted(scene.shots, key=lambda s: s.order):
            yield scene, shot
