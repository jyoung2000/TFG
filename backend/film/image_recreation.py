"""Persistent, bounded image recreation with spatial comparison.

Scores are a *relative visual signal*, not proof of identity. All filesystem
references exposed by the API are relative to one analysis directory.
"""
from __future__ import annotations

import base64
import json
import math
import shutil
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any, cast

from PIL import Image, ImageChops, ImageStat, UnidentifiedImageError
from pydantic import BaseModel, Field

from _routes._errors import HTTPError
from film.llm_providers import LLMMessage, LLMProvider
from server_utils.path_policy import PathPolicyError, require_absolute_file

SUPPORTED = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}
MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 32_000_000


def describe_differences(value: object) -> str:
    """Flatten whatever shape a vision model used for 'differences' into text.

    qwen2.5vl:7b answers with {aspect: {reference: {...}, candidate: {...}}};
    larger models send a sentence or a list. Aspects where reference and
    candidate agree are dropped so only real mismatches drive the revision.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "; ".join(describe_differences(item) for item in cast(list[object], value) if describe_differences(item))
    if isinstance(value, dict):
        parts: list[str] = []
        for key, raw_sub in cast(dict[str, object], value).items():
            sub: object = raw_sub
            if isinstance(sub, dict):
                pair = cast(dict[str, object], sub)
                if "reference" in pair and "candidate" in pair:
                    if pair["reference"] == pair["candidate"]:
                        continue
                    parts.append(f"{key}: reference {_flat(pair['reference'])}, candidate {_flat(pair['candidate'])}")
                    continue
            text = describe_differences(cast(object, sub))
            if text:
                parts.append(f"{key}: {text}")
        return "; ".join(parts)
    return str(value)


def _flat(value: object) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{k} {_flat(v)}" for k, v in cast(dict[str, object], value).items())
    if isinstance(value, list):
        return ", ".join(_flat(v) for v in cast(list[object], value))
    return str(value)


class Candidate(BaseModel):
    id: str
    path: str
    prompt: str
    score: float
    round: int
    model: str


class Revision(BaseModel):
    differences: str
    prompt: str


class ImageAnalysis(BaseModel):
    id: str
    title: str
    source_path: str
    width: int
    height: int
    prompt: str = ""
    description: str = ""
    subjects: str = ""
    composition: str = ""
    colors: str = ""
    lighting: str = ""
    style: str = ""
    vision_model: str = ""
    image_model: str = ""
    confidence: float = 0.0
    candidates: list[Candidate] = Field(default_factory=list[Candidate])
    revisions: list[Revision] = Field(default_factory=list[Revision])
    best_candidate_id: str = ""


def _read_json(text: str) -> dict[str, Any]:
    try:
        payload: object = json.loads(text)
    except ValueError:
        # Some vision models surround the requested object with prose.
        start, end = text.find("{"), text.rfind("}")
        try:
            payload = json.loads(text[start:end + 1]) if start >= 0 and end > start else None
        except ValueError:
            payload = None
    return cast(dict[str, Any], payload) if isinstance(payload, dict) else {}


def _image_data_url(image: Image.Image) -> str:
    image = image.convert("RGB")
    image.thumbnail((1024, 1024))
    buf = BytesIO()
    image.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def score_images(reference: Image.Image, candidate: Image.Image) -> float:
    """Pixel/color + spatial-grid likeness in [0, 1]; scores are not calibrated."""
    ref = reference.convert("RGB").resize((256, 256), Image.Resampling.LANCZOS)
    comp = candidate.convert("RGB").resize((256, 256), Image.Resampling.LANCZOS)
    global_error = sum(ImageStat.Stat(ImageChops.difference(ref, comp)).mean) / (3 * 255)
    regions: list[float] = []
    for y in range(0, 256, 64):
        for x in range(0, 256, 64):
            box = (x, y, x + 64, y + 64)
            regions.append(sum(ImageStat.Stat(ImageChops.difference(ref.crop(box), comp.crop(box))).mean) / (3 * 255))
    return round(max(0.0, min(1.0, 1 - (global_error + sum(regions) / len(regions)) / 2)), 4)


class ImageRecreation:
    def __init__(self, root: Path, image_generation: Any, image_model: str) -> None:
        self.root = root
        self._image_generation = image_generation
        self.image_model = image_model

    def _dir(self, id: str) -> Path:
        if not id.startswith("ia-") or len(id) > 64 or not all(c.isalnum() or c == "-" for c in id):
            raise HTTPError(400, "Invalid image analysis ID")
        return self.root / id

    def _save(self, job: ImageAnalysis) -> ImageAnalysis:
        folder = self._dir(job.id)
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder / "analysis.json.tmp"
        temporary.write_text(job.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(folder / "analysis.json")
        return job

    def get(self, id: str) -> ImageAnalysis:
        doc = self._dir(id) / "analysis.json"
        if not doc.is_file():
            raise HTTPError(404, "Image analysis not found")
        try:
            return ImageAnalysis.model_validate_json(doc.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise HTTPError(500, "Image analysis could not be read") from exc

    def list(self) -> list[ImageAnalysis]:
        if not self.root.is_dir():
            return []
        jobs: list[ImageAnalysis] = []
        for folder in sorted(self.root.iterdir(), reverse=True):
            if folder.is_dir() and folder.name.startswith("ia-"):
                try:
                    jobs.append(self.get(folder.name))
                except HTTPError:
                    continue
        return jobs

    def import_image(self, raw_path: str) -> ImageAnalysis:
        try:
            path = require_absolute_file(raw_path, what="reference image", allowed_suffixes=SUPPORTED)
        except PathPolicyError as exc:
            raise HTTPError(400, str(exc)) from exc
        if path.stat().st_size > MAX_BYTES:
            raise HTTPError(400, "Reference exceeds the 20 MB limit")
        try:
            with Image.open(path) as image:
                if image.format != SUPPORTED[path.suffix.lower()]:
                    raise HTTPError(400, "Image contents do not match its extension")
                width, height = image.size
                if width * height > MAX_PIXELS or width < 16 or height < 16:
                    raise HTTPError(400, "Image dimensions must be at least 16px and under 32 megapixels")
                image.load()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise HTTPError(400, "Reference image cannot be decoded") from exc
        job = ImageAnalysis(id="ia-" + uuid.uuid4().hex[:12], title=path.stem,
                            source_path="reference" + path.suffix.lower(), width=width, height=height,
                            image_model=self.image_model)
        folder = self._dir(job.id)
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, folder / job.source_path)
        return self._save(job)

    def delete(self, id: str) -> None:
        self.get(id)
        shutil.rmtree(self._dir(id))

    def analyze(self, id: str, provider: LLMProvider | None) -> ImageAnalysis:
        job = self.get(id)
        if provider is None:
            raise HTTPError(400, "Connect a vision-capable AI Director in Settings to analyze images (qwen2.5vl:7b recommended).")
        with Image.open(self._dir(id) / job.source_path) as image:
            url = _image_data_url(image)
        instruction = ("You reverse-engineer an image into an evidence-only prompt for image generation. "
                       "Return JSON ONLY with string fields description, prompt, subjects, composition, colors, lighting, style "
                       "and numeric confidence (0-1). Describe subject count and positions, background, palette, lighting, "
                       "and visible details. Do not invent hidden details or claim exact reproduction. "
                       "Write prompt as a directly usable positive generation prompt, not a critique.")
        try:
            reply = provider.chat([LLMMessage(role="system", content=instruction),
                                   LLMMessage(role="user", content="Describe this reference accurately.", images=[url])],
                                  json_mode=True, timeout=180)
        except Exception as exc:
            raise HTTPError(502, f"Vision analysis failed: {exc}") from exc
        fields = _read_json(reply.text)
        prompt = fields.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise HTTPError(502, "Vision model did not return a usable image prompt")
        for key in ("prompt", "description", "subjects", "composition", "colors", "lighting", "style"):
            value = fields.get(key, "")
            text = value.strip() if isinstance(value, str) else "; ".join(str(v) for v in cast(list[object], value)) if isinstance(value, list) else ""
            setattr(job, key, text)
        conf = fields.get("confidence", 0)
        job.confidence = min(1.0, max(0.0, float(conf))) if isinstance(conf, (int, float)) and math.isfinite(float(conf)) else 0.0
        job.vision_model = provider.model
        return self._save(job)

    def edit_prompt(self, id: str, prompt: str) -> ImageAnalysis:
        if not prompt.strip():
            raise HTTPError(400, "Prompt cannot be empty")
        job = self.get(id)
        job.prompt = prompt.strip()
        return self._save(job)

    def _render(self, job: ImageAnalysis, prompt: str, count: int) -> ImageAnalysis:
        if not prompt.strip():
            raise HTTPError(400, "Analyze the reference first, or enter a prompt")
        # At most 1024 on the long edge, multiples of 16, preserving aspect ratio.
        scale = min(1.0, 1024 / max(job.width, job.height))
        width = max(64, round(job.width * scale / 16) * 16)
        height = max(64, round(job.height * scale / 16) * 16)
        from api_types import GenerateImageRequest
        result = self._image_generation.generate(GenerateImageRequest(prompt=prompt, width=width, height=height,
                                                                       numSteps=8, numImages=count))
        if result.status != "complete" or not result.image_paths:
            raise HTTPError(503, f"Image generation {result.status}; no candidate was produced")
        reference = self._dir(job.id) / job.source_path
        with Image.open(reference) as ref:
            for raw in result.image_paths[:count]:
                generated = Path(raw).resolve()
                # Only accept generator outputs from its configured output root.
                from server_utils.path_policy import is_within
                if (not is_within(self._image_generation._outputs_dir, generated)
                        or not generated.is_file() or generated.suffix.lower() not in SUPPORTED):
                    raise HTTPError(502, "Image generator returned an unreadable image")
                name = "candidate-" + uuid.uuid4().hex[:12] + generated.suffix.lower()
                dest = self._dir(job.id) / name
                shutil.copyfile(generated, dest)
                with Image.open(dest) as candidate:
                    score = score_images(ref, candidate)
                row = Candidate(id=name.rsplit(".", 1)[0], path=name, prompt=prompt,
                                score=score, round=1 + len(job.revisions), model=job.image_model)
                job.candidates.append(row)
                best = next((c for c in job.candidates if c.id == job.best_candidate_id), None)
                if best is None or row.score > best.score:
                    job.best_candidate_id = row.id
                self._save(job)
        return job

    def render(self, id: str, candidates: int = 2, rounds: int = 1, provider: LLMProvider | None = None) -> ImageAnalysis:
        job = self.get(id)
        if len(job.candidates) >= 9:
            raise HTTPError(400, "Candidate budget exhausted")
        job = self._render(job, job.prompt, min(candidates, 9 - len(job.candidates)))
        if rounds > 1:
            if provider is None:
                raise HTTPError(400, "Vision provider required for comparison and refinement")
            job = self.refine(id, candidates, provider)
        return job

    def refine(self, id: str, candidates: int, provider: LLMProvider | None) -> ImageAnalysis:
        job = self.get(id)
        if not job.best_candidate_id:
            raise HTTPError(400, "Render a candidate before refining")
        if len(job.candidates) + candidates > 9 or len(job.revisions) >= 2:
            raise HTTPError(400, "Refinement budget exhausted (two revisions, nine candidates)")
        if provider is None:
            raise HTTPError(400, "A vision provider is required for comparison")
        best = next(c for c in job.candidates if c.id == job.best_candidate_id)
        with Image.open(self._dir(id) / job.source_path) as ref, Image.open(self._dir(id) / best.path) as gen:
            images = [_image_data_url(ref), _image_data_url(gen)]
        instruction = ("Compare two images: image 1 is the reference and image 2 is a generated candidate. "
                       "Return JSON ONLY: differences (specific mismatches in object count/position, colors, lighting, "
                       "style and text) and revised_prompt (a better standalone positive generation prompt). "
                       "Do not assert that exact matching is guaranteed.")
        try:
            reply = provider.chat([LLMMessage(role="system", content=instruction),
                                   LLMMessage(role="user", content="Describe visible differences and revise the prompt.", images=images)],
                                  json_mode=True, timeout=180)
        except Exception as exc:
            raise HTTPError(502, f"Comparison failed: {exc}") from exc
        fields = _read_json(reply.text)
        differences = describe_differences(fields.get("differences"))
        raw_prompt = fields.get("revised_prompt")
        prompt = raw_prompt.strip() if isinstance(raw_prompt, str) else ""
        if not differences and not prompt:
            raise HTTPError(502, "Vision model did not return a discrepancy or revised prompt")
        if not prompt:
            # Small models often list differences but skip the rewrite; fold the
            # corrections into the current prompt so the next render uses them.
            prompt = f"{job.prompt} Corrections to match the reference: {differences}"
        job.revisions.append(Revision(differences=differences or "No specific differences reported", prompt=prompt))
        job.prompt = prompt
        self._save(job)
        return self._render(job, job.prompt, candidates)
