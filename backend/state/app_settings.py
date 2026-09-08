"""Canonical app settings schema and patch models."""

from __future__ import annotations

import os
from typing import Any, Literal, TypeGuard, TypeVar, cast, get_args

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

# Canonical environment variable for the OpenRouter secret. The settings file
# value wins when present; the env var is the fallback for users who prefer
# not to persist the key on disk.
OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"

DirectorProvider = Literal["auto", "gemini", "openrouter"]


def _to_camel_case(field_name: str) -> str:
    special_aliases = {
        "prompt_enhancer_enabled_t2v": "promptEnhancerEnabledT2V",
        "prompt_enhancer_enabled_i2v": "promptEnhancerEnabledI2V",
    }
    if field_name in special_aliases:
        return special_aliases[field_name]

    head, *tail = field_name.split("_")
    return head + "".join(part.title() for part in tail)


def _clamp_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    if value is None:
        return default

    parsed = int(value)
    return max(minimum, min(maximum, parsed))


class SettingsBaseModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel_case,
        populate_by_name=True,
        validate_assignment=True,
        extra="ignore",
    )


class SettingsPatchModel(SettingsBaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel_case,
        populate_by_name=True,
        validate_assignment=True,
        extra="forbid",
    )


class FastModelSettings(SettingsBaseModel):
    use_upscaler: bool = True


class ProModelSettings(SettingsBaseModel):
    steps: int = 20
    use_upscaler: bool = True

    @field_validator("steps", mode="before")
    @classmethod
    def _clamp_steps(cls, value: Any) -> int:
        return _clamp_int(value, minimum=1, maximum=100, default=20)


class OpenRouterRoleModels(SettingsBaseModel):
    """Preferred OpenRouter model per AI Director role ('' = use default_model)."""

    default_model: str = "openai/gpt-4o-mini"
    script: str = ""
    storyboard: str = ""
    director: str = ""
    continuity: str = ""
    prompt_refinement: str = ""

    def for_role(self, role: str) -> str:
        chosen = getattr(self, role, "") if role in type(self).model_fields else ""
        return str(chosen).strip() or self.default_model.strip() or "openai/gpt-4o-mini"


class AppSettings(SettingsBaseModel):
    use_torch_compile: bool = False
    load_on_startup: bool = False
    ltx_api_key: str = ""
    user_prefers_ltx_api_video_generations: bool = False
    fal_api_key: str = ""
    use_local_text_encoder: bool = False
    fast_model: FastModelSettings = Field(default_factory=FastModelSettings)
    pro_model: ProModelSettings = Field(default_factory=ProModelSettings)
    prompt_cache_size: int = 100
    prompt_enhancer_enabled_t2v: bool = True
    prompt_enhancer_enabled_i2v: bool = False
    gemini_api_key: str = ""
    openrouter_api_key: str = ""
    director_provider: DirectorProvider = "auto"
    openrouter_models: OpenRouterRoleModels = Field(default_factory=OpenRouterRoleModels)
    seed_locked: bool = False
    locked_seed: int = 42

    def resolved_openrouter_api_key(self) -> str:
        """Settings-file key first, OPENROUTER_API_KEY env var as fallback."""
        stored = self.openrouter_api_key.strip()
        if stored:
            return stored
        return os.environ.get(OPENROUTER_API_KEY_ENV, "").strip()

    def openrouter_key_source(self) -> Literal["settings", "env", "none"]:
        if self.openrouter_api_key.strip():
            return "settings"
        if os.environ.get(OPENROUTER_API_KEY_ENV, "").strip():
            return "env"
        return "none"

    @field_validator("prompt_cache_size", mode="before")
    @classmethod
    def _clamp_prompt_cache_size(cls, value: Any) -> int:
        return _clamp_int(value, minimum=0, maximum=1000, default=100)

    @field_validator("locked_seed", mode="before")
    @classmethod
    def _clamp_locked_seed(cls, value: Any) -> int:
        return _clamp_int(value, minimum=0, maximum=2_147_483_647, default=42)


SettingsModelT = TypeVar("SettingsModelT", bound=SettingsBaseModel)
_PARTIAL_MODEL_CACHE: dict[type[SettingsBaseModel], type[SettingsPatchModel]] = {}


def _wrap_optional(annotation: Any) -> Any:
    if type(None) in get_args(annotation):
        return annotation
    return annotation | None


def _to_partial_annotation(annotation: Any) -> Any:
    if _is_settings_model_annotation(annotation):
        return make_partial_model(annotation)
    return annotation


def make_partial_model(model: type[SettingsModelT]) -> type[SettingsPatchModel]:
    cached = _PARTIAL_MODEL_CACHE.get(model)
    if cached is not None:
        return cached

    fields: dict[str, tuple[Any, Any]] = {}
    for field_name, field_info in model.model_fields.items():
        partial_annotation = _wrap_optional(_to_partial_annotation(field_info.annotation))
        fields[field_name] = (partial_annotation, Field(default=None))

    partial_model = create_model(
        f"{model.__name__}Patch",
        __base__=SettingsPatchModel,
        **cast(Any, fields),
    )

    _PARTIAL_MODEL_CACHE[model] = partial_model
    return partial_model


def _is_settings_model_annotation(annotation: object) -> TypeGuard[type[SettingsBaseModel]]:
    return isinstance(annotation, type) and issubclass(annotation, SettingsBaseModel)


AppSettingsPatch = make_partial_model(AppSettings)
UpdateSettingsRequest = AppSettingsPatch


class SettingsResponse(SettingsBaseModel):
    use_torch_compile: bool = False
    load_on_startup: bool = False
    has_ltx_api_key: bool = False
    user_prefers_ltx_api_video_generations: bool = False
    has_fal_api_key: bool = False
    use_local_text_encoder: bool = False
    fast_model: FastModelSettings = Field(default_factory=FastModelSettings)
    pro_model: ProModelSettings = Field(default_factory=ProModelSettings)
    prompt_cache_size: int = 100
    prompt_enhancer_enabled_t2v: bool = True
    prompt_enhancer_enabled_i2v: bool = False
    has_gemini_api_key: bool = False
    has_openrouter_api_key: bool = False
    openrouter_key_source: str = "none"
    director_provider: DirectorProvider = "auto"
    openrouter_models: OpenRouterRoleModels = Field(default_factory=OpenRouterRoleModels)
    seed_locked: bool = False
    locked_seed: int = 42


def to_settings_response(settings: AppSettings) -> SettingsResponse:
    data = settings.model_dump(by_alias=False)
    ltx_key = data.pop("ltx_api_key", "")
    fal_key = data.pop("fal_api_key", "")
    gemini_key = data.pop("gemini_api_key", "")
    data.pop("openrouter_api_key", "")
    data["has_ltx_api_key"] = bool(ltx_key)
    data["has_fal_api_key"] = bool(fal_key)
    data["has_gemini_api_key"] = bool(gemini_key)
    data["has_openrouter_api_key"] = bool(settings.resolved_openrouter_api_key())
    data["openrouter_key_source"] = settings.openrouter_key_source()
    return SettingsResponse.model_validate(data)


def should_video_generate_with_ltx_api(*, force_api_generations: bool, settings: AppSettings) -> bool:
    has_ltx_api_key = bool(settings.ltx_api_key.strip())
    return force_api_generations or (
        settings.user_prefers_ltx_api_video_generations and has_ltx_api_key
    )
