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
    CompileSpecAllResponse,
    CompileSpecRequest,
    CompileSpecResponse,
    PromptTemplateCreateRequest,
    PromptTemplateListResponse,
    PromptTemplateUpdateRequest,
)
from film.prompt_brief import brief_from_analysis, brief_from_shot
from _routes._errors import HTTPError
from film.prompt_compiler import PromptStyle
from film.prompt_templates import PromptTemplate, TemplateStore
from film.shot_spec import ShotSpec
from handlers.knowledge_handler import KnowledgeHandler
from film.prompt_compiler import GENERIC, TARGETS, ShotBrief, compile_for, PromptHints, SpecCompileResult, compile_from_spec, resolve_target
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
        templates: TemplateStore | None = None,
        knowledge: KnowledgeHandler | None = None,
    ) -> None:
        super().__init__(state, lock)
        self._film = film_handler
        self._analyses = analysis_store
        self._templates = templates
        self._knowledge = knowledge

    # ---- ShotSpec compile ---------------------------------------------------

    def hints(self, spec: ShotSpec, target: str, model: str = "") -> PromptHints | None:
        if self._knowledge is None:
            return None
        resolved, _ = resolve_target(target)
        return self._knowledge.hints_for(spec.attribute_keys(), resolved.id, model=model)

    def compile_spec(self, req: CompileSpecRequest) -> CompileSpecResponse:
        hints = self.hints(req.spec, req.target, req.model) if req.use_hints else None
        result = compile_from_spec(req.spec, req.target, req.style, hints, seed=req.seed)
        return CompileSpecResponse(result=result, hints=hints, spec_keys=req.spec.attribute_keys())

    def compile_spec_all(self, spec: ShotSpec, targets: list[str], styles: list[PromptStyle], *, seed: int | None = None, use_hints: bool = True) -> CompileSpecAllResponse:
        results: dict[str, SpecCompileResult] = {}
        hints: PromptHints | None = None
        for target in targets or [t.id for t in TARGETS]:
            target_hints = self.hints(spec, target) if use_hints else None
            hints = hints or target_hints
            for style in styles or [None]:
                key = f"{resolve_target(target)[0].id}:{style or 'default'}"
                results[key] = compile_from_spec(spec, target, style, target_hints, seed=seed)
        return CompileSpecAllResponse(results=results, hints=hints)

    # ---- templates ----------------------------------------------------------

    def _store(self) -> TemplateStore:
        if self._templates is None:
            raise HTTPError(503, "Prompt templates are not available in this build")
        return self._templates

    def templates(self) -> PromptTemplateListResponse:
        return PromptTemplateListResponse(templates=self._store().list())

    def update_template(self, template_id: str, req: PromptTemplateUpdateRequest) -> PromptTemplate:
        try:
            return self._store().set_instruction(template_id, req.instruction)
        except KeyError as exc:
            raise HTTPError(404, f"Unknown template: {template_id}") from exc
        except ValueError as exc:
            raise HTTPError(400, str(exc)) from exc

    def reset_template(self, template_id: str) -> PromptTemplate:
        return self._store().reset(template_id)

    def create_template(self, req: PromptTemplateCreateRequest) -> PromptTemplate:
        try:
            return self._store().create(req.name, req.instruction, req.description, req.profile)
        except ValueError as exc:
            raise HTTPError(400, str(exc)) from exc

    def delete_template(self, template_id: str) -> bool:
        return self._store().delete(template_id)

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
