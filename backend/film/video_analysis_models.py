"""Domain models for analysing an existing video.

The reverse of the filmmaking flow: a file on disk becomes shots, shots become
structured observations, and those become an editable TFG project. The models
mirror the forward-flow vocabulary (`film_models.py`) wherever the same idea
exists, so a reconstructed shot is the same kind of thing as an authored one.

Two rules run through the schema:

* Anything a model inferred carries a confidence and is kept apart from what
  was measured. A frame timestamp is a fact; "this is an over-the-shoulder on
  the protagonist" is not.
* The evidence that produced a field stays attached, so the UI can answer
  "why did the AI write this?" without guessing.
"""

from __future__ import annotations

from typing import Annotated, Literal, cast

from pydantic import BaseModel, BeforeValidator, Field

from film.film_models import now_ms


def _flatten_shape(v: object) -> object:
    """Collapse single-item lists to the bare string; join longer ones.

    Small local models emit 'background': ['dark space'] where a string
    belongs. Runs before _coerce_list_shape so both shapes are accepted.
    """
    if isinstance(v, list):
        strings: list[str] = [item for item in cast(list[object], v) if isinstance(item, str)]
        if len(strings) == 1:
            return strings[0]
        if len(strings) > 1:
            return "; ".join(item for item in strings if item.strip())
        return ""
    return v


