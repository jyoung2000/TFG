"""AI Director: native command registry + LLM tool calling + film building.

Follows Open Media's MCP-bridge principle: every command maps 1:1 onto film
mutations the UI already performs through FilmHandler — the director mutates
the same persisted film project the UI reads, never a hidden copy. The
natural-language path runs an LLM (OpenRouter or Gemini, through the fakeable
HTTPClient) in a tool-calling loop where each tool IS a registry command; a
model that answers with a JSON ``{"commands": [...]}`` plan instead of tool
calls is executed the same way. Execution is always the structured registry.
"""

from __future__ import annotations

import base64
import json
import logging
import math
import re
from collections.abc import Callable
from threading import RLock
from typing import cast

from pydantic import BaseModel, Field, ValidationError

from _routes._errors import HTTPError
from film.film_api_types import (
    CreateAssetRequest,
    CreateSceneRequest,
    CreateShotRequest,
    DirectorChatRequest,
    DirectorChatResponse,
    DirectorCommandRequest,
    DirectorCommandResponse,
    DirectorCommandResult,
    DirectorContextDetails,
    DirectorProviderStatus,
    DirectorInstructRequest,
    DirectorInstructResponse,
    DirectorRoleModel,
    DirectorStatusResponse,
    DirectorToolInfo,
    FilmBuildApplyRequest,
    FilmBuildApplyResponse,
    FilmBuildCharacter,
    FilmBuildPlan,
    FilmBuildRequest,
    FilmBuildResponse,
    FilmBuildScene,
    FilmBuildShot,
    GenerateShotRequest,
    GenerateStoryboardRequest,
    GenerateStoryboardResponse,
    OpenRouterModelInfo,
    OpenRouterModelsResponse,
    OpenRouterValidateResponse,
    RefinePromptRequest,
    RefinePromptResponse,
    VisualReviewResponse,
    ReorderRequest,
    UpdateAssetRequest,
    UpdateSceneRequest,
    UpdateScriptRequest,
    UpdateShotRequest,
)
from film.film_models import (
    CAMERA_ANGLE_LABELS,
    CAMERA_ELEVATION_LABELS,
    CAMERA_MOVE_LABELS,
    COMPOSITION_LABELS,
    SHOT_SIZE_LABELS,
    CompositionKeyframe,
    CompositionObject,
    CompositionScene,
    CompositionTransform,
    FilmAsset,
    FilmProject,
    FilmScene,
    FilmShot,
    ShotCharacter,
    ShotFraming,
    ShotGenerationSettings,
    now_ms,
)
from film.film_continuity import previous_in_same_scene
from film.film_prompt import framing_summary, synthesize_prompt
from film.llm_providers import (
    ANTHROPIC_DEFAULT_MODEL,
    XAI_DEFAULT_MODEL,
    AnthropicProvider,
    XAIProvider,
    gemini_list_models,
    GEMINI_DEFAULT_MODEL,
    GeminiProvider,
    LLMMessage,
    LLMProvider,
    LLMReply,
    OpenAICompatibleProvider,
    OpenRouterModel,
    OpenRouterProvider,
    ToolSpec,
    messages_chars,
    openrouter_list_models,
    openrouter_validate_key,
    parse_json_block,
)
from film.script_parser import parse_script, suggest_duration, suggest_shot_size
from handlers.base import StateHandlerBase
from handlers.film_generation_handler import FilmGenerationHandler
from handlers.film_handler import FilmHandler
from services.interfaces import HTTPClient, VideoProcessor
from state.app_settings import AppSettings
from state.app_state_types import AppState

logger = logging.getLogger(__name__)

_MAX_TOOL_STEPS = 12
_OPENROUTER_MODELS_TTL_MS = 10 * 60 * 1000
_KEY_MISSING = (
    "AI_DIRECTOR_KEY_MISSING: connect a text model in Settings → API Keys — an OpenRouter, "
    "Claude, Grok or Gemini key, or a local OpenAI-compatible server for a fully offline "
    "director (or set the OPENROUTER_API_KEY environment variable)"
)

_ROLES = ("script", "storyboard", "director", "continuity", "prompt_refinement")


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


class _ChatSuggestion(BaseModel):
    reply: str = ""
    prompt: str = ""
    negative_prompt: str = ""
    duration_seconds: float | None = None


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


def _param_bool(params: dict[str, object], key: str, default: bool) -> bool:
    value = params.get(key, None)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise HTTPError(400, f"Parameter {key} must be a boolean")
    return value


def _param_str_list(params: dict[str, object], key: str) -> list[str]:
    value = params.get(key, None)
    if value is None:
        return []
    if not isinstance(value, list):
        raise HTTPError(400, f"Parameter {key} must be a list of strings")
    items: list[str] = []
    for item in cast(list[object], value):
        if not isinstance(item, str):
            raise HTTPError(400, f"Parameter {key} must be a list of strings")
        items.append(item)
    return items


def _schema(properties: dict[str, object], required: list[str] | None = None) -> dict[str, object]:
    schema: dict[str, object] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _s(description: str, enum: list[str] | None = None) -> dict[str, object]:
    prop: dict[str, object] = {"type": "string", "description": description}
    if enum:
        prop["enum"] = enum
    return prop


def _n(description: str) -> dict[str, object]:
    return {"type": "number", "description": description}


def _b(description: str) -> dict[str, object]:
    return {"type": "boolean", "description": description}


def _list_s(description: str) -> dict[str, object]:
    return {"type": "array", "items": {"type": "string"}, "description": description}


_SHOT_SIZES = list(SHOT_SIZE_LABELS)
_ANGLES = list(CAMERA_ANGLE_LABELS)
_ELEVATIONS = list(CAMERA_ELEVATION_LABELS)
_COMPOSITIONS = list(COMPOSITION_LABELS)
_MOVES = list(CAMERA_MOVE_LABELS)

_ASSET_PROPS: dict[str, object] = {
    "name": _s("Asset name (reused if one with this name exists)"),
    "description": _s("Short description"),
    "appearance": _s("Physical appearance (characters)"),
    "wardrobe": _s("Wardrobe/costume (characters)"),
    "environment": _s("Environment details (locations)"),
    "lighting": _s("Lighting (locations)"),
    "atmosphere": _s("Atmosphere/weather (locations)"),
    "prop_details": _s("Prop details (props)"),
}


