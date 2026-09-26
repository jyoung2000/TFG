"""Hardware presets: one click (or the first run) sets every default that
depends on the card. The RTX 4070 12 GB preset is the production target
(docs/RTX_4070_TEST_MATRIX.md); nothing in it can exceed the card.

A preset is a settings patch plus the words the UI shows for it. Applying
one goes through the normal settings update, so listeners, validation and
persistence all behave exactly as if the person had changed each field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

VideoProfile = Literal["fast", "balanced"]


@dataclass(frozen=True)
class VideoProfileSpec:
    id: VideoProfile
    label: str
    model: str
    resolution: str
    duration_seconds: int
    #: What the person trades when picking it.
    note: str


#: Quick video / Film "fast" vs "balanced" on the distilled LTX-2 model.
VIDEO_PROFILES: dict[VideoProfile, VideoProfileSpec] = {
    "fast": VideoProfileSpec("fast", "Fast", "ltx2_22B_distilled", "540p", 6, "540p · 6 s · 8 steps: a clip in about a minute on a 4070."),
    "balanced": VideoProfileSpec("balanced", "Balanced", "ltx2_22B_distilled", "720p", 8, "720p · 6–8 s: sharper, roughly three times longer per clip."),
}


@dataclass(frozen=True)
class HardwarePreset:
    id: str
    name: str
    #: Substrings (lower-case) of the GPU name that make this the recommended preset.
    gpu_markers: tuple[str, ...]
    #: VRAM range the preset is built for, in GB (inclusive).
    vram_gb: tuple[int, int]
    description: str
    #: Human-readable lines, one per thing the preset sets.
    changes: tuple[str, ...]
    #: The settings patch (snake_case, nested like `AppSettings`).
    patch: dict[str, Any] = field(default_factory=dict[str, Any])

    def recommended_for(self, gpu_name: str | None, vram_gb: float | None) -> bool:
        name = (gpu_name or "").lower()
        if any(marker in name for marker in self.gpu_markers):
            return True
        if vram_gb is not None and self.vram_gb[0] <= vram_gb <= self.vram_gb[1] and "nvidia" in name:
            return True
        return False


RTX_4070_12GB = HardwarePreset(
    id="rtx-4070-12gb",
    name="RTX 4070 · 12 GB",
    gpu_markers=("rtx 4070", "rtx 3080", "rtx 4070 super", "rtx 5070"),
    vram_gb=(11, 12),
    description="Everything local and sized for 12 GB of VRAM: distilled LTX-2 for video, Z-Image for stills, the small vision stack, no VLM by default.",
    changes=(
        "Video: LTX-2 22B distilled — Fast profile (540p · 6 s), Balanced available (720p · 6–8 s)",
        "Image: Z-Image at 8 steps",
        "Vision: Florence-2-large captions, CLIP ViT-L/14 tags, Depth-Anything-V2-small, DINOv2-small",
        "VLM off by default (turn on Ollama in Settings → Vision when you want it); keep_alive 0 so it never holds VRAM",
        "Local text encoder on, media provider local, VRAM budget 12 GB",
    ),
    patch={
        "hardware_preset": "rtx-4070-12gb",
        "gpu_vram_budget_gb": 12.0,
        "default_video_model": "ltx2_22B_distilled",
        "default_image_model": "z_image",
        "video_profile": "fast",
        "image_steps": 8,
        "use_local_text_encoder": True,
        "media_provider": "local",
        "pro_model": {"steps": 20},
        "vision": {
            "enabled": True,
            "florence_enabled": True,
            "florence_model": "florence-2-large",
            "clip_enabled": True,
            "clip_model": "openai/clip-vit-large-patch14",
            "depth_enabled": True,
            "depth_model": "depth-anything-v2-small",
            "dino_enabled": True,
            "dino_model": "dinov2-small",
            "vlm_provider": "off",
            "vlm_keep_alive": "0",
        },
    },
)

PRESETS: dict[str, HardwarePreset] = {RTX_4070_12GB.id: RTX_4070_12GB}


def recommended_preset(gpu_name: str | None, vram_gb: float | None) -> HardwarePreset | None:
    for preset in PRESETS.values():
        if preset.recommended_for(gpu_name, vram_gb):
            return preset
    return None
