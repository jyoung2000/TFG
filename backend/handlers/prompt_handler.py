"""Compiling a shot into the prompt a particular model wants.

Thin by design: the compiler in `film/prompt_compiler.py` is a pure function
and the briefs in `film/prompt_brief.py` are pure translations. This handler's
only job is to find the shot the caller named and refuse an ambiguous request.
"""

from __future__ import annotations

from threading import RLock

from _routes._errors import HTTPError
from film.prompt_api_types import (
    CompiledPromptPayload,
    CompilePromptRequest,
    CompilePromptResponse,
    PromptTargetListResponse,
    PromptTargetPayload,
)
from film.prompt_brief import brief_from_analysis, brief_from_shot
from film.prompt_compiler import GENERIC, TARGETS, ShotBrief, compile_for
from film.video_analysis_store import VideoAnalysisStore
from handlers.base import StateHandlerBase
from handlers.film_handler import FilmHandler
from state.app_state_types import AppState


class PromptHandler(StateHandlerBase):
    def __init__(
        self,
        state: AppState,
        lock: RLock,
        film_handler: FilmHandler,
        analysis_store: VideoAnalysisStore,
    ) -> None:
        super().__init__(state, lock)
        self._film = film_handler
        self._analyses = analysis_store

    def targets(self) -> PromptTargetListResponse:
        """Every convention this app knows, including the fallback.

        Exposed so the UI can show the rule rather than only its output: a user
        who disagrees with how their model was classified can see exactly what
        matched it.
        """
        return PromptTargetListResponse(
            targets=[
                PromptTargetPayload(
                    id=target.id,
                    label=target.label,
                    style=target.style,
                    basis=target.basis,
                    note=target.note,
                    max_chars=target.max_chars,
                    supports_negative=target.supports_negative,
                    renders_audio=target.renders_audio,
                    renders_motion=target.renders_motion,
                    matches=list(target.matches),
                )
                for target in (*TARGETS, GENERIC)
            ]
        )

    def compile(self, req: CompilePromptRequest) -> CompilePromptResponse:
        brief = self._brief_for(req)
        compiled = compile_for(brief, req.models)
        return CompilePromptResponse(
            brief=brief,
            prompts=[
                CompiledPromptPayload(
                    model=result.model,
                    target_id=result.target_id,
                    target_label=result.target_label,
                    style=result.style,
                    basis=result.basis,
                    note=result.note,
                    prompt=result.prompt,
                    negative_prompt=result.negative_prompt,
                    matched=result.matched,
                    dropped=list(result.dropped),
                )
                # Ordered as the caller asked, not as the dict happens to iterate.
                for result in (compiled[model] for model in req.models if model in compiled)
            ],
        )

    def _brief_for(self, req: CompilePromptRequest) -> ShotBrief:
        """Resolve exactly one source, or refuse.

        Guessing between a storyboard shot and an analysed shot would silently
        compile the wrong thing, so an ambiguous request is an error.
        """
        sources = [
            bool(req.brief is not None),
            bool(req.project_id and req.shot_id),
            bool(req.analysis_id and req.analysis_shot_id),
        ]
        if sum(sources) != 1:
            raise HTTPError(
                400,
                "Name exactly one source: a brief, a project shot "
                "(project_id + scene_id + shot_id), or an analysed shot "
                "(analysis_id + analysis_shot_id).",
            )

        if req.brief is not None:
            return req.brief

        if req.project_id:
            project = self._film.get_project(req.project_id)
            found = project.find_shot(req.shot_id)
            if found is None:
                raise HTTPError(404, f"Shot not found: {req.shot_id}")
            scene, shot = found
            return brief_from_shot(project, scene, shot)

        analysis = self._analyses.load(req.analysis_id)
        shot = next((s for s in analysis.shots if s.id == req.analysis_shot_id), None)
        if shot is None:
            raise HTTPError(404, f"Analysed shot not found: {req.analysis_shot_id}")
        return brief_from_analysis(analysis, shot)