def _build_tool_specs() -> list[ToolSpec]:
    shot_id = _s("Shot id")
    scene_id = _s("Scene id")
    return [
        ToolSpec("get_project", "Compact summary of assets, scenes and shots.", _schema({})),
        ToolSpec("list_assets", "List characters, locations and props with details.", _schema({})),
        ToolSpec("get_scene", "Full scene record.", _schema({"scene_id": scene_id}, ["scene_id"])),
        ToolSpec("get_shot", "Full shot record (without 3D composition).", _schema({"shot_id": shot_id}, ["shot_id"])),
        ToolSpec(
            "get_shot_composition",
            "3D Shot Composer scene for a shot (camera, figures, keyframes).",
            _schema({"shot_id": shot_id}, ["shot_id"]),
        ),
        ToolSpec("list_framing_options", "Valid framing/camera vocabulary.", _schema({})),
        ToolSpec(
            "create_scene",
            "Create a scene.",
            _schema(
                {
                    "title": _s("Scene title"),
                    "description": _s("Scene description"),
                    "mood": _s("Mood"),
                    "lighting": _s("Lighting"),
                    "time_of_day": _s("Time of day"),
                }
            ),
        ),
        ToolSpec(
            "update_scene",
            "Update scene fields.",
            _schema(
                {
                    "scene_id": scene_id,
                    "title": _s("Title"),
                    "description": _s("Description"),
                    "mood": _s("Mood"),
                    "lighting": _s("Lighting"),
                    "time_of_day": _s("Time of day"),
                    "continuity_notes": _s("Continuity notes"),
                },
                ["scene_id"],
            ),
        ),
        ToolSpec("delete_scene", "Delete a scene and its shots.", _schema({"scene_id": scene_id}, ["scene_id"])),
        ToolSpec(
            "create_shot",
            "Create a shot in a scene.",
            _schema(
                {
                    "scene_id": scene_id,
                    "title": _s("Shot title"),
                    "description": _s("Visual description (what the camera sees)"),
                    "duration_seconds": _n("Duration in seconds"),
                    "action": _s("Action beat"),
                    "dialogue": _s("Dialogue line"),
                },
                ["scene_id"],
            ),
        ),
        ToolSpec(
            "update_shot",
            "Update shot text fields.",
            _schema(
                {
                    "shot_id": shot_id,
                    "title": _s("Title"),
                    "description": _s("Description"),
                    "action": _s("Action"),
                    "dialogue": _s("Dialogue"),
                    "emotion": _s("Emotion"),
                    "duration_seconds": _n("Duration in seconds"),
                },
                ["shot_id"],
            ),
        ),
        ToolSpec("delete_shot", "Delete a shot.", _schema({"shot_id": shot_id}, ["shot_id"])),
        ToolSpec(
            "reorder_shots",
            "Reorder shots in a scene.",
            _schema({"scene_id": scene_id, "ordered_shot_ids": _list_s("Shot ids in new order")}, ["scene_id", "ordered_shot_ids"]),
        ),
        ToolSpec(
            "set_framing",
            "Set shot size / camera angle / elevation / composition.",
            _schema(
                {
                    "shot_id": shot_id,
                    "shot_size": _s("Shot size", _SHOT_SIZES),
                    "camera_angle": _s("Camera angle", _ANGLES),
                    "camera_elevation": _s("Camera elevation", _ELEVATIONS),
                    "composition": _s("Composition", _COMPOSITIONS),
                    "fov_deg": _n("Field of view in degrees"),
                },
                ["shot_id"],
            ),
        ),
        ToolSpec(
            "set_camera_motion",
            "Set the camera move.",
            _schema({"shot_id": shot_id, "camera_move": _s("Camera move", _MOVES)}, ["shot_id", "camera_move"]),
        ),
        ToolSpec(
            "set_duration",
            "Set shot duration.",
            _schema({"shot_id": shot_id, "duration_seconds": _n("Seconds")}, ["shot_id", "duration_seconds"]),
        ),
        ToolSpec("add_character", "Create (or reuse) a character asset.", _schema(_ASSET_PROPS, ["name"])),
        ToolSpec("add_location", "Create (or reuse) a location asset.", _schema(_ASSET_PROPS, ["name"])),
        ToolSpec("add_prop", "Create (or reuse) a prop asset.", _schema(_ASSET_PROPS, ["name"])),
        ToolSpec(
            "update_asset",
            "Update an asset's fields.",
            _schema({"asset_id": _s("Asset id"), **_ASSET_PROPS}, ["asset_id"]),
        ),
        ToolSpec(
            "assign_character",
            "Put a character in a shot (by name or asset_id).",
            _schema(
                {
                    "shot_id": shot_id,
                    "name": _s("Character name"),
                    "asset_id": _s("Character asset id"),
                    "emotion": _s("Emotion"),
                    "position_hint": _s("Where in frame, e.g. 'foreground left'"),
                    "pose_name": _s("Pose name"),
                },
                ["shot_id"],
            ),
        ),
        ToolSpec(
            "set_location",
            "Set a shot's location (by name or asset_id).",
            _schema({"shot_id": shot_id, "name": _s("Location name"), "asset_id": _s("Location asset id")}, ["shot_id"]),
        ),
        ToolSpec(
            "apply_pose",
            "Apply a named pose to a character in a shot.",
            _schema({"shot_id": shot_id, "name": _s("Character name"), "asset_id": _s("Character asset id"), "pose_name": _s("Pose name")}, ["shot_id", "pose_name"]),
        ),
        ToolSpec(
            "set_prompt",
            "Override the generation prompt for a shot (locks it against re-synthesis).",
            _schema(
                {"shot_id": shot_id, "visual_prompt": _s("Prompt text"), "negative_prompt": _s("Negative prompt"), "locked": _b("Lock the prompt (default true)")},
                ["shot_id", "visual_prompt"],
            ),
        ),
        ToolSpec(
            "set_generation_settings",
            "Set per-shot generation settings.",
            _schema(
                {
                    "shot_id": shot_id,
                    "model": _s("Model id ('' = project default)"),
                    "resolution": _s("Resolution like 720p ('' = default)"),
                    "seed": _n("Seed (omit for random)"),
                    "quality_preset": _s("Quality preset", ["project", "fast_preview", "balanced", "quality", "custom"]),
                    "continue_from_previous": _b("Use previous shot's last frame as start"),
                },
                ["shot_id"],
            ),
        ),
        ToolSpec("set_script", "Replace the project script text.", _schema({"content": _s("Screenplay text")}, ["content"])),
        ToolSpec("check_continuity", "Continuity warnings for a shot.", _schema({"shot_id": shot_id}, ["shot_id"])),
        ToolSpec(
            "generate_shot",
            "Queue a preview or final render of a shot. Only when the user asks to render.",
            _schema({"shot_id": shot_id, "kind": _s("preview or final", ["preview", "final"])}, ["shot_id"]),
        ),
        ToolSpec(
            "queue_shot",
            "Alias of generate_shot.",
            _schema({"shot_id": shot_id, "kind": _s("preview or final", ["preview", "final"])}, ["shot_id"]),
        ),
        ToolSpec("generate_preview", "Queue a fast preview render of a shot.", _schema({"shot_id": shot_id}, ["shot_id"])),
        ToolSpec("generate_final", "Queue a final-quality render of a shot.", _schema({"shot_id": shot_id}, ["shot_id"])),
        ToolSpec("duplicate_shot", "Duplicate a shot (composition copied, versions reset).", _schema({"shot_id": shot_id}, ["shot_id"])),
        ToolSpec("get_composition", "Alias of get_shot_composition.", _schema({"shot_id": shot_id}, ["shot_id"])),
        ToolSpec("update_character", "Update a character asset (alias of update_asset).", _schema({"asset_id": _s("Asset id"), **_ASSET_PROPS}, ["asset_id"])),
        ToolSpec("update_location", "Update a location asset (alias of update_asset).", _schema({"asset_id": _s("Asset id"), **_ASSET_PROPS}, ["asset_id"])),
        ToolSpec("update_prop", "Update a prop asset (alias of update_asset).", _schema({"asset_id": _s("Asset id"), **_ASSET_PROPS}, ["asset_id"])),
        ToolSpec(
            "assign_prop",
            "Put a prop in a shot (by name or asset_id); a placeholder appears in the composer.",
            _schema({"shot_id": shot_id, "name": _s("Prop name"), "asset_id": _s("Prop asset id")}, ["shot_id"]),
        ),
        ToolSpec("assign_location", "Alias of set_location.", _schema({"shot_id": shot_id, "name": _s("Location name"), "asset_id": _s("Location asset id")}, ["shot_id"])),
        ToolSpec("set_shot_type", "Set the shot size.", _schema({"shot_id": shot_id, "shot_size": _s("Shot size", _SHOT_SIZES)}, ["shot_id", "shot_size"])),
        ToolSpec("set_camera_angle", "Set the camera angle.", _schema({"shot_id": shot_id, "camera_angle": _s("Camera angle", _ANGLES)}, ["shot_id", "camera_angle"])),
        ToolSpec("set_camera_elevation", "Set the camera elevation.", _schema({"shot_id": shot_id, "camera_elevation": _s("Camera elevation", _ELEVATIONS)}, ["shot_id", "camera_elevation"])),
        ToolSpec("set_composition", "Set the frame composition.", _schema({"shot_id": shot_id, "composition": _s("Composition", _COMPOSITIONS)}, ["shot_id", "composition"])),
        ToolSpec(
            "set_ots",
            "Configure an over-the-shoulder relationship: which character is foreground, which is the subject, and which shoulder.",
            _schema(
                {
                    "shot_id": shot_id,
                    "foreground": _s("Foreground character name or asset_id (camera behind them)"),
                    "subject": _s("Subject character name or asset_id (looked toward)"),
                    "shoulder": _s("Shoulder the camera looks over", ["left", "right"]),
                },
                ["shot_id", "foreground", "subject"],
            ),
        ),
        ToolSpec(
            "set_negative_prompt",
            "Set the negative prompt for a shot.",
            _schema({"shot_id": shot_id, "negative_prompt": _s("Negative prompt")}, ["shot_id", "negative_prompt"]),
        ),
        ToolSpec(
            "position_object",
            "Place a composer object (character by name/asset_id, or object id) on the ground plane. x = screen right/left in metres, z = toward camera; hints like 'foreground left' are accepted.",
            _schema(
                {
                    "shot_id": shot_id,
                    "target": _s("Character name, asset_id, or object id"),
                    "x": _n("X position (metres)"),
                    "y": _n("Y position (metres, usually 0)"),
                    "z": _n("Z position (metres)"),
                    "hint": _s("Placement hint", ["foreground left", "foreground right", "background left", "background right", "center", "left", "right"]),
                },
                ["shot_id", "target"],
            ),
        ),
        ToolSpec(
            "rotate_object",
            "Rotate a composer object around the vertical axis (degrees; 0 faces the front camera).",
            _schema({"shot_id": shot_id, "target": _s("Character name, asset_id, or object id"), "yaw_degrees": _n("Yaw in degrees")}, ["shot_id", "target", "yaw_degrees"]),
        ),
        ToolSpec(
            "scale_object",
            "Uniformly scale a composer object.",
            _schema({"shot_id": shot_id, "target": _s("Character name, asset_id, or object id"), "scale": _n("Uniform scale factor")}, ["shot_id", "target", "scale"]),
        ),
        ToolSpec(
            "update_pose",
            "Set individual joint rotations (degrees) on a character in the composer.",
            _schema(
                {
                    "shot_id": shot_id,
                    "target": _s("Character name, asset_id, or object id"),
                    "joints": {"type": "object", "description": "joint name -> [x, y, z] degrees", "additionalProperties": {"type": "array", "items": {"type": "number"}}},
                },
                ["shot_id", "target", "joints"],
            ),
        ),
        ToolSpec(
            "set_camera",
            "Manually position the shot camera (switches the shot to manual camera mode).",
            _schema(
                {
                    "shot_id": shot_id,
                    "x": _n("Camera X"),
                    "y": _n("Camera Y (height)"),
                    "z": _n("Camera Z"),
                    "look_at": _s("Character name / asset_id / object id to aim at"),
                    "fov_deg": _n("Field of view in degrees"),
                },
                ["shot_id", "x", "y", "z"],
            ),
        ),
        ToolSpec(
            "add_keyframe",
            "Add a motion keyframe for the camera or an object at a time (seconds).",
            _schema(
                {
                    "shot_id": shot_id,
                    "target": _s("'camera', or a character name / asset_id / object id"),
                    "time": _n("Time in seconds"),
                    "x": _n("X"),
                    "y": _n("Y"),
                    "z": _n("Z"),
                    "yaw_degrees": _n("Yaw in degrees (objects) / rotation Y (camera)"),
                    "fov_deg": _n("Camera FOV at this keyframe"),
                },
                ["shot_id", "target", "time"],
            ),
        ),
        ToolSpec(
            "update_keyframe",
            "Update an existing keyframe by id.",
            _schema(
                {
                    "shot_id": shot_id,
                    "keyframe_id": _s("Keyframe id"),
                    "time": _n("Time in seconds"),
                    "x": _n("X"),
                    "y": _n("Y"),
                    "z": _n("Z"),
                    "yaw_degrees": _n("Yaw in degrees"),
                    "fov_deg": _n("FOV"),
                },
                ["shot_id", "keyframe_id"],
            ),
        ),
        ToolSpec("delete_keyframe", "Delete a keyframe by id.", _schema({"shot_id": shot_id, "keyframe_id": _s("Keyframe id")}, ["shot_id", "keyframe_id"])),
        ToolSpec(
            "capture_shot",
            "Report the shot's capture state. Rendering a new capture needs the Shot Composer viewport (GPU/WebGL), which the director cannot drive; tell the user to press Capture there.",
            _schema({"shot_id": shot_id}, ["shot_id"]),
        ),
    ]


_TOOL_SPECS = _build_tool_specs()


