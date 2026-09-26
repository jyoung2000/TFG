"""Florence-2 wrapper.

Task prompts, the HF model registry and the task → post-processing map are
adapted from kijai/ComfyUI-Florence2 (MIT, `nodes.py`) — the ComfyUI model
management and folder plumbing are replaced by `VramManager` and the app's
models directory. The model classes themselves come from `transformers`
(native `Florence2ForConditionalGeneration`, no `trust_remote_code`).

Heavy imports happen inside `load()`, never at module import.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from PIL import Image

from services.vision.protocol import CaptionLevel, CaptionResult, DetectResult, DetectTask, VisionRegion, VramClass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FlorenceModelSpec:
    id: str
    repo_id: str
    vram_class: VramClass
    estimated_mb: int
    #: PromptGen fine-tunes add the GENERATE_TAGS / MIXED_CAPTION_PLUS tasks.
    prompt_gen: bool = False
    description: str = ""


#: Registry adapted from kijai/ComfyUI-Florence2 `nodes.py` model list.
FLORENCE_MODELS: dict[str, FlorenceModelSpec] = {
    "florence-2-base": FlorenceModelSpec("florence-2-base", "microsoft/Florence-2-base", "S", 600, description="0.23B, fast; captions + detection"),
    "florence-2-large": FlorenceModelSpec("florence-2-large", "microsoft/Florence-2-large", "M", 1700, description="0.77B, best captions + grounding"),
    "florence-2-base-ft": FlorenceModelSpec("florence-2-base-ft", "microsoft/Florence-2-base-ft", "S", 600),
    "florence-2-large-ft": FlorenceModelSpec("florence-2-large-ft", "microsoft/Florence-2-large-ft", "M", 1700),
    "promptgen-large-v2": FlorenceModelSpec("promptgen-large-v2", "MiaoshouAI/Florence-2-large-PromptGen-v2.0", "M", 1700, prompt_gen=True, description="tags + mixed caption for prompt writing"),
    "promptgen-base-v2": FlorenceModelSpec("promptgen-base-v2", "MiaoshouAI/Florence-2-base-PromptGen-v2.0", "S", 600, prompt_gen=True),
    "cogflorence-large": FlorenceModelSpec("cogflorence-large", "thwri/CogFlorence-2.2-Large", "M", 1700, description="long natural-language captions"),
    "florence-2-flux-large": FlorenceModelSpec("florence-2-flux-large", "gokaygokay/Florence-2-Flux-Large", "M", 1700, description="captions phrased for Flux/T5 prompts"),
}
DEFAULT_FLORENCE_MODEL = "florence-2-large"

#: Task token per public task name (adapted from kijai's task map).
TASK_TOKENS: dict[str, str] = {
    "caption": "<CAPTION>",
    "detailed_caption": "<DETAILED_CAPTION>",
    "more_detailed_caption": "<MORE_DETAILED_CAPTION>",
    "od": "<OD>",
    "dense_region_caption": "<DENSE_REGION_CAPTION>",
    "region_proposal": "<REGION_PROPOSAL>",
    "caption_to_phrase_grounding": "<CAPTION_TO_PHRASE_GROUNDING>",
    "ocr": "<OCR>",
    "prompt_gen_tags": "<GENERATE_TAGS>",
    "prompt_gen_mixed_caption": "<MIXED_CAPTION>",
    "prompt_gen_mixed_caption_plus": "<MIXED_CAPTION_PLUS>",
    "prompt_gen_analyze": "<ANALYZE>",
}
#: Tasks whose output is boxes rather than text (kijai: post-processing selector).
BOX_TASKS = frozenset({"od", "dense_region_caption", "region_proposal", "caption_to_phrase_grounding"})


def clean_caption(text: str) -> str:
    """Strip the task token echoes and pad tokens Florence leaves in generations
    (kijai: caption cleanup)."""
    cleaned = re.sub(r"<[^>]+>", "", text)
    cleaned = cleaned.replace("</s>", "").replace("<s>", "").replace("<pad>", "")
    return " ".join(cleaned.split()).strip()


def parse_boxes(parsed: dict[str, Any], task: str, width: int, height: int) -> list[VisionRegion]:
    """Turn the processor's post_process_generation payload into normalised regions.

    Florence returns `{'<OD>': {'bboxes': [[x1,y1,x2,y2],…], 'labels': [...]}}`
    in pixel coordinates; grounding uses the same shape; region proposals
    have empty labels."""
    token = TASK_TOKENS[task]
    payload = cast(dict[str, Any], parsed.get(token, parsed))
    boxes = cast(list[list[float]], payload.get("bboxes", []))
    labels = cast(list[str], payload.get("labels", []) or payload.get("bboxes_labels", []))
    regions: list[VisionRegion] = []
    for index, box in enumerate(boxes):
        if len(box) != 4 or width <= 0 or height <= 0:
            continue
        x1, y1, x2, y2 = (float(v) for v in box)
        label = clean_caption(labels[index]) if index < len(labels) else "region"
        regions.append(
            VisionRegion(
                label=label or "region",
                bbox=[round(x1 / width, 4), round(y1 / height, 4), round((x2 - x1) / width, 4), round((y2 - y1) / height, 4)],
            )
        )
    return regions


class Florence2:
    """Lazy Florence-2 runner. `load()` is the only place torch is touched."""

    name = "florence"

    def __init__(self, model_id: str = DEFAULT_FLORENCE_MODEL, *, cache_dir: Path | None = None, device: str = "auto") -> None:
        self.spec = FLORENCE_MODELS.get(model_id, FLORENCE_MODELS[DEFAULT_FLORENCE_MODEL])
        self._cache_dir = cache_dir
        self._device = device
        self._model: Any = None
        self._processor: Any = None
        self._dtype: Any = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def model_id(self) -> str:
        return self.spec.id

    def load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoProcessor, Florence2ForConditionalGeneration  # pyright: ignore[reportUnknownVariableType]

        device = self._device
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self._dtype = torch.float16 if device == "cuda" else torch.float32
        kwargs: dict[str, Any] = {"torch_dtype": self._dtype}
        if self._cache_dir is not None:
            kwargs["cache_dir"] = str(self._cache_dir)
        logger.info("Loading %s (%s) on %s", self.spec.id, self.spec.repo_id, device)
        self._processor = AutoProcessor.from_pretrained(self.spec.repo_id, **({"cache_dir": str(self._cache_dir)} if self._cache_dir else {}))  # pyright: ignore[reportUnknownMemberType]
        model = Florence2ForConditionalGeneration.from_pretrained(self.spec.repo_id, **kwargs)  # pyright: ignore[reportUnknownMemberType]
        self._model = model.to(device).eval()  # pyright: ignore[reportUnknownMemberType]
        self._device = device

    def unload(self) -> None:
        if self._model is None:
            return
        self._model = None
        self._processor = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass

    def _run(self, image: Image.Image, task: str, text: str = "", max_new_tokens: int = 512) -> tuple[str, dict[str, Any]]:
        self.load()
        import torch

        token = TASK_TOKENS[task]
        prompt = f"{token}{text}" if text else token
        inputs = self._processor(text=prompt, images=image, return_tensors="pt")
        inputs = {k: (v.to(self._device, self._dtype) if k == "pixel_values" else v.to(self._device)) for k, v in inputs.items()}
        with torch.inference_mode():
            generated = self._model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=max_new_tokens,
                num_beams=3,
                do_sample=False,
            )
        raw = cast(str, self._processor.batch_decode(generated, skip_special_tokens=False)[0])
        parsed = cast(dict[str, Any], self._processor.post_process_generation(raw, task=token, image_size=image.size))
        return raw, parsed

    def caption(self, image: Image.Image, level: CaptionLevel) -> CaptionResult:
        task = level
        if task.startswith("prompt_gen") and not self.spec.prompt_gen:
            task = "more_detailed_caption"
        raw, parsed = self._run(image, task)
        text = parsed.get(TASK_TOKENS[task], raw)
        return CaptionResult(text=clean_caption(str(text)), level=task, model=self.spec.id)

    def detect(self, image: Image.Image, task: DetectTask, text: str = "") -> DetectResult:
        _, parsed = self._run(image, task, text=text if task == "caption_to_phrase_grounding" else "")
        width, height = image.size
        return DetectResult(task=task, model=self.spec.id, regions=parse_boxes(parsed, task, width, height))