def _coerce_list_shape(v: object) -> object:
    """Coerce a bare string (or None) into a single-item list; drop junk items."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        cleaned: list[str] = [item for item in cast(list[object], v) if isinstance(item, str) and item.strip()]
        return cleaned
    return v


#: A list[str] field that accepts every shape the small models emit:
#: 'astronaut', ['astronaut'], ['a', 'b'], '', None.
FlexibleStrList = Annotated[list[str], BeforeValidator(_coerce_list_shape), BeforeValidator(_flatten_shape)]

#: A str field that accepts a list of strings too ('globe' / ['globe']).
FlexibleStr = Annotated[str, BeforeValidator(_flatten_shape)]

AnalysisDepth = Literal["fast", "standard", "detailed"]
AnalysisStage = Literal["idle", "probing", "detecting", "extracting", "analyzing", "complete", "failed", "cancelled"]
DetectionMethod = Literal["cut", "fade", "uniform", "whole"]
#: How a field's value came to be. Kept per group so the UI can shade inference.
Provenance = Literal["measured", "inferred", "user"]


class VideoSourceInfo(BaseModel):
    """What the container told us. All measured, none inferred."""

    path: str = ""
    file_name: str = ""
    size_bytes: int = 0
    duration_seconds: float = 0.0
    fps: float = 0.0
    width: int = 0
    height: int = 0
    aspect_ratio: str = ""
    codec: str = ""
    bit_rate: int = 0
    frame_count: int = 0
    has_audio: bool = False
    audio_codec: str = ""
    audio_channels: int = 0
    audio_sample_rate: int = 0
    rotation: int = 0
    pixel_format: str = ""


class FrameEvidence(BaseModel):
    """One extracted still, and where it came from in the source."""

    #: Path relative to the analysis directory.
    path: str = ""
    timestamp: float = 0.0
    role: Literal["start", "middle", "end", "representative"] = "representative"


class VisualAnalysis(BaseModel):
    """What the frames show — produced by the AI director or the offline pass.

    All fields use the flexible shapes so small local models' type flips
    (list where a string belongs and vice versa) cannot fail the analysis.
    """

    description: FlexibleStr = ""
    subjects: FlexibleStrList = Field(default_factory=list[str])
    character_estimates: FlexibleStrList = Field(default_factory=list[str])
    objects: FlexibleStrList = Field(default_factory=list[str])
    location: FlexibleStr = ""
    environment: FlexibleStr = ""
    foreground: FlexibleStr = ""
    midground: FlexibleStr = ""
    background: FlexibleStr = ""
    composition: FlexibleStr = ""
    framing: FlexibleStr = ""
    shot_size: FlexibleStr = ""
    angle: FlexibleStr = ""
    camera_height: FlexibleStr = ""
    perspective: FlexibleStr = ""
    lens_estimate: FlexibleStr = ""
    depth_of_field: FlexibleStr = ""
    focus: FlexibleStr = ""
    lighting: FlexibleStr = ""
    palette: FlexibleStrList = Field(default_factory=list[str])
    contrast: FlexibleStr = ""
    visual_style: FlexibleStr = ""
    production_design: FlexibleStr = ""
    wardrobe: FlexibleStr = ""
    props: FlexibleStrList = Field(default_factory=list[str])
    confidence: float = 0.0


class CinematographyAnalysis(BaseModel):
    camera_position: FlexibleStr = ""
    camera_movement: FlexibleStr = ""
    movement_types: FlexibleStrList = Field(default_factory=list[str])
    is_static: bool = True
    screen_direction: FlexibleStr = ""
    eyeline: FlexibleStr = ""
    ots_relationship: FlexibleStr = ""
    blocking: FlexibleStr = ""
    composition_rules: FlexibleStrList = Field(default_factory=list[str])
    confidence: float = 0.0


class NarrativeAnalysis(BaseModel):
    """What the shot means in the story — produced by the AI director."""

    what_happens: FlexibleStr = ""
    who_acts: FlexibleStrList = Field(default_factory=list[str])
    narrative_purpose: FlexibleStr = ""
    emotional_purpose: FlexibleStr = ""
    story_beat: FlexibleStr = ""
    setup_or_payoff: FlexibleStr = ""
    continuity_implications: FlexibleStrList = Field(default_factory=list[str])
    pacing: FlexibleStr = ""
    transition_role: FlexibleStr = ""
    confidence: float = 0.0


class EditorialAnalysis(BaseModel):
    transition_in: str = ""
    transition_out: str = ""
    cut_type: str = ""
    rhythm: str = ""
    approximate_beat: str = ""
    montage_role: str = ""
    broll_role: str = ""
    confidence: float = 0.0


class AudioAnalysis(BaseModel):
    """Only populated when the source has audio and audio analysis was asked for."""

    analyzed: bool = False
    dialogue: str = ""
    transcription: str = ""
    voiceover: str = ""
    ambience: str = ""
    music: str = ""
    sfx: list[str] = Field(default_factory=list[str])
    silence: bool = False
    emphasis: str = ""
    rhythm: str = ""
    confidence: float = 0.0


class TextAnalysis(BaseModel):
    analyzed: bool = False
    visible_text: list[str] = Field(default_factory=list[str])
    subtitles: list[str] = Field(default_factory=list[str])
    signs: list[str] = Field(default_factory=list[str])
    ui_text: list[str] = Field(default_factory=list[str])
    typography: str = ""
    confidence: float = 0.0


class ReversePrompts(BaseModel):
    """Prompts derived from the analysis, one per job rather than one generic.

    `model_specific` is keyed by model id: the same shot reads differently to
    an LTX model than to a Wan or a hosted one, so the compiler fills this per
    target rather than copying one string everywhere.
    """

    storyboard: str = ""
    video: str = ""
    cinematography: str = ""
    environment: str = ""
    character: str = ""
    motion: str = ""
    negative: str = ""
    model_specific: dict[str, str] = Field(default_factory=dict[str, str])
    #: True once a human edited any field, so regeneration does not overwrite.
    edited: bool = False


class PromptLensAnalysis(BaseModel):
    """PromptLens reverse-engineered 1:1 prompt, one per shot.

    Recreates the prompt that could regenerate this exact shot: a single
    usable "core prompt", a deep 150-200-word description, and the six
    dimensions prompt-lens analyses (subject / environment / camera /
    lighting / style / mood).
    """

    core_prompt: FlexibleStr = ""
    deep_description: FlexibleStr = ""
    subject: FlexibleStr = ""
    environment: FlexibleStr = ""
    camera: FlexibleStr = ""
    lighting: FlexibleStr = ""
    style: FlexibleStr = ""
    mood: FlexibleStr = ""
    confidence: float = 0.0


class AnalyzedShot(BaseModel):
    """One detected shot and everything derived from it."""

    id: str = ""
    index: int = 0
    start: float = 0.0
    end: float = 0.0
    duration: float = 0.0
    detection_confidence: float = 0.0
    detection_method: DetectionMethod = "cut"
    #: True when a person moved this boundary; detection will not overwrite it.
    boundary_edited: bool = False
    frames: list[FrameEvidence] = Field(default_factory=list[FrameEvidence])

    visual: VisualAnalysis = Field(default_factory=VisualAnalysis)
    cinematography: CinematographyAnalysis = Field(default_factory=CinematographyAnalysis)
    narrative: NarrativeAnalysis = Field(default_factory=NarrativeAnalysis)
    editorial: EditorialAnalysis = Field(default_factory=EditorialAnalysis)
    audio: AudioAnalysis = Field(default_factory=AudioAnalysis)
    text: TextAnalysis = Field(default_factory=TextAnalysis)
    prompts: ReversePrompts = Field(default_factory=ReversePrompts)
    prompt_lens: PromptLensAnalysis = Field(default_factory=PromptLensAnalysis)

    #: Where the content came from: a model, or the deterministic fallback.
    analysis_provider: str = ""
    analysis_model: str = ""
    provenance: Provenance = "measured"
    #: Raw model reply, kept so "why did the AI write this?" has an answer.
    evidence_note: str = ""
    analyzed_at: int = 0


class VideoAnalysis(BaseModel):
    """A whole analysis job: its source, its shots, and its progress."""

    schema_version: int = 1
    id: str = ""
    title: str = ""
    source: VideoSourceInfo = Field(default_factory=VideoSourceInfo)
    shots: list[AnalyzedShot] = Field(default_factory=list[AnalyzedShot])

    # Requested options, kept so a re-run repeats what the user chose.
    depth: AnalysisDepth = "standard"
    sensitivity: float = 0.5
    min_shot_seconds: float = 0.6
    max_shots: int = 400
    detect_fades: bool = True
    analyze_audio: bool = False
    analyze_text: bool = False
    provider: str = ""
    model: str = ""

    stage: AnalysisStage = "idle"
    progress: float = 0.0
    message: str = ""
    error: str = ""
    #: Set once the analysis has produced a film project.
    reconstructed_project_id: str = ""

    # Story-level inference, filled once the shots are understood.
    synopsis: str = ""
    visual_style: str = ""
    characters: list[str] = Field(default_factory=list[str])
    locations: list[str] = Field(default_factory=list[str])

    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)

    def shot(self, shot_id: str) -> AnalyzedShot | None:
        return next((shot for shot in self.shots if shot.id == shot_id), None)
