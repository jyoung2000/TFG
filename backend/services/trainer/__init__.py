"""LoRA training behind one Protocol (phase 7).

`LoraTrainer` is the service boundary. Real trainers are subprocess wrappers
around upstream projects that each live in their own environment
(`scripts/ensure-trainer.{sh,ps1}`): kohya-ss/musubi-tuner for Z-Image,
Qwen-Image and Wan 2.x, ostris/ai-toolkit for Z-Image / FLUX / Qwen-Image.
LTX-2's own trainer is catalogued but does not fit 12 GB (its low-VRAM config
targets 32 GB), so it reports itself unavailable on this machine instead of
pretending. `FakeTrainer` simulates a run for tests.
"""

from services.trainer.catalog import TRAINERS, TrainerSpec, trainer_for, trainers_for_target
from services.trainer.fake_trainer import FakeTrainer
from services.trainer.trainer import (
    LoraTrainer,
    TrainerUnavailable,
    TrainingOutcome,
    TrainingProgress,
    TrainingRequest,
)
from services.trainer.subprocess_trainer import AiToolkitTrainer, MusubiTrainer, SubprocessTrainer, select_trainer

__all__ = [
    "AiToolkitTrainer",
    "FakeTrainer",
    "LoraTrainer",
    "MusubiTrainer",
    "SubprocessTrainer",
    "TRAINERS",
    "TrainerSpec",
    "TrainerUnavailable",
    "TrainingOutcome",
    "TrainingProgress",
    "TrainingRequest",
    "select_trainer",
    "trainer_for",
    "trainers_for_target",
]