class FilmDirectorHandler(StateHandlerBase):
    def __init__(
        self,
        state: AppState,
        lock: RLock,
        film_handler: FilmHandler,
        film_generation_handler: FilmGenerationHandler,
        http: HTTPClient,
        video_processor: VideoProcessor | None = None,
    ) -> None:
        super().__init__(state, lock)
        self._film = film_handler
        self._film_generation = film_generation_handler
        self._http = http
        self._video_processor = video_processor
        self._openrouter_models_cache: tuple[int, list[OpenRouterModel]] | None = None
        self._commands: dict[str, Callable[[str, dict[str, object]], object]] = {
            "get_project": self._cmd_get_project,
            "list_assets": self._cmd_list_assets,
            "get_scene": self._cmd_get_scene,
            "get_shot": self._cmd_get_shot,
            "get_shot_composition": self._cmd_get_shot_composition,
            "list_framing_options": self._cmd_list_framing_options,
            "create_scene": self._cmd_create_scene,
            "update_scene": self._cmd_update_scene,
            "delete_scene": self._cmd_delete_scene,
            "create_shot": self._cmd_create_shot,
            "update_shot": self._cmd_update_shot,
            "delete_shot": self._cmd_delete_shot,
            "reorder_shots": self._cmd_reorder_shots,
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
            "set_prompt": self._cmd_set_prompt,
            "set_generation_settings": self._cmd_set_generation_settings,
            "set_script": self._cmd_set_script,
            "check_continuity": self._cmd_check_continuity,
            "generate_shot": self._cmd_generate_shot,
            "queue_shot": self._cmd_generate_shot,
            "generate_preview": self._cmd_generate_preview,
            "generate_final": self._cmd_generate_final,
            "duplicate_shot": self._cmd_duplicate_shot,
            "get_composition": self._cmd_get_shot_composition,
            "update_character": self._cmd_update_asset,
            "update_location": self._cmd_update_asset,
            "update_prop": self._cmd_update_asset,
            "assign_prop": self._cmd_assign_prop,
            "assign_location": self._cmd_set_location,
            "set_shot_type": self._cmd_set_framing,
            "set_camera_angle": self._cmd_set_framing,
            "set_camera_elevation": self._cmd_set_framing,
            "set_composition": self._cmd_set_framing,
            "set_ots": self._cmd_set_ots,
            "set_negative_prompt": self._cmd_set_negative_prompt,
            "position_object": self._cmd_position_object,
            "rotate_object": self._cmd_rotate_object,
            "scale_object": self._cmd_scale_object,
            "update_pose": self._cmd_update_pose,
            "set_camera": self._cmd_set_camera,
            "add_keyframe": self._cmd_add_keyframe,
            "update_keyframe": self._cmd_update_keyframe,
            "delete_keyframe": self._cmd_delete_keyframe,
            "capture_shot": self._cmd_capture_shot,
        }
        missing = {spec.name for spec in _TOOL_SPECS} ^ set(self._commands)
        assert not missing, f"tool specs and command registry differ: {missing}"

    # ---- Public API ------------------------------------------------------

    def command_names(self) -> list[str]:
        return sorted(self._commands)

    def run_command(self, project_id: str, req: DirectorCommandRequest) -> DirectorCommandResponse:
        result = self._execute(project_id, req.name, req.params)
        return DirectorCommandResponse(results=[result])

    _PROVIDER_LABELS: dict[str, str] = {
        "openrouter": "OpenRouter",
        "anthropic": "Claude (Anthropic)",
        "xai": "Grok (xAI)",
        "gemini": "Gemini (Google)",
        "openai_compatible": "Local / OpenAI-compatible",
    }

    @staticmethod
    def _provider_configuration(settings: AppSettings) -> dict[str, bool]:
        """Which text providers are usable right now."""
        return {
            "openrouter": bool(settings.resolved_openrouter_api_key()),
            "anthropic": bool(settings.anthropic_api_key.strip()),
            "xai": bool(settings.xai_api_key.strip()),
            "gemini": bool(settings.gemini_api_key.strip()),
            "openai_compatible": bool(
                settings.openai_compatible_base_url.strip() and settings.openai_compatible_model.strip()
            ),
        }

    def status(self) -> DirectorStatusResponse:
        with self.lock:
            settings = self.state.app_settings.model_copy(deep=True)
        configured = self._provider_configuration(settings)
        active = self._active_provider_name(settings.director_provider, configured)
        roles: list[DirectorRoleModel] = []
        for role in _ROLES:
            if active == "none":
                roles.append(DirectorRoleModel(role=role, provider="none", model=""))
            else:
                roles.append(
                    DirectorRoleModel(
                        role=role,
                        provider=active,
                        model=settings.director_model_for(active, role) or self._default_model_for(active),
                    )
                )
        providers = [
            DirectorProviderStatus(
                id=provider_id,
                label=self._PROVIDER_LABELS[provider_id],
                configured=configured[provider_id],
                model=settings.director_model_for(provider_id) or self._default_model_for(provider_id),
                needs_key=provider_id != "openai_compatible",
                note=(
                    "Runs fully offline against your own server"
                    if provider_id == "openai_compatible"
                    else ""
                ),
            )
            for provider_id in self._PROVIDER_LABELS
        ]
        message = ""
        if settings.director_provider != "auto" and not configured.get(settings.director_provider, False):
            label = self._PROVIDER_LABELS.get(settings.director_provider, settings.director_provider)
            message = (
                f"{label} is selected but not configured — add its key in Settings → API Keys, "
                "or switch the provider."
            )
        elif active == "none":
            message = _KEY_MISSING
        return DirectorStatusResponse(
            provider_setting=settings.director_provider,
            active_provider=active,
            gemini_configured=configured["gemini"],
            openrouter_configured=configured["openrouter"],
            openai_compatible_configured=configured["openai_compatible"],
            anthropic_configured=configured["anthropic"],
            xai_configured=configured["xai"],
            openrouter_key_source=settings.openrouter_key_source(),
            roles=roles,
            tools=[DirectorToolInfo(name=spec.name, description=spec.description) for spec in _TOOL_SPECS],
            providers=providers,
            message=message,
        )

    @staticmethod
    def _default_model_for(provider: str) -> str:
        return {
            "anthropic": ANTHROPIC_DEFAULT_MODEL,
            "xai": XAI_DEFAULT_MODEL,
            "gemini": GEMINI_DEFAULT_MODEL,
        }.get(provider, "")

    def chat_models(self, provider: str, *, refresh: bool = False) -> OpenRouterModelsResponse:
        """The model list a text provider offers for this key/endpoint.

        Always the provider's own catalog — the app never ships a fixed list of
        model ids that would go stale.
        """
        if provider == "openrouter":
            return self.openrouter_models(refresh=refresh)
        if provider == "openai_compatible":
            return self.openai_compatible_models()
        with self.lock:
            settings = self.state.app_settings.model_copy(deep=True)
        if provider == "anthropic":
            models = AnthropicProvider(self._http, settings.anthropic_api_key.strip()).list_models()
        elif provider == "xai":
            models = XAIProvider(self._http, settings.xai_api_key.strip()).list_models()
        elif provider == "gemini":
            models = gemini_list_models(self._http, settings.gemini_api_key.strip())
        else:
            raise HTTPError(400, f"Unknown text provider: {provider}")
        return OpenRouterModelsResponse(
            models=[OpenRouterModelInfo(**m.model_dump()) for m in models], fetched_at_ms=now_ms(), cached=False
        )

    def openrouter_models(self, *, refresh: bool = False) -> OpenRouterModelsResponse:
        now = now_ms()
        cached = self._openrouter_models_cache
        if cached is not None and not refresh and now - cached[0] < _OPENROUTER_MODELS_TTL_MS:
            return OpenRouterModelsResponse(
                models=[OpenRouterModelInfo(**m.model_dump()) for m in cached[1]], fetched_at_ms=cached[0], cached=True
            )
        with self.lock:
            key = self.state.app_settings.resolved_openrouter_api_key()
        models = openrouter_list_models(self._http, key)
        self._openrouter_models_cache = (now, models)
        return OpenRouterModelsResponse(
            models=[OpenRouterModelInfo(**m.model_dump()) for m in models], fetched_at_ms=now, cached=False
        )

    def openai_compatible_models(self) -> OpenRouterModelsResponse:
        with self.lock:
            settings = self.state.app_settings.model_copy(deep=True)
        base = settings.openai_compatible_base_url.strip()
        if not base:
            raise HTTPError(400, "OPENAI_COMPATIBLE_NOT_CONFIGURED: set the endpoint base URL first")
        provider = OpenAICompatibleProvider(self._http, settings.openai_compatible_api_key.strip(), "", base_url=base)
        models = provider.list_models()
        return OpenRouterModelsResponse(
            models=[OpenRouterModelInfo(**m.model_dump()) for m in models], fetched_at_ms=now_ms(), cached=False
        )

    def validate_openrouter_key(self) -> OpenRouterValidateResponse:
        with self.lock:
            key = self.state.app_settings.resolved_openrouter_api_key()
        if not key:
            return OpenRouterValidateResponse(valid=False, message="No OpenRouter API key configured")
        try:
            info = openrouter_validate_key(self._http, key)
        except HTTPError as exc:
            if exc.status_code == 401:
                return OpenRouterValidateResponse(valid=False, message="OpenRouter rejected this key (401). Remove it and add a valid key.")
            return OpenRouterValidateResponse(valid=False, message=str(exc.detail))
        return OpenRouterValidateResponse(
            valid=True,
            label=info.label,
            usage=info.usage,
            limit=info.limit,
            is_free_tier=info.is_free_tier,
            message="Key accepted by OpenRouter",
        )

    # ---- Provider resolution --------------------------------------------

    # "auto" tries hosted providers in this order, then the local endpoint.
    _AUTO_ORDER = ("openrouter", "anthropic", "xai", "gemini", "openai_compatible")

    @classmethod
    def _active_provider_name(cls, setting: str, configured: dict[str, bool]) -> str:
        if setting != "auto":
            return setting if configured.get(setting, False) else "none"
        for candidate in cls._AUTO_ORDER:
            if configured.get(candidate, False):
                return candidate
        return "none"

    def _provider(self, role: str) -> LLMProvider:
        with self.lock:
            settings = self.state.app_settings.model_copy(deep=True)
        configured = self._provider_configuration(settings)
        active = self._active_provider_name(settings.director_provider, configured)
        model = settings.director_model_for(active, role)
        if active == "openrouter":
            return OpenRouterProvider(self._http, settings.resolved_openrouter_api_key(), model)
        if active == "anthropic":
            return AnthropicProvider(self._http, settings.anthropic_api_key.strip(), model)
        if active == "xai":
            return XAIProvider(self._http, settings.xai_api_key.strip(), model)
        if active == "gemini":
            return GeminiProvider(self._http, settings.gemini_api_key.strip(), model or GEMINI_DEFAULT_MODEL)
        if active == "openai_compatible":
            return OpenAICompatibleProvider(
                self._http,
                settings.openai_compatible_api_key.strip(),
                model,
                base_url=settings.openai_compatible_base_url.strip(),
            )
        selected = settings.director_provider
        if selected == "openrouter":
            raise HTTPError(400, "OPENROUTER_KEY_MISSING: OpenRouter is selected but no key is configured")
        if selected == "gemini":
            raise HTTPError(400, "GEMINI_API_KEY_MISSING: Gemini is selected but no key is configured")
        if selected == "anthropic":
            raise HTTPError(400, "ANTHROPIC_KEY_MISSING: Claude is selected but no key is configured")
        if selected == "xai":
            raise HTTPError(400, "XAI_KEY_MISSING: Grok is selected but no key is configured")
        if selected == "openai_compatible":
            raise HTTPError(400, "OPENAI_COMPATIBLE_NOT_CONFIGURED: set the endpoint base URL and model in Settings → API Keys")
        raise HTTPError(400, _KEY_MISSING)

    @staticmethod
    def _context(
        provider: LLMProvider,
        role: str,
        *,
        steps: int,
        tool_calls: int,
        prompt_chars: int,
        summary_chars: int,
        replies: list[LLMReply],
        scope: str,
    ) -> DirectorContextDetails:
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        for reply in replies:
            if reply.usage is None:
                continue
            prompt_tokens = (prompt_tokens or 0) + reply.usage.prompt_tokens
            completion_tokens = (completion_tokens or 0) + reply.usage.completion_tokens
        model = replies[-1].model if replies and replies[-1].model else provider.model
        return DirectorContextDetails(
            provider=provider.name,
            model=model,
            role=role,
            steps=steps,
            tool_calls=tool_calls,
            prompt_chars=prompt_chars,
            project_summary_chars=summary_chars,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            scope=scope,
        )

    # ---- Natural-language director --------------------------------------

    def instruct(self, project_id: str, req: DirectorInstructRequest) -> DirectorInstructResponse:
        if not req.instruction.strip():
            raise HTTPError(400, "Instruction is required")
        provider = self._provider("director")
        project = self._film.get_project(project_id)
        summary_obj = self._summarize_project(project, focus_scene_id=req.scene_id)
        summary = json.dumps(summary_obj, separators=(",", ":"))
        focus = ""
        if req.scene_id:
            focus += f"\nThe user is currently looking at scene {req.scene_id}."
        if req.shot_id:
            focus += f"\nThe user is currently looking at shot {req.shot_id}."
        scope = (
            f"{len(project.scenes)} scenes, {sum(len(s.shots) for s in project.scenes)} shots, "
            f"{len(project.assets)} assets; compositions and version history omitted"
        )
        if req.scene_id:
            scope += "; only the focused scene is expanded"

        system_text = (
            "You are the AI Director of a local filmmaking app. Use the provided tools to "
            "change the film project exactly as the user asks; read state with get_* tools "
            "when unsure. Reuse existing assets by name; only create what is missing. Never "
            "call generate_shot/queue_shot unless the user explicitly asks to render now. "
            "Keep durations between 1 and 20 seconds. When done, answer with one or two "
            "plain sentences summarizing what you changed.\n"
            "If you cannot call tools, reply ONLY with JSON: "
            '{"summary": "...", "commands": [{"name": "tool_name", "params": {...}}]}'
        )
        messages: list[LLMMessage] = [LLMMessage("system", system_text)]
        for turn in req.history[-8:]:
            if turn.role in ("user", "assistant") and turn.content.strip():
                messages.append(LLMMessage("assistant" if turn.role == "assistant" else "user", turn.content))
        messages.append(
            LLMMessage("user", f"Current project state (JSON):\n{summary}\n{focus}\n\nInstruction: {req.instruction}")
        )

        results: list[DirectorCommandResult] = []
        replies: list[LLMReply] = []
        prompt_chars = 0
        final_text = ""
        steps = 0
        stop = False
        while steps < _MAX_TOOL_STEPS and not stop:
            steps += 1
            prompt_chars += messages_chars(messages)
            reply = provider.chat(messages, _TOOL_SPECS)
            replies.append(reply)
            if reply.tool_calls:
                messages.append(LLMMessage("assistant", reply.text, tool_calls=list(reply.tool_calls)))
                for call in reply.tool_calls:
                    result = self._execute(project_id, call.name, call.arguments)
                    results.append(result)
                    payload = {"ok": result.ok, "result": result.result, "error": result.error}
                    messages.append(
                        LLMMessage("tool", json.dumps(payload, default=str)[:6000], tool_call_id=call.id, name=call.name)
                    )
                    if not result.ok and call.name not in ("get_project", "get_shot", "get_scene", "list_assets"):
                        # Let the model see the failure once more so it can correct itself;
                        # it decides whether to continue.
                        continue
                continue
            final_text = reply.text.strip()
            plan = self._try_parse_plan(final_text)
            if plan is not None and plan.commands:
                for command in plan.commands:
                    result = self._execute(project_id, command.name, command.params)
                    results.append(result)
                    if not result.ok:
                        break
                final_text = plan.summary or final_text
            stop = True
        if not stop:
            results.append(
                DirectorCommandResult(name="director", ok=False, error=f"Stopped after {_MAX_TOOL_STEPS} tool steps")
            )
        context = self._context(
            provider,
            "director",
            steps=steps,
            tool_calls=sum(1 for r in results if r.name != "director"),
            prompt_chars=prompt_chars,
            summary_chars=len(summary),
            replies=replies,
            scope=scope,
        )
        return DirectorInstructResponse(plan_summary=final_text, results=results, reply=final_text, context=context)

    @staticmethod
    def _try_parse_plan(text: str) -> _DirectorPlan | None:
        if "{" not in text:
            return None
        try:
            raw = parse_json_block(text)
        except HTTPError:
            return None
        if not isinstance(raw, dict):
            return None
        try:
            return _DirectorPlan.model_validate(raw)
        except ValidationError:
            return None

    # ---- Generic chat (Quick Mode idea refinement) -----------------------

    def chat(self, req: DirectorChatRequest) -> DirectorChatResponse:
        if not req.messages or not any(m.content.strip() for m in req.messages):
            raise HTTPError(400, "At least one message is required")
        role = req.role if req.role in _ROLES else "prompt_refinement"
        provider = self._provider(role)
        setup = ""
        if req.model_hint:
            setup += f" The video model is {req.model_hint}."
        if req.duration_seconds:
            setup += f" The clip is {req.duration_seconds:g} seconds long."
        system_text = (
            "You are a creative assistant inside a local AI video app (LTX video models). Help the "
            "user turn an idea into one strong text-to-video prompt: concrete subject, setting, "
            "lighting, camera framing and motion, mood, in 40-90 words, present tense, no lists."
            + setup
            + ' Always answer ONLY with JSON: {"reply": "short conversational answer", '
            '"prompt": "the full video prompt", "negative_prompt": "comma separated things to avoid", '
            '"duration_seconds": number}'
        )
        messages: list[LLMMessage] = [LLMMessage("system", system_text)]
        for turn in req.messages[-12:]:
            if turn.role in ("user", "assistant") and turn.content.strip():
                messages.append(LLMMessage("assistant" if turn.role == "assistant" else "user", turn.content))
        reply = provider.chat(messages, None, json_mode=True)
        suggestion = _ChatSuggestion(reply=reply.text.strip())
        try:
            raw = parse_json_block(reply.text)
            if isinstance(raw, dict):
                suggestion = _ChatSuggestion.model_validate(raw)
        except (HTTPError, ValidationError):
            pass
        context = self._context(
            provider, role, steps=1, tool_calls=0, prompt_chars=messages_chars(messages), summary_chars=0,
            replies=[reply], scope="no project context; conversation only",
        )
        return DirectorChatResponse(
            reply=suggestion.reply or reply.text.strip(),
            suggested_prompt=suggestion.prompt,
            suggested_negative_prompt=suggestion.negative_prompt,
            suggested_duration_seconds=suggestion.duration_seconds,
            context=context,
        )

    # ---- Prompt refinement -----------------------------------------------

    # ---- Visual continuity review (optional, multimodal) --------------------

    _VISUAL_CATEGORIES: dict[str, str] = {
        "good": "good",
        "minor_drift": "minor_drift",
        "minor drift": "minor_drift",
        "review_recommended": "review_recommended",
        "review recommended": "review_recommended",
        "likely_break": "likely_break",
        "likely continuity break": "likely_break",
        "likely_continuity_break": "likely_break",
        "break": "likely_break",
    }

    def _frame_data_url(self, output_path: str, *, last: bool) -> tuple[str, bytes] | None:
        """(data URL, jpeg bytes) for the first or last frame of a rendered clip."""
        processor = self._video_processor
        if processor is None:
            return None
        try:
            cap = processor.open_video(output_path)
            try:
                info = processor.get_video_info(cap)
                index = max(0, info["frame_count"] - 1) if last else 0
                frame = processor.read_frame(cap, index)
                if frame is None:
                    return None
                jpeg = processor.encode_frame_jpeg(frame, quality=88)
            finally:
                processor.release(cap)
        except Exception as exc:  # noqa: BLE001 - review is best-effort
            logger.warning("Could not extract frame for visual review: %s", exc)
            return None
        encoded = base64.b64encode(jpeg).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}", jpeg

    def visual_review(self, project_id: str, shot_id: str) -> VisualReviewResponse:
        """Compare the previous shot's last frame with this shot's first frame
        through a multimodal model. Never a hard failure: anything that stops
        the review comes back as ``available=False`` with a reason, and the
        deterministic continuity checks stay authoritative."""
        project = self._film.get_project(project_id)
        found = project.find_shot(shot_id)
        if found is None:
            raise HTTPError(404, f"Shot not found: {shot_id}")
        scene, shot = found
        previous = project.previous_shot(shot.id)
        if previous is None or not previous_in_same_scene(project, previous, shot):
            return VisualReviewResponse(available=False, reason="This is the first shot of its scene — nothing to compare against.")
        prev_version = previous.version(previous.current_version) if previous.current_version is not None else None
        cur_version = shot.version(shot.current_version) if shot.current_version is not None else None
        if prev_version is None or prev_version.status != "complete" or not prev_version.output_path:
            return VisualReviewResponse(available=False, reason="The previous shot has no rendered version yet.", previous_shot_id=previous.id)
        if cur_version is None or cur_version.status != "complete" or not cur_version.output_path:
            return VisualReviewResponse(available=False, reason="This shot has no rendered version yet.", previous_shot_id=previous.id)
        try:
            provider = self._provider("continuity")
        except HTTPError as exc:
            return VisualReviewResponse(available=False, reason=str(exc.detail), previous_shot_id=previous.id)

        prev_frame = self._frame_data_url(prev_version.output_path, last=True)
        cur_frame = self._frame_data_url(cur_version.output_path, last=False)
        if prev_frame is None or cur_frame is None:
            return VisualReviewResponse(
                available=False,
                reason="Could not read frames from the rendered clips (missing file or unreadable video).",
                previous_shot_id=previous.id,
            )
        captures = self._film.store.captures_dir(project_id)
        captures.mkdir(parents=True, exist_ok=True)
        prev_rel = f"captures/{shot.id}-review-prev.jpg"
        cur_rel = f"captures/{shot.id}-review-cur.jpg"
        (captures / f"{shot.id}-review-prev.jpg").write_bytes(prev_frame[1])
        (captures / f"{shot.id}-review-cur.jpg").write_bytes(cur_frame[1])

        cast_names = [a.name for c in shot.characters for a in project.assets if a.id == c.asset_id]
        prev_cast = [a.name for c in previous.characters for a in project.assets if a.id == c.asset_id]
        location_asset = project.asset(shot.location_id) if shot.location_id else None
        location = location_asset.name if location_asset is not None else "unspecified"
        system = (
            "You are a film continuity supervisor. You receive the LAST frame of the previous shot and the FIRST frame "
            "of the next shot from the same scene. Judge visual continuity only: character appearance and wardrobe, "
            "props, location/set dressing, lighting and time of day, screen direction. Ignore differences that are "
            "expected from the framing change. Answer with JSON only: "
            '{"category": "good" | "minor_drift" | "review_recommended" | "likely_break", '
            '"summary": "<one sentence>", "issues": ["<specific observation>", ...]}. '
            "Be conservative: use likely_break only for clear contradictions (different clothing colour, missing "
            "character, different location)."
        )
        user = (
            f"Scene: {scene.title or 'untitled'} · location: {location}.\n"
            f"Previous shot: {previous.title or previous.id} — {framing_summary(previous)}; cast: {', '.join(prev_cast) or 'none'}.\n"
            f"This shot: {shot.title or shot.id} — {framing_summary(shot)}; cast: {', '.join(cast_names) or 'none'}.\n"
            "Image 1 is the previous shot's last frame; image 2 is this shot's first frame."
        )
        messages = [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user, images=[prev_frame[0], cur_frame[0]]),
        ]
        try:
            reply = provider.chat(messages, json_mode=True)
        except HTTPError as exc:
            return VisualReviewResponse(
                available=False,
                reason=f"The provider could not review the frames: {exc.detail}",
                previous_shot_id=previous.id,
                previous_frame_path=prev_rel,
                current_frame_path=cur_rel,
            )
        try:
            parsed = parse_json_block(reply.text)
        except HTTPError:
            parsed = None
        payload = cast(dict[str, object], parsed) if isinstance(parsed, dict) else {}
        raw_category = str(payload.get("category", "")).strip().lower()
        category = self._VISUAL_CATEGORIES.get(raw_category)
        issues_raw = payload.get("issues", [])
        issues = [str(i) for i in cast(list[object], issues_raw)][:8] if isinstance(issues_raw, list) else []
        summary = str(payload.get("summary", "")).strip() or reply.text.strip()[:300]
        context = self._context(
            provider,
            "continuity",
            steps=1,
            tool_calls=0,
            prompt_chars=messages_chars(messages),
            summary_chars=len(user),
            replies=[reply],
            scope="two frames (previous last / current first) + shot facts",
        )
        if category is None:
            return VisualReviewResponse(
                available=False,
                reason=f"The model did not return a recognised category ({raw_category or 'no JSON'}).",
                summary=summary,
                previous_shot_id=previous.id,
                previous_frame_path=prev_rel,
                current_frame_path=cur_rel,
                context=context,
            )
        return VisualReviewResponse(
            available=True,
            category=category,  # type: ignore[arg-type]
            summary=summary,
            issues=issues,
            previous_shot_id=previous.id,
            previous_frame_path=prev_rel,
            current_frame_path=cur_rel,
            context=context,
        )

    def refine_prompt(self, project_id: str, scene_id: str, shot_id: str, req: RefinePromptRequest) -> RefinePromptResponse:
        provider = self._provider("prompt_refinement")
        project = self._film.get_project(project_id)
        scene = project.scene(scene_id)
        if scene is None:
            raise HTTPError(404, f"Scene not found: {scene_id}")
        found = project.find_shot(shot_id)
        if found is None or found[0].id != scene_id:
            raise HTTPError(404, f"Shot not found: {shot_id}")
        shot = found[1]
        base_prompt = shot.visual_prompt or synthesize_prompt(project, scene, shot)
        cast_lines = [
            f"- {a.name}: {a.appearance or a.description}; wardrobe: {a.wardrobe}"
            for a in project.assets
            if a.kind == "character" and any(c.asset_id == a.id for c in shot.characters)
        ]
        system_text = (
            "You refine prompts for an LTX text/image-to-video model. Keep every concrete fact "
            "(characters, wardrobe, location, framing, camera move) and make the prompt vivid and "
            "specific: 50-110 words, one paragraph, present tense, no lists, no camera jargon the "
            "model cannot follow. Answer ONLY with JSON: {\"prompt\": \"...\", \"negative_prompt\": \"...\"}"
        )
        user_text = (
            f"Framing: {framing_summary(shot)}\nCamera move: {shot.camera_move}\nDuration: {shot.duration_seconds:g}s\n"
            f"Scene: {scene.title} — {scene.description} ({scene.time_of_day}, {scene.mood})\n"
            f"Cast:\n{chr(10).join(cast_lines) or '- none'}\nAction: {shot.action}\nDialogue: {shot.dialogue}\n"
            f"Current prompt: {base_prompt}\n"
            + (f"User guidance: {req.guidance}\n" if req.guidance.strip() else "")
        )
        messages = [LLMMessage("system", system_text), LLMMessage("user", user_text)]
        reply = provider.chat(messages, None, json_mode=True)
        raw = parse_json_block(reply.text)
        if not isinstance(raw, dict):
            raise HTTPError(502, "Prompt refinement returned an unexpected payload")
        data = cast(dict[str, object], raw)
        new_prompt = str(data.get("prompt", "") or "").strip()
        if not new_prompt:
            raise HTTPError(502, "Prompt refinement returned an empty prompt")
        negative = str(data.get("negative_prompt", "") or "").strip()
        update = UpdateShotRequest(visual_prompt=new_prompt, prompt_locked=True)
        if negative:
            update = UpdateShotRequest(visual_prompt=new_prompt, negative_prompt=negative, prompt_locked=True)
        updated = self._film.update_shot(project_id, scene_id, shot_id, update)
        context = self._context(
            provider, "prompt_refinement", steps=1, tool_calls=0, prompt_chars=messages_chars(messages),
            summary_chars=0, replies=[reply], scope="one shot: framing, cast, scene, current prompt",
        )
        return RefinePromptResponse(shot=updated, previous_prompt=base_prompt, context=context)

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

    def _summarize_project(self, project: FilmProject, *, focus_scene_id: str | None = None) -> dict[str, object]:
        scenes: list[dict[str, object]] = []
        for scene in sorted(project.scenes, key=lambda s: s.order):
            expanded = focus_scene_id is None or scene.id == focus_scene_id
            entry: dict[str, object] = {
                "id": scene.id,
                "order": scene.order,
                "title": scene.title,
                "location_id": scene.location_id,
                "character_ids": scene.character_ids,
            }
            if expanded:
                entry["shots"] = [
                    {
                        "id": shot.id,
                        "order": shot.order,
                        "title": shot.title,
                        "duration_seconds": shot.duration_seconds,
                        "framing": framing_summary(shot),
                        "camera_move": shot.camera_move,
                        "characters": [c.asset_id for c in shot.characters],
                        "status": shot.status,
                    }
                    for shot in sorted(scene.shots, key=lambda s: s.order)
                ]
            else:
                entry["shot_count"] = len(scene.shots)
                entry["shot_ids"] = [shot.id for shot in sorted(scene.shots, key=lambda s: s.order)]
            scenes.append(entry)
        return {
            "id": project.id,
            "name": project.name,
            "assets": [
                {"id": a.id, "kind": a.kind, "name": a.name, "description": a.description[:120]}
                for a in project.assets
            ],
            "scenes": scenes,
            "pose_names": sorted({p.name for p in project.pose_library}),
        }

    def _cmd_get_project(self, project_id: str, params: dict[str, object]) -> object:
        del params
        return self._summarize_project(self._film.get_project(project_id))

    def _cmd_list_assets(self, project_id: str, params: dict[str, object]) -> object:
        del params
        project = self._film.get_project(project_id)
        return [a.model_dump(exclude={"reference_images"}) for a in project.assets]

    def _cmd_get_scene(self, project_id: str, params: dict[str, object]) -> object:
        scene_id = _param_str(params, "scene_id")
        project = self._film.get_project(project_id)
        scene = project.scene(scene_id)
        if scene is None:
            raise HTTPError(404, f"Scene not found: {scene_id}")
        data = scene.model_dump()
        shots = data.get("shots")
        if isinstance(shots, list):
            for shot in cast(list[object], shots):
                if isinstance(shot, dict):
                    cast(dict[str, object], shot).pop("composition", None)
        return data

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

    def _cmd_delete_scene(self, project_id: str, params: dict[str, object]) -> object:
        scene_id = _param_str(params, "scene_id")
        self._film.delete_scene(project_id, scene_id)
        return {"deleted": scene_id}

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

    def _cmd_delete_shot(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        self._film.delete_shot(project_id, scene_id, shot_id)
        return {"deleted": shot_id}

    def _cmd_reorder_shots(self, project_id: str, params: dict[str, object]) -> object:
        scene_id = _param_str(params, "scene_id")
        ordered = _param_str_list(params, "ordered_shot_ids")
        scene = self._film.reorder_shots(project_id, scene_id, ReorderRequest(ordered_ids=ordered))
        return {"scene_id": scene.id, "order": [s.id for s in sorted(scene.shots, key=lambda s: s.order)]}

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
                ots_shoulder=current.ots_shoulder,
                # A preset change re-solves the camera from the presets.
                camera_mode="preset",
            )
        except ValidationError as exc:
            raise HTTPError(400, f"Invalid framing: {exc}") from exc
        shot = self._film.update_shot(project_id, scene_id, shot_id, UpdateShotRequest(framing=framing))
        return {"id": shot.id, "framing": framing_summary(shot)}

    def _cmd_set_camera_motion(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        move = _param_str(params, "camera_move")
        if move not in CAMERA_MOVE_LABELS:
            raise HTTPError(400, f"Invalid camera_move: {move}. Valid: {', '.join(CAMERA_MOVE_LABELS)}")
        shot = self._film.update_shot(
            project_id, scene_id, shot_id, UpdateShotRequest.model_validate({"camera_move": move})
        )
        return {"id": shot.id, "camera_move": shot.camera_move}

    def _cmd_set_duration(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        duration = _param_float(params, "duration_seconds", 0.0)
        if duration <= 0:
            raise HTTPError(400, "duration_seconds must be positive")
        shot = self._film.update_shot(project_id, scene_id, shot_id, UpdateShotRequest(duration_seconds=duration))
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
        updated = self._film.update_shot(project_id, scene_id, shot_id, UpdateShotRequest(characters=characters))
        scene = project.scene(scene_id)
        if scene is not None and asset_id not in scene.character_ids:
            self._film.update_scene(
                project_id, scene_id, UpdateSceneRequest(character_ids=[*scene.character_ids, asset_id])
            )
        return {"id": updated.id, "characters": [c.asset_id for c in updated.characters]}

    def _cmd_set_location(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        project = self._film.get_project(project_id)
        asset_id = self._resolve_asset_id(project, params, "location")
        updated = self._film.update_shot(project_id, scene_id, shot_id, UpdateShotRequest(location_id=asset_id))
        scene = project.scene(scene_id)
        if scene is not None and scene.location_id is None:
            self._film.update_scene(project_id, scene_id, UpdateSceneRequest(location_id=asset_id))
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
        updated = self._film.update_shot(project_id, scene_id, shot_id, UpdateShotRequest(characters=characters))
        return {"id": updated.id, "pose_applied": pose_name}

    def _cmd_set_prompt(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        prompt = _param_str(params, "visual_prompt")
        negative = _param_str(params, "negative_prompt", required=False)
        locked = _param_bool(params, "locked", True)
        req = UpdateShotRequest(visual_prompt=prompt, prompt_locked=locked)
        if negative:
            req = UpdateShotRequest(visual_prompt=prompt, negative_prompt=negative, prompt_locked=locked)
        shot = self._film.update_shot(project_id, scene_id, shot_id, req)
        return {"id": shot.id, "visual_prompt": shot.visual_prompt, "prompt_locked": shot.prompt_locked}

    def _cmd_set_generation_settings(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        project = self._film.get_project(project_id)
        found = project.find_shot(shot_id)
        assert found is not None
        current = found[1].generation
        seed_raw = params.get("seed", None)
        seed: int | None = current.seed
        if seed_raw is not None:
            if isinstance(seed_raw, bool) or not isinstance(seed_raw, (int, float)):
                raise HTTPError(400, "Parameter seed must be a number")
            seed = int(seed_raw)
        try:
            generation = ShotGenerationSettings(
                model=_param_str(params, "model", required=False, default=current.model),
                resolution=_param_str(params, "resolution", required=False, default=current.resolution),
                fps=current.fps,
                seed=seed,
                aspect_ratio=current.aspect_ratio,
                use_capture_as_reference=current.use_capture_as_reference,
                continue_from_previous=_param_bool(params, "continue_from_previous", current.continue_from_previous),
                quality_preset=_param_str(params, "quality_preset", required=False, default=current.quality_preset),  # type: ignore[arg-type]
            )
        except ValidationError as exc:
            raise HTTPError(400, f"Invalid generation settings: {exc}") from exc
        shot = self._film.update_shot(project_id, scene_id, shot_id, UpdateShotRequest(generation=generation))
        return {"id": shot.id, "generation": shot.generation.model_dump()}

    def _cmd_set_script(self, project_id: str, params: dict[str, object]) -> object:
        content = _param_str(params, "content")
        project = self._film.update_script(project_id, UpdateScriptRequest(content=content))
        return {"script_chars": len(project.script.content)}

    def _cmd_check_continuity(self, project_id: str, params: dict[str, object]) -> object:
        shot_id = _param_str(params, "shot_id")
        return [w.model_dump() for w in self._film.continuity(project_id, shot_id)]

    def _cmd_generate_shot(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        kind = _param_str(params, "kind", required=False, default="preview")
        if kind not in ("preview", "final"):
            raise HTTPError(400, "kind must be 'preview' or 'final'")
        response = self._film_generation.queue_shot(
            project_id, scene_id, shot_id, GenerateShotRequest(kind=kind)  # type: ignore[arg-type]
        )
        return {"status": response.status, "version_number": response.version_number}

    # ---- Composition tools (the director drives the same CompositionScene the composer edits) ----

    def _cmd_generate_preview(self, project_id: str, params: dict[str, object]) -> object:
        return self._cmd_generate_shot(project_id, {**params, "kind": "preview"})

    def _cmd_generate_final(self, project_id: str, params: dict[str, object]) -> object:
        return self._cmd_generate_shot(project_id, {**params, "kind": "final"})

    def _cmd_duplicate_shot(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        copy = self._film.duplicate_shot(project_id, scene_id, shot_id)
        return {"id": copy.id, "title": copy.title, "order": copy.order}

    def _cmd_assign_prop(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        project = self._film.get_project(project_id)
        asset_id = self._resolve_asset_id(project, params, "prop")
        found = project.find_shot(shot_id)
        assert found is not None
        prop_ids = [p for p in found[1].prop_ids if p != asset_id] + [asset_id]
        updated = self._film.update_shot(project_id, scene_id, shot_id, UpdateShotRequest(prop_ids=prop_ids))
        scene = project.scene(scene_id)
        if scene is not None and asset_id not in scene.prop_ids:
            self._film.update_scene(project_id, scene_id, UpdateSceneRequest(prop_ids=[*scene.prop_ids, asset_id]))
        return {"id": updated.id, "prop_ids": updated.prop_ids}

    def _cmd_set_negative_prompt(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        negative = _param_str(params, "negative_prompt")
        shot = self._film.update_shot(project_id, scene_id, shot_id, UpdateShotRequest(negative_prompt=negative))
        return {"id": shot.id, "negative_prompt": shot.negative_prompt}

    def _ensure_composition(self, project: FilmProject, shot: FilmShot) -> CompositionScene:
        """The composer's scene, created from the cast when the shot has never
        been opened in the composer (same seeding the UI does)."""
        if shot.composition is not None:
            return shot.composition.model_copy(deep=True)
        objects: list[CompositionObject] = []
        count = len(shot.characters)
        for index, shot_character in enumerate(shot.characters):
            asset = project.asset(shot_character.asset_id)
            objects.append(
                CompositionObject(
                    name=asset.name if asset else f"Character {index + 1}",
                    type="figure",
                    asset_id=shot_character.asset_id,
                    transform=CompositionTransform(position=(index * 1.2 - (count - 1) * 0.6, 0.0, 0.0)),
                )
            )
        camera = CompositionObject(
            id="shot-camera",
            name="Shot Camera",
            type="camera",
            transform=CompositionTransform(position=(0.0, 1.6, 4.0)),
            fov=shot.framing.fov_deg,
        )
        return CompositionScene(
            objects=objects,
            camera=camera,
            framing=shot.framing.model_copy(deep=True),
            camera_move=shot.camera_move,
            duration_seconds=shot.duration_seconds,
        )

    def _resolve_object(self, project: FilmProject, composition: CompositionScene, target: str) -> CompositionObject:
        needle = target.strip().lower()
        for obj in composition.objects:
            if obj.id == target or (obj.asset_id and obj.asset_id == target):
                return obj
        for obj in composition.objects:
            if obj.name.strip().lower() == needle:
                return obj
        for obj in composition.objects:
            asset = project.asset(obj.asset_id) if obj.asset_id else None
            if asset is not None and asset.name.strip().lower() == needle:
                return obj
        raise HTTPError(404, f"No composer object matches {target!r}. Assign the character to the shot first.")

    def _save_composition(self, project_id: str, scene_id: str, shot_id: str, composition: CompositionScene) -> FilmShot:
        return self._film.update_shot(project_id, scene_id, shot_id, UpdateShotRequest(composition=composition))

    _PLACEMENT_HINTS: dict[str, tuple[float, float]] = {
        "foreground left": (-0.9, 1.2),
        "foreground right": (0.9, 1.2),
        "background left": (-1.1, -1.6),
        "background right": (1.1, -1.6),
        "center": (0.0, 0.0),
        "left": (-1.2, 0.0),
        "right": (1.2, 0.0),
    }

    def _cmd_position_object(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        project = self._film.get_project(project_id)
        found = project.find_shot(shot_id)
        assert found is not None
        composition = self._ensure_composition(project, found[1])
        obj = self._resolve_object(project, composition, _param_str(params, "target"))
        if obj.locked:
            raise HTTPError(409, f"{obj.name} is locked in the composer")
        x, y, z = obj.transform.position
        hint = _param_str(params, "hint", required=False).strip().lower()
        if hint:
            if hint not in self._PLACEMENT_HINTS:
                raise HTTPError(400, f"Unknown placement hint {hint!r}")
            x, z = self._PLACEMENT_HINTS[hint]
        x = _param_float(params, "x", x)
        y = _param_float(params, "y", y)
        z = _param_float(params, "z", z)
        obj.transform = CompositionTransform(position=(x, y, z), rotation=obj.transform.rotation, scale=obj.transform.scale)
        self._save_composition(project_id, scene_id, shot_id, composition)
        return {"object_id": obj.id, "name": obj.name, "position": [x, y, z]}

    def _cmd_rotate_object(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        project = self._film.get_project(project_id)
        found = project.find_shot(shot_id)
        assert found is not None
        composition = self._ensure_composition(project, found[1])
        obj = self._resolve_object(project, composition, _param_str(params, "target"))
        if obj.locked:
            raise HTTPError(409, f"{obj.name} is locked in the composer")
        yaw = math.radians(_param_float(params, "yaw_degrees", 0.0))
        rx, _, rz = obj.transform.rotation
        obj.transform = CompositionTransform(position=obj.transform.position, rotation=(rx, yaw, rz), scale=obj.transform.scale)
        self._save_composition(project_id, scene_id, shot_id, composition)
        return {"object_id": obj.id, "name": obj.name, "yaw_degrees": math.degrees(yaw)}

    def _cmd_scale_object(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        project = self._film.get_project(project_id)
        found = project.find_shot(shot_id)
        assert found is not None
        composition = self._ensure_composition(project, found[1])
        obj = self._resolve_object(project, composition, _param_str(params, "target"))
        if obj.locked:
            raise HTTPError(409, f"{obj.name} is locked in the composer")
        scale = _param_float(params, "scale", 1.0)
        if not 0.05 <= scale <= 20:
            raise HTTPError(400, "scale must be between 0.05 and 20")
        obj.transform = CompositionTransform(position=obj.transform.position, rotation=obj.transform.rotation, scale=(scale, scale, scale))
        self._save_composition(project_id, scene_id, shot_id, composition)
        return {"object_id": obj.id, "name": obj.name, "scale": scale}

    def _cmd_update_pose(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        project = self._film.get_project(project_id)
        found = project.find_shot(shot_id)
        assert found is not None
        composition = self._ensure_composition(project, found[1])
        obj = self._resolve_object(project, composition, _param_str(params, "target"))
        if obj.type != "figure":
            raise HTTPError(400, f"{obj.name} is not a character figure")
        raw_joints = params.get("joints")
        if not isinstance(raw_joints, dict):
            raise HTTPError(400, "joints must be an object of joint -> [x, y, z] degrees")
        joints: dict[str, tuple[float, float, float]] = dict(obj.pose)
        for name, value in cast(dict[object, object], raw_joints).items():
            if not isinstance(value, list) or len(cast(list[object], value)) != 3:
                raise HTTPError(400, f"joint {name!r} must be [x, y, z]")
            values = cast(list[object], value)
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in values):
                raise HTTPError(400, f"joint {name!r} must contain numbers")
            joints[str(name)] = (float(cast(float, values[0])), float(cast(float, values[1])), float(cast(float, values[2])))
        obj.pose = joints
        self._save_composition(project_id, scene_id, shot_id, composition)
        return {"object_id": obj.id, "name": obj.name, "joints": sorted(joints)}

    def _cmd_set_ots(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        project = self._film.get_project(project_id)
        found = project.find_shot(shot_id)
        assert found is not None
        shot = found[1]
        # Make sure both characters are in the shot (and therefore in the composer).
        for key in ("foreground", "subject"):
            target = _param_str(params, key)
            asset_id = self._resolve_asset_id(project, {"name": target, "asset_id": target if project.asset(target) else ""}, "character")
            if all(c.asset_id != asset_id for c in shot.characters):
                shot = self._film.update_shot(
                    project_id, scene_id, shot_id, UpdateShotRequest(characters=[*shot.characters, ShotCharacter(asset_id=asset_id)])
                )
        project = self._film.get_project(project_id)
        found = project.find_shot(shot_id)
        assert found is not None
        composition = self._ensure_composition(project, found[1])
        foreground = self._resolve_object(project, composition, _param_str(params, "foreground"))
        subject = self._resolve_object(project, composition, _param_str(params, "subject"))
        shoulder = _param_str(params, "shoulder", required=False, default="left")
        if shoulder not in ("left", "right"):
            raise HTTPError(400, "shoulder must be 'left' or 'right'")
        composition.framing = composition.framing.model_copy(
            update={
                "camera_angle": "ots",
                "ots_foreground_id": foreground.id,
                "ots_subject_id": subject.id,
                "ots_shoulder": shoulder,
                "camera_mode": "preset",
            }
        )
        updated = self._save_composition(project_id, scene_id, shot_id, composition)
        return {
            "id": updated.id,
            "framing": framing_summary(updated),
            "foreground": foreground.name,
            "subject": subject.name,
            "shoulder": shoulder,
        }

    def _cmd_set_camera(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        project = self._film.get_project(project_id)
        found = project.find_shot(shot_id)
        assert found is not None
        composition = self._ensure_composition(project, found[1])
        camera = composition.camera or CompositionObject(id="shot-camera", name="Shot Camera", type="camera")
        x = _param_float(params, "x", camera.transform.position[0])
        y = _param_float(params, "y", camera.transform.position[1])
        z = _param_float(params, "z", camera.transform.position[2])
        rotation = camera.transform.rotation
        look_at = _param_str(params, "look_at", required=False)
        if look_at:
            target = self._resolve_object(project, composition, look_at)
            tx, ty, tz = target.transform.position
            ty += 1.4 * target.transform.scale[1]  # aim at chest height
            dx, dy, dz = tx - x, ty - y, tz - z
            yaw = math.atan2(dx, dz)
            pitch = math.atan2(dy, math.hypot(dx, dz))
            rotation = (pitch, yaw + math.pi, 0.0)
        fov = _param_float(params, "fov_deg", camera.fov or composition.framing.fov_deg)
        camera.transform = CompositionTransform(position=(x, y, z), rotation=rotation, scale=(1.0, 1.0, 1.0))
        camera.fov = fov
        composition.camera = camera
        composition.framing = composition.framing.model_copy(update={"camera_mode": "manual", "fov_deg": fov})
        updated = self._save_composition(project_id, scene_id, shot_id, composition)
        return {"id": updated.id, "camera_position": [x, y, z], "fov_deg": fov, "camera_mode": "manual"}

    def _keyframe_from_params(self, params: dict[str, object], base: CompositionKeyframe | None, default_time: float) -> CompositionKeyframe:
        current = base or CompositionKeyframe(time=default_time)
        px, py, pz = current.transform.position
        rx, ry, rz = current.transform.rotation
        x = _param_float(params, "x", px)
        y = _param_float(params, "y", py)
        z = _param_float(params, "z", pz)
        yaw_raw = params.get("yaw_degrees")
        yaw = math.radians(_param_float(params, "yaw_degrees", math.degrees(ry))) if yaw_raw is not None else ry
        time_value = _param_float(params, "time", current.time)
        if time_value < 0:
            raise HTTPError(400, "time must be >= 0")
        fov_raw = params.get("fov_deg")
        fov = _param_float(params, "fov_deg", current.fov or 0.0) if fov_raw is not None else current.fov
        return CompositionKeyframe(
            id=current.id,
            time=time_value,
            transform=CompositionTransform(position=(x, y, z), rotation=(rx, yaw, rz), scale=current.transform.scale),
            fov=fov,
        )

    def _cmd_add_keyframe(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        project = self._film.get_project(project_id)
        found = project.find_shot(shot_id)
        assert found is not None
        composition = self._ensure_composition(project, found[1])
        target = _param_str(params, "target")
        if target.strip().lower() == "camera":
            if composition.camera is None:
                composition.camera = CompositionObject(id="shot-camera", name="Shot Camera", type="camera")
            obj = composition.camera
        else:
            obj = self._resolve_object(project, composition, target)
        seed = CompositionKeyframe(time=0.0, transform=obj.transform.model_copy(), fov=obj.fov)
        keyframe = self._keyframe_from_params(params, seed, 0.0)
        keyframe.id = CompositionKeyframe().id
        obj.keyframes = sorted([*obj.keyframes, keyframe], key=lambda k: k.time)
        self._save_composition(project_id, scene_id, shot_id, composition)
        return {"keyframe_id": keyframe.id, "target": obj.name, "time": keyframe.time, "count": len(obj.keyframes)}

    def _find_keyframe(self, composition: CompositionScene, keyframe_id: str) -> tuple[CompositionObject, CompositionKeyframe]:
        candidates = [*composition.objects] + ([composition.camera] if composition.camera else [])
        for obj in candidates:
            for keyframe in obj.keyframes:
                if keyframe.id == keyframe_id:
                    return obj, keyframe
        raise HTTPError(404, f"Keyframe not found: {keyframe_id}")

    def _cmd_update_keyframe(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        project = self._film.get_project(project_id)
        found = project.find_shot(shot_id)
        assert found is not None
        composition = self._ensure_composition(project, found[1])
        obj, keyframe = self._find_keyframe(composition, _param_str(params, "keyframe_id"))
        updated = self._keyframe_from_params(params, keyframe, keyframe.time)
        obj.keyframes = sorted([updated if k.id == keyframe.id else k for k in obj.keyframes], key=lambda k: k.time)
        self._save_composition(project_id, scene_id, shot_id, composition)
        return {"keyframe_id": updated.id, "target": obj.name, "time": updated.time}

    def _cmd_delete_keyframe(self, project_id: str, params: dict[str, object]) -> object:
        scene_id, shot_id = self._find_shot(project_id, params)
        project = self._film.get_project(project_id)
        found = project.find_shot(shot_id)
        assert found is not None
        composition = self._ensure_composition(project, found[1])
        obj, keyframe = self._find_keyframe(composition, _param_str(params, "keyframe_id"))
        obj.keyframes = [k for k in obj.keyframes if k.id != keyframe.id]
        self._save_composition(project_id, scene_id, shot_id, composition)
        return {"deleted": keyframe.id, "target": obj.name, "count": len(obj.keyframes)}

    def _cmd_capture_shot(self, project_id: str, params: dict[str, object]) -> object:
        _, shot_id = self._find_shot(project_id, params)
        project = self._film.get_project(project_id)
        found = project.find_shot(shot_id)
        assert found is not None
        shot = found[1]
        return {
            "id": shot.id,
            "has_capture": bool(shot.capture_path),
            "capture_path": shot.capture_path,
            "composed": shot.composition is not None,
            "note": (
                "A capture already exists; press Capture in the Shot Composer to refresh it after changes."
                if shot.capture_path
                else "No capture yet. Open the shot in the Shot Composer and press Capture — the director cannot render the viewport."
            ),
        }

    # ---- Storyboard generation ------------------------------------------

    def generate_storyboard(self, project_id: str, req: GenerateStoryboardRequest) -> GenerateStoryboardResponse:
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
            plan = self._storyboard_plan_with_llm(script, req.target_shots_per_scene)
            used_llm = True
        else:
            plan = self._storyboard_plan_heuristic(script)

        build = FilmBuildPlan(
            characters=[],
            scenes=[
                FilmBuildScene(
                    title=scene.title,
                    description=scene.description,
                    time_of_day=scene.time_of_day,
                    mood=scene.mood,
                    shots=[
                        FilmBuildShot(
                            description=shot.description,
                            action=shot.action,
                            dialogue=shot.dialogue,
                            shot_size=shot.shot_size,
                            camera_angle=shot.camera_angle,
                            camera_elevation=shot.camera_elevation,
                            composition=shot.composition,
                            camera_move=shot.camera_move,
                            duration_seconds=shot.duration_seconds,
                            characters=shot.characters,
                        )
                        for shot in scene.shots
                    ],
                )
                for scene in plan.scenes
            ],
        )
        for name in plan.characters:
            build.characters.append(_build_character(name))
        applied = self._apply_plan(project_id, build, replace_existing=req.replace_existing, set_script=False)
        return GenerateStoryboardResponse(
            status="draft_created",
            scenes_created=applied.scenes_created,
            shots_created=applied.shots_created,
            characters_created=applied.characters_created,
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

    def _storyboard_plan_with_llm(self, script: str, target_shots: int) -> _StoryboardPlan:
        provider = self._provider("storyboard")
        system_text = (
            "You are a professional storyboard artist. Break the screenplay into scenes and "
            f"shots (about {target_shots} shots per scene). Every field must be filled.\n"
            f"shot_size: {'|'.join(_SHOT_SIZES)}\n"
            f"camera_angle: {'|'.join(_ANGLES)}\n"
            f"camera_elevation: {'|'.join(_ELEVATIONS)}\n"
            f"composition: {'|'.join(_COMPOSITIONS)}\n"
            f"camera_move: {'|'.join(_MOVES)}\n"
            "description: detailed visual description (30+ words) usable as an image prompt.\n"
            'Return ONLY JSON: {"characters": ["NAME"], "scenes": [{"title": "...", '
            '"description": "...", "time_of_day": "...", "mood": "...", "shots": '
            '[{"description": "...", "action": "...", "dialogue": "", "shot_size": "medium", '
            '"camera_angle": "front", "camera_elevation": "eye", "composition": "center", '
            '"camera_move": "static", "duration_seconds": 4, "characters": ["NAME"]}]}]}'
        )
        reply = provider.chat(
            [LLMMessage("system", system_text), LLMMessage("user", f"Screenplay:\n\n{script}")], None, json_mode=True
        )
        try:
            return _StoryboardPlan.model_validate(parse_json_block(reply.text))
        except ValidationError as exc:
            raise HTTPError(502, f"LLM storyboard did not match the expected schema: {exc}") from exc

    # ---- Build Film with AI ---------------------------------------------

    def build_film(self, project_id: str, req: FilmBuildRequest) -> FilmBuildResponse:
        idea = req.idea.strip()
        if not idea:
            raise HTTPError(400, "Describe the film idea first")
        self._film.get_project(project_id)  # 404 if unknown
        target_scenes = max(1, min(12, req.target_scenes))
        target_shots = max(1, min(8, req.target_shots_per_scene))
        if not req.use_llm:
            return FilmBuildResponse(plan=_heuristic_build_plan(idea, target_scenes, target_shots, req.style), used_llm=False)
        provider = self._provider("script")
        system_text = (
            "You are a screenwriter and storyboard artist for short AI-generated films. From the "
            f"idea, design a film with {target_scenes} scenes and about {target_shots} shots per scene. "
            "Shots are 2-10 seconds. Give characters concrete appearance and wardrobe so they stay "
            "consistent across shots; give locations environment and lighting. Every shot "
            "description must be a vivid, self-contained visual description (30-60 words) that names "
            "the characters and location.\n"
            f"shot_size: {'|'.join(_SHOT_SIZES)}; camera_angle: {'|'.join(_ANGLES)}; "
            f"camera_elevation: {'|'.join(_ELEVATIONS)}; composition: {'|'.join(_COMPOSITIONS)}; "
            f"camera_move: {'|'.join(_MOVES)}.\n"
            'Return ONLY JSON: {"title": "...", "logline": "...", "style": "...", "script": "screenplay text", '
            '"characters": [{"name": "...", "description": "...", "appearance": "...", "wardrobe": "..."}], '
            '"locations": [{"name": "...", "description": "...", "environment": "...", "lighting": "...", "atmosphere": "..."}], '
            '"scenes": [{"title": "...", "description": "...", "location": "location name", "time_of_day": "...", '
            '"mood": "...", "lighting": "...", "characters": ["name"], "shots": [{"title": "...", "description": "...", '
            '"action": "...", "dialogue": "", "shot_size": "medium", "camera_angle": "front", "camera_elevation": "eye", '
            '"composition": "center", "camera_move": "static", "duration_seconds": 4, "characters": ["name"], '
            '"location": "location name"}]}]}'
        )
        user_text = f"Idea: {idea}" + (f"\nVisual style: {req.style}" if req.style.strip() else "")
        messages = [LLMMessage("system", system_text), LLMMessage("user", user_text)]
        reply = provider.chat(messages, None, json_mode=True)
        try:
            plan = FilmBuildPlan.model_validate(parse_json_block(reply.text))
        except ValidationError as exc:
            raise HTTPError(502, f"LLM film plan did not match the expected schema: {exc}") from exc
        if not plan.scenes:
            raise HTTPError(502, "LLM film plan contained no scenes")
        if not plan.script.strip():
            plan.script = _plan_to_script(plan)
        context = self._context(
            provider, "script", steps=1, tool_calls=0, prompt_chars=messages_chars(messages), summary_chars=0,
            replies=[reply], scope="idea and style only; no project state sent",
        )
        return FilmBuildResponse(plan=plan, used_llm=True, context=context)

    def apply_build(self, project_id: str, req: FilmBuildApplyRequest) -> FilmBuildApplyResponse:
        if not req.plan.scenes:
            raise HTTPError(400, "The plan has no scenes")
        project = self._film.get_project(project_id)
        if project.scenes and not req.replace_existing:
            raise HTTPError(409, "This project already has scenes. Pass replace_existing=true to replace them.")
        return self._apply_plan(project_id, req.plan, replace_existing=req.replace_existing, set_script=True)

    def _apply_plan(
        self, project_id: str, plan: FilmBuildPlan, *, replace_existing: bool, set_script: bool
    ) -> FilmBuildApplyResponse:
        with self.lock:
            project = self._film.store.load(project_id)
            if replace_existing:
                project.scenes = []
            if plan.title and not project.name:
                project.name = plan.title
            if set_script and plan.script.strip():
                project.script.content = plan.script
                project.script.updated_at = now_ms()

            def key(name: str) -> str:
                return name.strip().lower()

            character_ids = {key(a.name): a.id for a in project.assets if a.kind == "character"}
            location_ids = {key(a.name): a.id for a in project.assets if a.kind == "location"}
            characters_created = 0
            locations_created = 0
            for character in plan.characters:
                name = character.name.strip()
                if not name or key(name) in character_ids:
                    continue
                asset = FilmAsset(
                    kind="character",
                    name=name,
                    description=character.description,
                    appearance=character.appearance,
                    wardrobe=character.wardrobe,
                )
                project.assets.append(asset)
                character_ids[key(name)] = asset.id
                characters_created += 1
            for location in plan.locations:
                name = location.name.strip()
                if not name or key(name) in location_ids:
                    continue
                asset = FilmAsset(
                    kind="location",
                    name=name,
                    description=location.description,
                    environment=location.environment,
                    lighting=location.lighting,
                    atmosphere=location.atmosphere,
                )
                project.assets.append(asset)
                location_ids[key(name)] = asset.id
                locations_created += 1

            def ensure_character(name: str) -> str | None:
                nonlocal characters_created
                if not name.strip():
                    return None
                existing = character_ids.get(key(name))
                if existing:
                    return existing
                asset = FilmAsset(kind="character", name=name.strip().title())
                project.assets.append(asset)
                character_ids[key(name)] = asset.id
                characters_created += 1
                return asset.id

            def ensure_location(name: str) -> str | None:
                nonlocal locations_created
                if not name.strip():
                    return None
                existing = location_ids.get(key(name))
                if existing:
                    return existing
                asset = FilmAsset(kind="location", name=name.strip())
                project.assets.append(asset)
                location_ids[key(name)] = asset.id
                locations_created += 1
                return asset.id

            shots_created = 0
            for scene_index, scene_plan in enumerate(plan.scenes):
                scene = FilmScene(
                    order=len(project.scenes),
                    title=scene_plan.title or f"Scene {scene_index + 1}",
                    description=scene_plan.description,
                    time_of_day=scene_plan.time_of_day,
                    mood=scene_plan.mood,
                    lighting=scene_plan.lighting,
                    location_id=ensure_location(scene_plan.location),
                )
                for name in scene_plan.characters:
                    asset_id = ensure_character(name)
                    if asset_id and asset_id not in scene.character_ids:
                        scene.character_ids.append(asset_id)
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
                        title=shot_plan.title or f"Shot {shot_index + 1}",
                        description=shot_plan.description,
                        action=shot_plan.action,
                        dialogue=shot_plan.dialogue,
                        duration_seconds=max(1.0, min(20.0, shot_plan.duration_seconds)),
                        framing=framing,
                        status="draft",
                        location_id=ensure_location(shot_plan.location) or scene.location_id,
                    )
                    if shot_plan.camera_move in CAMERA_MOVE_LABELS:
                        shot.camera_move = shot_plan.camera_move  # type: ignore[assignment]
                    for name in shot_plan.characters:
                        asset_id = ensure_character(name)
                        if asset_id and all(c.asset_id != asset_id for c in shot.characters):
                            shot.characters.append(ShotCharacter(asset_id=asset_id))
                            if asset_id not in scene.character_ids:
                                scene.character_ids.append(asset_id)
                    scene.shots.append(shot)
                    shots_created += 1
                project.scenes.append(scene)

            # Prompts synthesize lazily on the next shot update; do it now so
            # draft cards show a meaningful prompt immediately.
            for scene in project.scenes:
                for shot in scene.shots:
                    if not shot.prompt_locked:
                        shot.visual_prompt = synthesize_prompt(project, scene, shot)
            project.updated_at = now_ms()
            self._film.store.save(project)

        return FilmBuildApplyResponse(
            status="applied",
            scenes_created=len(plan.scenes),
            shots_created=shots_created,
            characters_created=characters_created,
            locations_created=locations_created,
            project=self._film.get_project(project_id),
        )


# ---- Build helpers ---------------------------------------------------------


def _build_character(name: str) -> FilmBuildCharacter:
    return FilmBuildCharacter(name=name.strip().title())


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_HEURISTIC_COVERAGE: list[tuple[str, str, str, str, str, float]] = [
    ("Establishing", "wide", "front", "high", "leadingLines", 5.0),
    ("Medium", "medium", "threeQuarterLeft", "eye", "rightThird", 4.0),
    ("Close-up", "closeup", "front", "eye", "center", 3.0),
    ("Reverse", "mcu", "threeQuarterRight", "eye", "leftThird", 3.0),
    ("Detail", "xcu", "front", "low", "center", 2.5),
    ("Wide reveal", "xwide", "profile", "eye", "symmetrical", 5.0),
    ("Over the shoulder", "medium", "ots", "eye", "rightThird", 4.0),
    ("Low angle", "full", "front", "low", "center", 4.0),
]
_HEURISTIC_MOVES = ["static", "push_in", "pan_left", "static", "dolly_right", "pull_out", "static", "orbit"]


def _heuristic_build_plan(idea: str, target_scenes: int, target_shots: int, style: str) -> FilmBuildPlan:
    """Deterministic plan when no LLM is configured: split the idea into beats
    and cover each with standard shot progression."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(idea) if s.strip()]
    if not sentences:
        sentences = [idea.strip()]
    beats: list[str] = []
    per = max(1, round(len(sentences) / target_scenes))
    for index in range(0, len(sentences), per):
        beats.append(" ".join(sentences[index : index + per]))
        if len(beats) == target_scenes:
            beats[-1] = " ".join(sentences[index:])
            break
    while len(beats) < target_scenes:
        beats.append(beats[-1] if beats else idea)
    scenes: list[FilmBuildScene] = []
    for scene_index, beat in enumerate(beats):
        shots: list[FilmBuildShot] = []
        for shot_index in range(target_shots):
            title, size, angle, elevation, composition, duration = _HEURISTIC_COVERAGE[
                shot_index % len(_HEURISTIC_COVERAGE)
            ]
            shots.append(
                FilmBuildShot(
                    title=f"{title}",
                    description=beat,
                    action=beat if shot_index == 0 else "",
                    shot_size=size,
                    camera_angle=angle,
                    camera_elevation=elevation,
                    composition=composition,
                    camera_move=_HEURISTIC_MOVES[shot_index % len(_HEURISTIC_MOVES)],
                    duration_seconds=duration,
                )
            )
        scenes.append(FilmBuildScene(title=f"Scene {scene_index + 1}", description=beat, shots=shots))
    plan = FilmBuildPlan(title=idea[:60].strip().rstrip(".") or "Untitled film", logline=idea, style=style, scenes=scenes)
    plan.script = _plan_to_script(plan)
    return plan


def _plan_to_script(plan: FilmBuildPlan) -> str:
    lines: list[str] = []
    if plan.title:
        lines.append(plan.title.upper())
        lines.append("")
    if plan.logline:
        lines.append(plan.logline)
        lines.append("")
    for index, scene in enumerate(plan.scenes):
        heading = scene.title or f"Scene {index + 1}"
        location = scene.location.upper() if scene.location else heading.upper()
        time_of_day = (scene.time_of_day or "DAY").upper()
        if not heading.upper().startswith(("INT.", "EXT.")):
            heading = f"INT. {location} - {time_of_day}"
        lines.append(heading)
        lines.append("")
        if scene.description:
            lines.append(scene.description)
            lines.append("")
        for shot in scene.shots:
            if shot.action:
                lines.append(shot.action)
                lines.append("")
            if shot.dialogue:
                speaker = (shot.characters[0] if shot.characters else "VOICE").upper()
                lines.append(speaker)
                lines.append(shot.dialogue)
                lines.append("")
    return "\n".join(lines).strip() + "\n"
