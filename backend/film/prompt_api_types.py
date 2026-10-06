"""Request/response models for the prompt compiler routes."""

from __future__ import annotations

from pydantic import BaseModel, Field

from film.prompt_compiler import ConventionBasis, PromptHints, PromptStyle, ShotBrief, SpecCompileResult
from film.prompt_templates import PromptTemplate, TemplateProfile
from film.shot_spec import ShotSpec


class CompiledPromptPayload(BaseModel):
    """One brief rendered for one model, with an account of what it cost."""

    model: str = ""
    target_id: str = ""
    target_label: str = ""
    style: PromptStyle = "narrative"
    basis: ConventionBasis = "tfg_default"
    note: str = ""
    prompt: str = ""
    negative_prompt: str = ""
    #: False when the model id was not recognised, so the UI can say the prompt
    #: is the general convention rather than implying it was tailored.
    matched: bool = False
    #: Sections the target could not carry, each with the reason.
    dropped: list[str] = Field(default_factory=list[str])


class CompilePromptRequest(BaseModel):
    """Compile a brief for a set of models.

    Exactly one source: an explicit `brief`, a storyboard shot, or an analysed
    shot. The route rejects a request that names none or more than one, rather
    than guessing which was meant.
    """

    models: list[str] = Field(default_factory=list[str])

    brief: ShotBrief | None = None

    project_id: str = ""
    scene_id: str = ""
    shot_id: str = ""

    analysis_id: str = ""
    analysis_shot_id: str = ""


class CompilePromptResponse(BaseModel):
    #: The common representation the prompts were compiled from, so the caller
    #: can show what was actually said before any model saw it.
    brief: ShotBrief = Field(default_factory=ShotBrief)
    prompts: list[CompiledPromptPayload] = Field(default_factory=list[CompiledPromptPayload])


class PromptTargetPayload(BaseModel):
    id: str = ""
    label: str = ""
    style: PromptStyle = "narrative"
    basis: ConventionBasis = "tfg_default"
    note: str = ""
    max_chars: int = 0
    supports_negative: bool = True
    renders_audio: bool = False
    renders_motion: bool = True
    #: What in a model id identifies this family, so the rule is inspectable.
    matches: list[str] = Field(default_factory=list[str])


class PromptTargetListResponse(BaseModel):
    targets: list[PromptTargetPayload] = Field(default_factory=list[PromptTargetPayload])


class CompileSpecRequest(BaseModel):
    """Compile a ShotSpec for one target, optionally with knowledge hints."""

    spec: ShotSpec
    target: str
    style: PromptStyle | None = None
    seed: int | None = None
    #: Ask the knowledge engine for winning phrases/params before compiling.
    use_hints: bool = True
    model: str = ""


class CompileSpecResponse(BaseModel):
    result: SpecCompileResult
    hints: PromptHints | None = None
    spec_keys: list[str] = Field(default_factory=list[str])


class CompileSpecAllResponse(BaseModel):
    """One compile per target × style, for the Reproduce editor's tabs."""

    results: dict[str, SpecCompileResult] = Field(default_factory=dict[str, SpecCompileResult])
    hints: PromptHints | None = None


class PromptTemplateListResponse(BaseModel):
    templates: list[PromptTemplate] = Field(default_factory=list[PromptTemplate])


class PromptTemplateUpdateRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=4000)


class PromptTemplateCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    instruction: str = Field(min_length=1, max_length=4000)
    description: str = ""
    profile: TemplateProfile = "custom"
