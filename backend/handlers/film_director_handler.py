"""AI Director: native command registry + LLM planning + storyboard generation.

Follows Open Media's MCP-bridge principle: every command maps 1:1 onto film
mutations the UI already performs through FilmHandler — the director mutates
the same persisted film project the UI reads, never a hidden copy. The
natural-language path (Gemini via the fakeable HTTPClient, same pattern as
suggest_gap_prompt_handler) only *plans* a list of these commands; execution
is always the structured registry.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from threading import RLock

from pydantic import BaseModel, Field, ValidationError

from _routes._errors import HTTPError
from film.film_api_types import (
    CreateAssetRequest,
    CreateSceneRequest,
    CreateShotRequest,
    DirectorCommandRequest,
    DirectorCommandResponse,
    DirectorCommandResult,
    DirectorInstructRequest,
    DirectorInstructResponse,
    GenerateShotRequest,
    GenerateStoryboardRequest,
    GenerateStoryboardResponse,
    UpdateAssetRequest,
    UpdateSceneRequest,
    UpdateShotRequest,
)
from film.film_models import (
    CAMERA_ANGLE_LABELS,
    CAMERA_ELEVATION_LABELS,
    CAMERA_MOVE_LABELS,
    COMPOSITION_LABELS,
    SHOT_SIZE_LABELS,
    FilmAsset,
    FilmProject,
    FilmScene,
    FilmShot,
    ShotCharacter,
    ShotFraming,
)
from film.film_prompt import framing_summary, synthesize_prompt
from film.script_parser import parse_script, suggest_duration, suggest_shot_size
from handlers.base import StateHandlerBase
from handlers.film_generation_handler import FilmGenerationHandler
from handlers.film_handler import FilmHandler
from services.interfaces import HTTPClient, HttpTimeoutError, JSONValue
from state.app_state_types import AppState

logger = logging.getLogger(__name__)

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"


class _GeminiPart(BaseModel):
    text: str


class _GeminiContent(BaseModel):
    parts: list[_GeminiPart] = Field(min_length=1)


class _GeminiCandidate(BaseModel):
    content: _GeminiContent


class _GeminiResponsePayload(BaseModel):
    candidates: list[_GeminiCandidate] = Field(min_length=1)


class _PlannedCommand(BaseModel):
    name: str
    params: dict[str, object] = Field(default_factory=dict)


class _DirectorPlan(BaseModel):
    summary: str = ""
    commands: list[_PlannedCommand] = Field(default_factory=list[_PlannedCommand])


class _StoryboardShotPlan(BaseModel):
    description: str = ""
    action: str = ""
    dialogue: str = ""
    shot_size: str = "medium"
    camera_angle: str = "front"
    camera_elevation: str = "eye"
    composition: str = "center"
    camera_move: str = "static"
    duration_seconds: float = 4.0
    characters: list[str] = Field(default_factory=list[str])


class _StoryboardScenePlan(BaseModel):
    title: str = ""
    description: str = ""
    time_of_day: str = ""
    mood: str = ""
    shots: list[_StoryboardShotPlan] = Field(default_factory=list[_StoryboardShotPlan])


class _StoryboardPlan(BaseModel):
    characters: list[str] = Field(default_factory=list[str])
    scenes: list[_StoryboardScenePlan] = Field(default_factory=list[_StoryboardScenePlan])


def _param_str(params: dict[str, object], key: str, *, required: bool = True, default: str = "") -> str:
    value = params.get(key, None)
    if value is None:
        if required:
            raise HTTPError(400, f"Missing required parameter: {key}")
        return default
    if not isinstance(value, str):
        raise HTTPError(400, f"Parameter {key} must be a string")
    return value


def _param_float(params: dict[str, object], key: str, default: float) -> float:
    value = params.get(key, None)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPError(400, f"Parameter {key} must be a number")
    return float(value)


class FilmDirectorHandler(StateHandlerBase):
    def __init__(
        self,
        state: AppState,
        lock: RLock,
        film_handler: FilmHandler,
        film_generation_handler: FilmGenerationHandler,
        http: HTTPClient,
    ) -> None:
        super().__init__(state, lock)
        self._film = film_handler
        self._film_generation = film_generation_handler
        self._http = http
        self._commands: dict[str, Callable[[str, dict[str, object]], object]] = {
            "get_project": self._cmd_get_project,
            "get_scene": self._cmd_get_scene,
            "get_shot": self._cmd_get_shot,
            "get_shot_composition": self._cmd_get_shot_composition,
            "list_framing_options": self._cmd_list_framing_options,
            "create_scene": self._cmd_create_scene,
            "update_scene": self._cmd_update_scene,
            "create_shot": self._cmd_create_shot,
            "update_shot": self._cmd_update_shot,
            "set_framing": self._cmd_set_framing,
            "set_camera_motion": self._cmd_set_camera_motion,
            "set_duration": self._cmd_set_duration,
            "add_character": self._cmd_add_character,
            "add_location": self._cmd_add_location,
            "add_prop": self._cmd_add_prop,
            "update_asset": self._cmd_update_asset,
            "assign_character": self._cmd_assign_character,
            "set_location": self._cmd_set_location,
            "apply_pose": self._cmd_apply_pose,
            "generate_shot": self._cmd_generate_shot,
        }

    # ---- Public API ------------------------------------------------------

    def command_names(self) -> list[str]:
        return sorted(self._commands)

    def run_command(self, project_id: str, req: DirectorCommandRequest) -> DirectorCommandResponse:
        result = self._execute(project_id, req.name, req.params)
        return DirectorCommandResponse(results=[result])

    def instruct(self, project_id: str, req: DirectorInstructRequest) -> DirectorInstructResponse:
        if not req.instruction.strip():
            raise HTTPError(400, "Instruction is required")
        plan = self._plan_with_gemini(project_id, req)
        results: list[DirectorCommandResult] = []
        for command in plan.commands:
            result = self._execute(project_id, command.name, command.params)
            results.append(result)
            if not result.ok:
                break
        return DirectorInstructResponse(plan_summary=plan.summary, results=results)

    # ---- Command execution ----------------------------------------------

    def _execute(self, project_id: str, name: str, params: dict[str, object]) -> DirectorCommandResult:
        handler = self._commands.get(name)
        if handler is None:
            return DirectorCommandResult(
                name=name, ok=False, error=f"Unknown command {name!r}. Valid: {', '.join(self.command_names())}"
            )
        try:
            result = handler(project_id, params)
            return DirectorCommandResult(name=name, ok=True, result=result)
        except HTTPError as exc:
            return DirectorCommandResult(name=name, ok=False, error=str(exc.detail))
        except Exception as exc:  # noqa: BLE001 - a director command must never 500 the batch
            logger.warning("Director command %s failed", name, exc_info=True)
            return DirectorCommandResult(name=name, ok=False, error=str(exc))

    # ---- Individual commands --------------------------------------------

    def _summarize_project(self, project: FilmProject) -> dict[str, object]:
        return {
            "id": project.id,
            "assets": [
                {"id": a.id, "kind": a.kind, "name": a.name, "description": a.description}
                for a in project.assets
            ],
            "scenes": [
                {
                    "id": scene.id,
                    "order": scene.order,
                    "title": scene.title,
                    "location_id": scene.location_id,
                    "character_ids": scene.character_ids,
                    "shots": [
                        {
                            "id": shot.id,
                            "order": shot.order,
                            "title": shot.title,
                            "duration_seconds": shot.duration_seconds,
                            "framing": framing_summary(shot),
                            "status": shot.status,
                        }
                        for shot in sorted(scene.shots, key=lambda s: s.order)
                    ],
                }
                for scene in sorted(project.scenes, key=lambda s: s.order)
            ],
            "pose_names": sorted({p.name for p in project.pose_library}),
        }

    def _cmd_get_project(self, project_id: str, params: dict[str, object]) -> object:
        del params
        return self._summarize_project(self._film.get_project(project_id))

    def _cmd_get_scene(self, project_id: str, params: dict[str, object]) -> object:
        scene_id = _param_str(params, "scene_id")
        project = self._film.get_project(project_id)
        scene = project.scene(scene_id)
        if scene is None:
            raise HTTPError(404, f"Scene not found: {scene_id}")
        return scene.model_dump()

    def _find_shot(self, project_id: str, params: dict[str, object]) -> tuple[str, str]:
        shot_id = _param_str(params, "shot_id")
        project = self._film.get_project(project_id)
        found = project.find_shot(shot_id)
        if found is None:
            raise HTTPError(404, f"Shot not found: {shot_id}")
        return found[0].id, shot_id

    def _cmd_get_shot(self, project_id: str, params: dict[str, object]) -> object:
        shot_id = _param_str(params, "shot_id")
        project = self._film.get_project(project_id)
        found = project.find_shot(shot_id)
        if found is None:
            raise HTTPError(404, f"Shot not found: {shot_id}")
        shot = found[1].model_dump()
        shot.pop("composition", None)  # too large for a summary payload
        return shot

    def _cmd_get_shot_composition(self, project_id: str, params: dict[str, object]) -> object:
        shot_id = _param_str(params, "shot_id")
        project = self._film.get_project(project_id)
        found = project.find_shot(shot_id)
        if found is None:
            raise HTTPError(404, f"Shot not found: {shot_id}")
        composition = found[1].composition
        return composition.model_dump() if composition is not None else None

    def _cmd_list_framing_options(self, project_id: str, params: dict[str, object]) -> object:
        del project_id, params
        return {
            "shot_size": SHOT_SIZE_LABELS,
            "camera_angle": CAMERA_ANGLE_LABELS,
            "camera_elevation": CAMERA_ELEVATION_LABELS,
            "composition": COMPOSITION_LABELS,
            "camera_move": CAMERA_MOVE_LABELS,
        }

    def _cmd_create_scene(self, project_id: str, params: dict[str, object]) -> object:
        req = CreateSceneRequest(
            title=_param_str(params, "title", required=False),
            description=_param_str(params, "description", required=False),
            mood=_param_str(params, "mood", required=False),
            lighting=_param_str(params, "lighting", required=False),
            time_of_day=_param_str(params, "time_of_day", required=False),
        )
        return self._film.create_scene(project_id, req).model_dump(exclude={"shots"})

    def _cmd_update_scene(self, project_id: str, params: dict[str, object]) -> object:
        scene_id = _param_str(params, "scene_id")
        payload = {k: v for k, v in params.items() if k != "scene_id"}
        try:
            req = UpdateSceneRequest.model_validate(payload)
        except ValidationError as exc:
            raise HTTPError(400, f"Invalid scene update: {exc}") from exc
        return self._film.update_scene(project_id, scene_id, req).model_dump(exclude={"shots"})

    def _cmd_create_shot(self, project_id: str, params: dict[str, object]) -> object:
        scene_id = _param_str(params, "scene_id")
        req = CreateShotRequest(
            title=_param_str(params, "title", required=False),
            description=_param_str(params, "description", required=False),
            duration_seconds=_param_float(params, "duration_seconds", 4.0),
            action=_param_str(params, "action", required=False),
            dialogue=_param_str(params, "dialogue", required=False),
        )
        shot = self._film.create_shot(project_id, scene_id, req)
        return {"id": shot.id, "title": shot.title, "order": shot.order}

    def _cmd_update_shot(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        payload = {k: v for k, v in params.items() if k != "shot_id"}
        try:
            req = UpdateShotRequest.model_validate(payload)
        except ValidationError as exc:
            raise HTTPError(400, f"Invalid shot update: {exc}") from exc
        shot = self._film.update_shot(project_id, scene_id, shot_id, req)
        return {"id": shot.id, "framing": framing_summary(shot), "status": shot.status}

    def _cmd_set_framing(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        project = self._film.get_project(project_id)
        found = project.find_shot(shot_id)
        assert found is not None
        current = found[1].framing
        try:
            framing = ShotFraming(
                shot_size=params.get("shot_size", current.shot_size),  # type: ignore[arg-type]
                camera_angle=params.get("camera_angle", current.camera_angle),  # type: ignore[arg-type]
                camera_elevation=params.get("camera_elevation", current.camera_elevation),  # type: ignore[arg-type]
                composition=params.get("composition", current.composition),  # type: ignore[arg-type]
                fov_deg=_param_float(params, "fov_deg", current.fov_deg),
                ots_foreground_id=current.ots_foreground_id,
                ots_subject_id=current.ots_subject_id,
            )
        except ValidationError as exc:
            raise HTTPError(400, f"Invalid framing: {exc}") from exc
        shot = self._film.update_shot(
            project_id, scene_id, shot_id, UpdateShotRequest(framing=framing)
        )
        return {"id": shot.id, "framing": framing_summary(shot)}

    def _cmd_set_camera_motion(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        move = _param_str(params, "camera_move")
        if move not in CAMERA_MOVE_LABELS:
            raise HTTPError(400, f"Invalid camera_move: {move}. Valid: {', '.join(CAMERA_MOVE_LABELS)}")
        shot = self._film.update_shot(
            project_id,
            scene_id,
            shot_id,
            UpdateShotRequest.model_validate({"camera_move": move}),
        )
        return {"id": shot.id, "camera_move": shot.camera_move}

    def _cmd_set_duration(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        duration = _param_float(params, "duration_seconds", 0.0)
        if duration <= 0:
            raise HTTPError(400, "duration_seconds must be positive")
        shot = self._film.update_shot(
            project_id, scene_id, shot_id, UpdateShotRequest(duration_seconds=duration)
        )
        return {"id": shot.id, "duration_seconds": shot.duration_seconds}

    def _create_asset(self, project_id: str, params: dict[str, object], kind: str) -> object:
        name = _param_str(params, "name")
        project = self._film.get_project(project_id)
        for asset in project.assets:
            if asset.kind == kind and asset.name.strip().lower() == name.strip().lower():
                return {"id": asset.id, "name": asset.name, "existing": True}
        req = CreateAssetRequest(
            kind=kind,  # type: ignore[arg-type]
            name=name,
            description=_param_str(params, "description", required=False),
            appearance=_param_str(params, "appearance", required=False),
            wardrobe=_param_str(params, "wardrobe", required=False),
            environment=_param_str(params, "environment", required=False),
            lighting=_param_str(params, "lighting", required=False),
            atmosphere=_param_str(params, "atmosphere", required=False),
            prop_details=_param_str(params, "prop_details", required=False),
        )
        asset = self._film.create_asset(project_id, req)
        return {"id": asset.id, "name": asset.name, "existing": False}

    def _cmd_add_character(self, project_id: str, params: dict[str, object]) -> object:
        return self._create_asset(project_id, params, "character")

    def _cmd_add_location(self, project_id: str, params: dict[str, object]) -> object:
        return self._create_asset(project_id, params, "location")

    def _cmd_add_prop(self, project_id: str, params: dict[str, object]) -> object:
        return self._create_asset(project_id, params, "prop")

    def _cmd_update_asset(self, project_id: str, params: dict[str, object]) -> object:
        asset_id = _param_str(params, "asset_id")
        payload = {k: v for k, v in params.items() if k != "asset_id"}
        try:
            req = UpdateAssetRequest.model_validate(payload)
        except ValidationError as exc:
            raise HTTPError(400, f"Invalid asset update: {exc}") from exc
        asset = self._film.update_asset(project_id, asset_id, req)
        return {"id": asset.id, "name": asset.name}

    def _resolve_asset_id(self, project: FilmProject, params: dict[str, object], kind: str) -> str:
        asset_id = _param_str(params, "asset_id", required=False)
        if asset_id:
            if project.asset(asset_id) is None:
                raise HTTPError(404, f"Asset not found: {asset_id}")
            return asset_id
        name = _param_str(params, "name")
        for asset in project.assets:
            if asset.kind == kind and asset.name.strip().lower() == name.strip().lower():
                return asset.id
        raise HTTPError(404, f"No {kind} named {name!r}. Create it first with add_{kind}.")

    def _cmd_assign_character(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        project = self._film.get_project(project_id)
        asset_id = self._resolve_asset_id(project, params, "character")
        found = project.find_shot(shot_id)
        assert found is not None
        shot = found[1]
        characters = [c for c in shot.characters if c.asset_id != asset_id]
        characters.append(
            ShotCharacter(
                asset_id=asset_id,
                pose_name=_param_str(params, "pose_name", required=False),
                emotion=_param_str(params, "emotion", required=False),
                position_hint=_param_str(params, "position_hint", required=False),
            )
        )
        updated = self._film.update_shot(
            project_id, scene_id, shot_id, UpdateShotRequest(characters=characters)
        )
        return {"id": updated.id, "characters": [c.asset_id for c in updated.characters]}

    def _cmd_set_location(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        project = self._film.get_project(project_id)
        asset_id = self._resolve_asset_id(project, params, "location")
        updated = self._film.update_shot(
            project_id, scene_id, shot_id, UpdateShotRequest(location_id=asset_id)
        )
        return {"id": updated.id, "location_id": updated.location_id}

    def _cmd_apply_pose(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        pose_name = _param_str(params, "pose_name")
        project = self._film.get_project(project_id)
        asset_id = self._resolve_asset_id(project, params, "character")
        found = project.find_shot(shot_id)
        assert found is not None
        shot = found[1]
        characters = list(shot.characters)
        for index, character in enumerate(characters):
            if character.asset_id == asset_id:
                characters[index] = character.model_copy(update={"pose_name": pose_name})
                break
        else:
            characters.append(ShotCharacter(asset_id=asset_id, pose_name=pose_name))
        updated = self._film.update_shot(
            project_id, scene_id, shot_id, UpdateShotRequest(characters=characters)
        )
        return {"id": updated.id, "pose_applied": pose_name}

    def _cmd_generate_shot(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        kind = _param_str(params, "kind", required=False, default="preview")
        if kind not in ("preview", "final"):
            raise HTTPError(400, "kind must be 'preview' or 'final'")
        response = self._film_generation.queue_shot(
            project_id, scene_id, shot_id, GenerateShotRequest(kind=kind)  # type: ignore[arg-type]
        )
        return {"status": response.status, "version_number": response.version_number}

    # ---- Gemini planning -------------------------------------------------

    def _gemini_key(self) -> str:
        with self.lock:
            key = self.state.app_settings.gemini_api_key
        if not key:
            raise HTTPError(400, "GEMINI_API_KEY_MISSING")
        return key

    def _call_gemini(self, system_text: str, user_text: str) -> str:
        key = self._gemini_key()
        contents: list[JSONValue] = [{"role": "user", "parts": [{"text": user_text}]}]
        payload: dict[str, JSONValue] = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": system_text}]},
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 8192, "responseMimeType": "application/json"},
        }
        try:
            response = self._http.post(
                _GEMINI_URL,
                headers={"Content-Type": "application/json", "x-goog-api-key": key},
                json_payload=payload,
                timeout=60,
            )
        except HttpTimeoutError as exc:
            raise HTTPError(504, "Gemini API request timed out") from exc
        except Exception as exc:
            raise HTTPError(500, str(exc)) from exc
        if response.status_code != 200:
            raise HTTPError(response.status_code, f"Gemini API error: {response.text}")
        try:
            parsed = _GeminiResponsePayload.model_validate(response.json())
        except ValidationError as exc:
            raise HTTPError(500, "GEMINI_PARSE_ERROR") from exc
        return parsed.candidates[0].content.parts[0].text

    @staticmethod
    def _parse_json_block(text: str) -> object:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise HTTPError(500, f"LLM returned invalid JSON: {exc}") from exc

    def _plan_with_gemini(self, project_id: str, req: DirectorInstructRequest) -> _DirectorPlan:
        project = self._film.get_project(project_id)
        summary = json.dumps(self._summarize_project(project), indent=1)
        focus = ""
        if req.scene_id:
            focus += f"\nThe user is currently looking at scene {req.scene_id}."
        if req.shot_id:
            focus += f"\nThe user is currently looking at shot {req.shot_id}."
        system_text = (
            "You are the AI Director of a local filmmaking app. Translate the user's "
            "instruction into a JSON plan of commands run against the film project.\n"
            f"Available commands: {', '.join(self.command_names())}.\n"
            "Command parameter notes:\n"
            "- create_scene: title, description, mood, lighting, time_of_day\n"
            "- create_shot: scene_id, title, description, duration_seconds, action, dialogue\n"
            "- set_framing: shot_id, shot_size(xwide|wide|full|medium|mcu|closeup|xcu), "
            "camera_angle(front|threeQuarterLeft|threeQuarterRight|profile|back|ots|pov|dutch), "
            "camera_elevation(eye|low|high|bird|worm), composition(center|leftThird|rightThird|"
            "upperThird|lowerThird|negativeSpace|symmetrical|leadingLines)\n"
            "- set_camera_motion: shot_id, camera_move(static|push_in|pull_out|pan_left|pan_right|"
            "tilt_up|tilt_down|dolly_left|dolly_right|orbit|follow)\n"
            "- add_character/add_location/add_prop: name, description (+appearance/wardrobe for "
            "characters, environment/lighting for locations)\n"
            "- assign_character: shot_id, name (or asset_id), emotion, position_hint\n"
            "- apply_pose: shot_id, name (character), pose_name\n"
            "- set_duration: shot_id, duration_seconds\n"
            "- generate_shot: shot_id, kind(preview|final)\n"
            "Reuse existing assets by name whenever they match; only create what is missing. "
            "Do NOT include generate_shot unless the user explicitly asks to render/generate now.\n"
            'Return ONLY JSON: {"summary": "one sentence", "commands": [{"name": "...", "params": {...}}]}'
        )
        user_text = f"Current project state:\n{summary}\n{focus}\n\nInstruction: {req.instruction}"
        raw = self._call_gemini(system_text, user_text)
        try:
            return _DirectorPlan.model_validate(self._parse_json_block(raw))
        except ValidationError as exc:
            raise HTTPError(500, f"LLM plan did not match the expected schema: {exc}") from exc

    # ---- Storyboard generation ------------------------------------------

    def generate_storyboard(
        self, project_id: str, req: GenerateStoryboardRequest
    ) -> GenerateStoryboardResponse:
        project = self._film.get_project(project_id)
        script = project.script.content
        if not script.strip():
            raise HTTPError(400, "The project script is empty — write or import a script first")
        if project.scenes and not req.replace_existing:
            raise HTTPError(
                409,
                "This project already has scenes. Pass replace_existing=true to regenerate the storyboard.",
            )

        used_llm = False
        if req.use_llm:
            plan = self._storyboard_plan_with_gemini(script, req.target_shots_per_scene)
            used_llm = True
        else:
            plan = self._storyboard_plan_heuristic(script)

        with self.lock:
            project = self._film.store.load(project_id)
            if req.replace_existing:
                project.scenes = []
            character_ids: dict[str, str] = {
                a.name.strip().lower(): a.id for a in project.assets if a.kind == "character"
            }
            characters_created = 0
            for name in plan.characters:
                key = name.strip().lower()
                if not key or key in character_ids:
                    continue
                asset = FilmAsset(kind="character", name=name.strip().title())
                project.assets.append(asset)
                character_ids[key] = asset.id
                characters_created += 1

            shots_created = 0
            for scene_index, scene_plan in enumerate(plan.scenes):
                scene = FilmScene(
                    order=len(project.scenes),
                    title=scene_plan.title or f"Scene {scene_index + 1}",
                    description=scene_plan.description,
                    time_of_day=scene_plan.time_of_day,
                    mood=scene_plan.mood,
                )
                for shot_index, shot_plan in enumerate(scene_plan.shots):
                    framing = ShotFraming()
                    if shot_plan.shot_size in SHOT_SIZE_LABELS:
                        framing.shot_size = shot_plan.shot_size  # type: ignore[assignment]
                    if shot_plan.camera_angle in CAMERA_ANGLE_LABELS:
                        framing.camera_angle = shot_plan.camera_angle  # type: ignore[assignment]
                    if shot_plan.camera_elevation in CAMERA_ELEVATION_LABELS:
                        framing.camera_elevation = shot_plan.camera_elevation  # type: ignore[assignment]
                    if shot_plan.composition in COMPOSITION_LABELS:
                        framing.composition = shot_plan.composition  # type: ignore[assignment]
                    shot = FilmShot(
                        order=shot_index,
                        title=f"Shot {shot_index + 1}",
                        description=shot_plan.description,
                        action=shot_plan.action,
                        dialogue=shot_plan.dialogue,
                        duration_seconds=max(1.0, shot_plan.duration_seconds),
                        framing=framing,
                        status="draft",
                    )
                    if shot_plan.camera_move in CAMERA_MOVE_LABELS:
                        shot.camera_move = shot_plan.camera_move  # type: ignore[assignment]
                    for name in shot_plan.characters:
                        asset_id = character_ids.get(name.strip().lower())
                        if asset_id and all(c.asset_id != asset_id for c in shot.characters):
                            shot.characters.append(ShotCharacter(asset_id=asset_id))
                            if asset_id not in scene.character_ids:
                                scene.character_ids.append(asset_id)
                    scene.shots.append(shot)
                    shots_created += 1
                project.scenes.append(scene)
            self._film.store.save(project)

        # Prompts synthesize lazily on the next shot update; do it now so draft
        # cards show a meaningful prompt immediately.
        with self.lock:
            project = self._film.store.load(project_id)
            for scene in project.scenes:
                for shot in scene.shots:
                    if not shot.prompt_locked:
                        shot.visual_prompt = synthesize_prompt(project, scene, shot)
            self._film.store.save(project)

        return GenerateStoryboardResponse(
            status="draft_created",
            scenes_created=len(plan.scenes),
            shots_created=shots_created,
            characters_created=characters_created,
            used_llm=used_llm,
        )

    def _storyboard_plan_heuristic(self, script: str) -> _StoryboardPlan:
        parsed = parse_script(script)
        plan = _StoryboardPlan()
        seen_characters: set[str] = set()
        for parsed_scene in parsed:
            scene_plan = _StoryboardScenePlan(
                title=parsed_scene.title,
                description=parsed_scene.description,
                time_of_day=parsed_scene.time_of_day,
            )
            for index, parsed_shot in enumerate(parsed_scene.shots):
                scene_plan.shots.append(
                    _StoryboardShotPlan(
                        description=parsed_shot.description,
                        action="" if parsed_shot.dialogue else parsed_shot.description,
                        dialogue=parsed_shot.dialogue,
                        shot_size=suggest_shot_size(index, parsed_shot),
                        duration_seconds=suggest_duration(parsed_shot),
                        characters=parsed_shot.characters,
                    )
                )
            for name in parsed_scene.characters:
                if name.lower() not in seen_characters:
                    seen_characters.add(name.lower())
                    plan.characters.append(name)
            plan.scenes.append(scene_plan)
        if not plan.scenes:
            raise HTTPError(400, "Could not derive any scenes from the script")
        return plan

    def _storyboard_plan_with_gemini(self, script: str, target_shots: int) -> _StoryboardPlan:
        system_text = (
            "You are a professional storyboard artist. Break the screenplay into scenes and "
            f"shots (about {target_shots} shots per scene). Every field must be filled.\n"
            "shot_size: xwide|wide|full|medium|mcu|closeup|xcu\n"
            "camera_angle: front|threeQuarterLeft|threeQuarterRight|profile|back|ots|pov|dutch\n"
            "camera_elevation: eye|low|high|bird|worm\n"
            "composition: center|leftThird|rightThird|upperThird|lowerThird|negativeSpace|symmetrical|leadingLines\n"
            "camera_move: static|push_in|pull_out|pan_left|pan_right|tilt_up|tilt_down|dolly_left|dolly_right|orbit|follow\n"
            "description: detailed visual description (30+ words) usable as an image prompt.\n"
            'Return ONLY JSON: {"characters": ["NAME"], "scenes": [{"title": "...", '
            '"description": "...", "time_of_day": "...", "mood": "...", "shots": '
            '[{"description": "...", "action": "...", "dialogue": "", "shot_size": "medium", '
            '"camera_angle": "front", "camera_elevation": "eye", "composition": "center", '
            '"camera_move": "static", "duration_seconds": 4, "characters": ["NAME"]}]}]}'
        )
        raw = self._call_gemini(system_text, f"Screenplay:\n\n{script}")
        try:
            return _StoryboardPlan.model_validate(self._parse_json_block(raw))
        except ValidationError as exc:
            raise HTTPError(500, f"LLM storyboard did not match the expected schema: {exc}") from exc
