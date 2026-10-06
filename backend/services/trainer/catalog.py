"""Which trainer handles which target, and whether it fits 12 GB.

Facts recorded in session-notes (VF-014..): musubi-tuner documents
"12GB or more recommended for image training, 24GB or more for video
training" with `--blocks_to_swap` / `--fp8_base --fp8_scaled` / `--fp8_llm`
memory savers; ai-toolkit trains Z-Image, FLUX and Qwen-Image LoRAs with
`quantize: true` + `low_vram: true`; the LTX-2 trainer recommends 80 GB and
ships a 32 GB low-VRAM config, so it is catalogued but not runnable here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MACHINE_VRAM_MB = 12288


@dataclass(frozen=True)
class TrainerSpec:
    id: str
    name: str
    upstream: str
    license: str
    targets: tuple[str, ...]
    #: Estimated peak VRAM (MB) of the 12 GB-safe preset for image training.
    image_vram_mb: int
    #: Estimated peak VRAM (MB) for video training with block swap; 0 = not supported at 12 GB.
    video_vram_mb: int
    env_name: str
    notes: str
    extra_flags: dict[str, str] = field(default_factory=dict[str, str])

    @property
    def fits_12gb(self) -> bool:
        return self.image_vram_mb <= MACHINE_VRAM_MB


TRAINERS: tuple[TrainerSpec, ...] = (
    TrainerSpec(
        id="musubi",
        name="musubi-tuner",
        upstream="https://github.com/kohya-ss/musubi-tuner",
        license="Apache-2.0",
        targets=("z_image", "qwen_image", "wan22", "flux"),
        image_vram_mb=11000,
        video_vram_mb=0,
        env_name=".venv-trainer-musubi",
        notes="Image LoRAs (Z-Image, Qwen-Image, FLUX) fit 12 GB with fp8 + block swap; Wan 2.2 video LoRAs need 24 GB per upstream and are refused here.",
    ),
    TrainerSpec(
        id="ai-toolkit",
        name="ostris ai-toolkit",
        upstream="https://github.com/ostris/ai-toolkit",
        license="MIT",
        targets=("z_image", "flux", "qwen_image"),
        image_vram_mb=11500,
        video_vram_mb=0,
        env_name=".venv-trainer-aitoolkit",
        notes="quantize + low_vram config; Z-Image Turbo / de-turbo, FLUX.1/2 klein, Qwen-Image.",
    ),
    TrainerSpec(
        id="ltx-trainer",
        name="Lightricks LTX-2 trainer",
        upstream="https://github.com/Lightricks/LTX-2/tree/main/packages/ltx-trainer",
        license="Apache-2.0",
        targets=("ltx2",),
        image_vram_mb=32768,
        video_vram_mb=32768,
        env_name=".venv-trainer-ltx",
        notes="Upstream recommends 80 GB; the low-VRAM config targets 32 GB. Not runnable on a 12 GB card — listed so the UI can say so.",
    ),
)


def trainer_for(trainer_id: str) -> TrainerSpec | None:
    return next((t for t in TRAINERS if t.id == trainer_id), None)


def trainers_for_target(target: str) -> list[TrainerSpec]:
    return [t for t in TRAINERS if target in t.targets]
