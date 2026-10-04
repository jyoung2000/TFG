"""Image generation orchestration handler."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from threading import RLock
from collections.abc import Sequence
from typing import TYPE_CHECKING

from PIL import Image

from _routes._errors import HTTPError
from api_types import GenerateImageRequest, GenerateImageResponse
from handlers.base import StateHandlerBase
from handlers.jobs_handler import JobsHandler
from handlers.vision_handler import VisionHandler
from handlers.generation_handler import GenerationHandler
from handlers.pipelines_handler import PipelinesHandler
from services.interfaces import ZitAPIClient
from services.wangp_bridge import IMG2IMG_MODEL_TYPES, REFERENCE_IMAGE_MODEL_TYPES, WanGPBridge
from state.app_state_types import AppState

if TYPE_CHECKING:
    from runtime_config.runtime_config import RuntimeConfig

logger = logging.getLogger(__name__)

# CUDA error detection — shared with video_generation_handler.py
_CUDA_ERRORS = (
    "cudaErrorAlreadyMapped",
    "CUDA error: an illegal memory access",
    "CUDA error: unknown error",
    "driver shutting down",
    "context is destroyed",
)

def _is_cuda_context_error(text: str) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in _CUDA_ERRORS)



#: F-034 bounds: 16-multiple sides between these are honest work; anything
#: outside is a typo or an attack on the card, refused before CUDA sees it.
_MIN_DIM = 64
_MAX_DIM = 4096


class ImageGenerationHandler(StateHandlerBase):
    def __init__(
        self,
        state: AppState,
        lock: RLock,
        generation_handler: GenerationHandler,
        pipelines_handler: PipelinesHandler,
        outputs_dir: Path,
        config: RuntimeConfig,
        zit_api_client: ZitAPIClient,
        wangp_bridge: WanGPBridge,
        jobs: JobsHandler | None = None,
        vision: VisionHandler | None = None,
    ) -> None:
        super().__init__(state, lock)
        self._jobs = jobs
        self._vision = vision
        self._generation = generation_handler
        self._pipelines = pipelines_handler
        self._outputs_dir = outputs_dir
        self._config = config
        self._zit_api_client = zit_api_client
        self._wangp_bridge = wangp_bridge

    def generate(
        self,
        req: GenerateImageRequest,
        *,
        job_id: str | None = None,
        seed: int | None = None,
        init_image: Path | None = None,
        denoise_strength: float = 1.0,
        reference_images: Sequence[str] = (),
        reference_mode: str = "KI",
        record: bool = True,
    ) -> GenerateImageResponse:
        """Render images. `job_id` reuses an existing History job; `seed` pins the seed (re-runs).

        `reference_images` compose the render from ordered images (FLUX.2 -
        see `reference_model`): "KI" = scene first, then people; "I" = people.

        `init_image` + `denoise_strength` < 1 render img2img from that image
        (WanGP FLUX.2 only - see `img2img_model`)."""
        if self._generation.is_generation_running():
            raise HTTPError(409, "Generation already in progress")
        # F-034: bound dimensions before any pipeline or CUDA work — 99999²
        # used to reach the card and come back as a raw 500 CUDA OOM.
        for side, value in (("width", req.width), ("height", req.height)):
            if not (_MIN_DIM <= value <= _MAX_DIM):
                raise HTTPError(400, f"{side} must be between {_MIN_DIM} and {_MAX_DIM} pixels (got {value})")
        # `record=False`: a throwaway render (a live preview) leaves no History job.
        tracked = self._open_job(req, job_id, seed) if record else ""
        peak_mb: int | None = None
        try:
            if self._vision is not None:
                # The model this render actually uses ("Render with"), not the
                # configured default: FLUX.2 and Z-Image need different room.
                model_type = ((req.model or "").strip() or self._config.wangp_image_model_type) if self._config.wangp_enabled else "z_image"
                held = self._wangp_bridge.held_vram_mb() if self._config.wangp_enabled else 0
                with self._vision.render_scope(model_type, reclaimable_mb=held) as scope:
                    response = self._dispatch(req, tracked, seed, init_image, denoise_strength, tuple(reference_images), reference_mode)
                peak_mb = scope.peak_mb
            else:
                response = self._dispatch(req, tracked, seed, init_image, denoise_strength, tuple(reference_images), reference_mode)
        except HTTPError as exc:
            self._close_job(tracked, error=str(exc.detail))
            raise
        except Exception as exc:
            self._close_job(tracked, error=str(exc))
            raise
        if peak_mb is not None and tracked and self._jobs is not None:
            self._jobs.annotate(tracked, metrics={"peak_vram_mb": peak_mb})
        self._close_job(tracked, response=response)
        return response

    def img2img_model(self, preferred: str = "") -> str | None:
        """The installed model that can render from a reference image.

        `preferred` wins when it can; otherwise the first img2img-capable
        model whose weights are on disk. None when there is none - the local
        Z-Image pipeline and WanGP's Z-Image have no partial-denoise path."""
        if not self._config.wangp_enabled:
            return None
        preferred = preferred.strip() or self._config.wangp_image_model_type
        if self._wangp_bridge.supports_img2img(preferred) and self._wangp_bridge.weights_installed(preferred) is not False:
            return preferred
        return next((m for m in IMG2IMG_MODEL_TYPES if self._wangp_bridge.weights_installed(m) is True), None)

    def model_installed(self, model_type: str) -> bool:
        """Whether WanGP is on and the model's weights are on disk."""
        return self._config.wangp_enabled and self._wangp_bridge.weights_installed(model_type) is True

    def reference_model(self, preferred: str = "") -> str | None:
        """The installed model that composes from reference images (FLUX.2),
        `preferred` first. None when WanGP is off or none is installed."""
        if not self._config.wangp_enabled:
            return None
        preferred = preferred.strip() or self._config.wangp_image_model_type
        if preferred in REFERENCE_IMAGE_MODEL_TYPES and self._wangp_bridge.weights_installed(preferred) is not False:
            return preferred
        return next((m for m in REFERENCE_IMAGE_MODEL_TYPES if self._wangp_bridge.weights_installed(m) is True), None)

    def cancel_current(self) -> None:
        """Cancel whatever image generation is running (used by the Reproduce loop)."""
        self._generation.cancel_generation()

    def edit(self, req: GenerateImageRequest, *, reference: Image.Image, mask_png: bytes) -> GenerateImageResponse:
        """Edit `reference` inside `mask_png` with the edit-capable WanGP image model.

        The exact WanGP keys for reference images and masks depend on the
        checkout (`wgp.py` / `shared/api.py`) and could not be verified in
        this build; the bridge method raises with a clear message until they
        are confirmed (see session-notes VF-008).
        """
        if not self._config.wangp_enabled:
            raise HTTPError(400, "Image editing needs the WanGP edit model (Qwen-Image-Edit / Flux Kontext)")
        del reference, mask_png
        raise HTTPError(501, "Image editing with WanGP is not wired yet: the reference/mask parameter names must be confirmed against the local checkout")

    def _open_job(self, req: GenerateImageRequest, job_id: str | None, seed: int | None) -> str:
        if self._jobs is None:
            return ""
        if self._config.wangp_enabled:
            provider, model = "wangp", self._config.wangp_image_model_type
        elif self._config.force_api_generations:
            provider, model = "ltx-api", "z-image"
        else:
            provider, model = "local", "z-image"
        params = req.model_dump()
        if job_id:
            self._jobs.annotate(job_id, model=model, provider=provider, prompt=req.prompt, params=params, seed=seed)
            self._jobs.mark_running(job_id, phase="starting")
            return job_id
        return self._jobs.start(
            "image_gen", title=req.prompt[:80], model=model, provider=provider, seed=seed, prompt=req.prompt, params=params
        ).id

    def _close_job(self, job_id: str, *, response: GenerateImageResponse | None = None, error: str = "") -> None:
        if not job_id or self._jobs is None:
            return
        if response is None:
            self._jobs.fail(job_id, error or "Image generation failed")
        elif response.status == "complete" and response.image_paths:
            self._jobs.complete(job_id, list(response.image_paths))
        elif response.status == "cancelled":
            self._jobs.mark_cancelled(job_id)
        else:
            self._jobs.fail(job_id, f"Image generation ended with status {response.status}")

    def _note_seed(self, job_id: str, seed: int) -> None:
        if job_id and self._jobs is not None:
            self._jobs.annotate(job_id, seed=seed)

    def _dispatch(
        self, req: GenerateImageRequest, job_id: str, seed_override: int | None,
        init_image: Path | None = None, denoise_strength: float = 1.0,
        reference_images: tuple[str, ...] = (), reference_mode: str = "KI",
    ) -> GenerateImageResponse:
        if self._config.wangp_enabled:
            return self._generate_via_wangp(
                req, job_id=job_id, seed_override=seed_override, init_image=init_image, denoise_strength=denoise_strength,
                reference_images=reference_images, reference_mode=reference_mode,
            )
        if reference_images:
            raise HTTPError(400, "Composing from reference images needs WanGP with FLUX.2 installed")
        if init_image is not None:
            raise HTTPError(400, "Rendering from a reference image needs WanGP with FLUX.2 installed")

        if self._generation.is_generation_running():
            raise HTTPError(409, "Generation already in progress")

        width = (req.width // 16) * 16
        height = (req.height // 16) * 16
        num_images = max(1, min(12, req.numImages))

        generation_id = uuid.uuid4().hex[:8]
        settings = self.state.app_settings.model_copy(deep=True)
        if seed_override is not None:
            seed = seed_override
        elif settings.seed_locked:
            seed = settings.locked_seed
            logger.info("Using locked seed for image: %s", seed)
        else:
            seed = int(time.time()) % 2147483647
        self._note_seed(job_id, seed)

        if self._config.force_api_generations:
            return self._generate_via_api(
                prompt=req.prompt,
                width=width,
                height=height,
                num_inference_steps=req.numSteps,
                seed=seed,
                num_images=num_images,
            )

        try:
            self._pipelines.load_zit_to_gpu()
            self._generation.start_generation(generation_id, job_id=job_id)
            output_paths = self.generate_image(
                prompt=req.prompt,
                width=width,
                height=height,
                num_inference_steps=req.numSteps,
                seed=seed,
                num_images=num_images,
            )
            self._generation.complete_generation(output_paths)
            return GenerateImageResponse(status="complete", image_paths=output_paths)
        except Exception as e:
            if self._generation.is_generation_cancelled() or "cancelled" in str(e).lower():
                # A cancelled run must surface with a Cancelled state, not an error:
                # align the state machine with the response so the frontend polling
                # loop never sees a cancelled job as failed.
                self._generation.cancel_generation()
                logger.info("Image generation cancelled by user")
                return GenerateImageResponse(status="cancelled")

            self._generation.fail_generation(str(e))
            raise HTTPError(500, str(e)) from e

    def _generate_via_wangp(
        self, req: GenerateImageRequest, *, job_id: str = "", seed_override: int | None = None,
        init_image: Path | None = None, denoise_strength: float = 1.0,
        reference_images: tuple[str, ...] = (), reference_mode: str = "KI",
    ) -> GenerateImageResponse:
        if self._generation.is_generation_running():
            raise HTTPError(409, "Generation already in progress")

        # Same rule as video: missing weights are an explicit Models-tab
        # download, never a silent side effect of a render (wgp.py would
        # otherwise auto-download the checkpoint on load).
        # "Render with" - a request may name its own model; an empty name keeps
        # the backend's configured default.
        model_type = (req.model or "").strip() or self._config.wangp_image_model_type
        if self._wangp_bridge.weights_installed(model_type) is False:
            raise HTTPError(
                409,
                f"The local image model '{model_type}' has no downloaded weights yet. "
                "Download it first in the Models tab (Model Library → Local · WanGP models) — "
                "a render never starts a checkpoint download on its own.",
            )

        width = (req.width // 16) * 16
        height = (req.height // 16) * 16
        num_images = max(1, min(12, req.numImages))

        generation_id = uuid.uuid4().hex[:8]
        settings = self.state.app_settings.model_copy(deep=True)
        if seed_override is not None:
            seed = seed_override
        else:
            seed = settings.locked_seed if settings.seed_locked else int(time.time()) % 2147483647
        self._note_seed(job_id, seed)

        try:
            self._generation.start_api_generation(generation_id, job_id=job_id)
            output_paths = self._wangp_bridge.generate_images(
                prompt=req.prompt,
                width=width,
                height=height,
                num_steps=req.numSteps,
                num_images=num_images,
                seed=seed,
                on_progress=self._generation.update_progress,
                is_cancelled=self._generation.is_generation_cancelled,
                loras=[(lora.name, lora.multiplier) for lora in req.loras if Path(lora.name).is_file()],
                model_type=model_type,
                init_image=str(init_image) if init_image is not None else None,
                denoise_strength=denoise_strength,
                reference_images=reference_images,
                reference_mode=reference_mode,
            )
            self._generation.complete_generation(output_paths)
            return GenerateImageResponse(status="complete", image_paths=output_paths)
        except Exception as e:
            if self._generation.is_generation_cancelled() or "cancelled" in str(e).lower():
                self._generation.cancel_generation()
                logger.info("WanGP image generation cancelled by user")
                return GenerateImageResponse(status="cancelled")

            # CUDA-context errors from a stale worker: restart once and retry once.
            error_text = str(e)
            if _is_cuda_context_error(error_text):
                logger.warning("CUDA context error detected, restarting WanGP worker: %s", error_text[:120])
                stop_fn = getattr(self._wangp_bridge, "stop", None)
                if stop_fn is not None:
                    stop_fn()
                try:
                    return self._generate_via_wangp(req, job_id=job_id, seed_override=seed_override, init_image=init_image, denoise_strength=denoise_strength)
                except Exception as retry_e:
                    if self._generation.is_generation_cancelled() or "cancelled" in str(retry_e).lower():
                        self._generation.cancel_generation()
                        return GenerateImageResponse(status="cancelled")
                    self._generation.fail_generation(str(retry_e))
                    raise HTTPError(500, f"CUDA error after worker restart: {retry_e}") from retry_e

            self._generation.fail_generation(str(e))
            raise HTTPError(500, str(e)) from e



    def generate_image(
        self,
        prompt: str,
        width: int,
        height: int,
        num_inference_steps: int,
        seed: int | None,
        num_images: int,
    ) -> list[str]:
        if self._generation.is_generation_cancelled():
            raise RuntimeError("Generation was cancelled")

        self._generation.update_progress("loading_model", 5, 0, num_inference_steps)
        zit = self._pipelines.load_zit_to_gpu()
        self._generation.update_progress("inference", 15, 0, num_inference_steps)

        if seed is None:
            seed = int(time.time()) % 2147483647

        outputs: list[str] = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        for i in range(num_images):
            if self._generation.is_generation_cancelled():
                raise RuntimeError("Generation was cancelled")

            progress = 15 + int((i / num_images) * 80)
            self._generation.update_progress("inference", progress, i, num_images)

            result = zit.generate(
                prompt=prompt,
                height=height,
                width=width,
                guidance_scale=0.0,
                num_inference_steps=num_inference_steps,
                seed=seed + i,
            )

            output_path = self._outputs_dir / f"zit_image_{timestamp}_{uuid.uuid4().hex[:8]}.png"
            result.images[0].save(str(output_path))
            outputs.append(str(output_path))

        if self._generation.is_generation_cancelled():
            raise RuntimeError("Generation was cancelled")

        self._generation.update_progress("complete", 100, num_images, num_images)
        return outputs

    def _generate_via_api(
        self,
        *,
        prompt: str,
        width: int,
        height: int,
        num_inference_steps: int,
        seed: int,
        num_images: int,
    ) -> GenerateImageResponse:
        generation_id = uuid.uuid4().hex[:8]
        output_paths: list[Path] = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        settings = self.state.app_settings.model_copy(deep=True)

        try:
            self._generation.start_api_generation(generation_id)
            self._generation.update_progress("validating_request", 5, None, None)

            if not settings.fal_api_key.strip():
                raise HTTPError(500, "FAL_API_KEY_NOT_CONFIGURED")

            for idx in range(num_images):
                if self._generation.is_generation_cancelled():
                    raise RuntimeError("Generation was cancelled")

                inference_progress = 15 + int((idx / num_images) * 60)
                self._generation.update_progress("inference", inference_progress, None, None)
                image_bytes = self._zit_api_client.generate_text_to_image(
                    api_key=settings.fal_api_key,
                    prompt=prompt,
                    width=width,
                    height=height,
                    seed=seed + idx,
                    num_inference_steps=num_inference_steps,
                )

                if self._generation.is_generation_cancelled():
                    raise RuntimeError("Generation was cancelled")

                download_progress = 75 + int(((idx + 1) / num_images) * 20)
                self._generation.update_progress("downloading_output", download_progress, None, None)

                output_path = self._outputs_dir / f"zit_api_image_{timestamp}_{uuid.uuid4().hex[:8]}.png"
                output_path.write_bytes(image_bytes)
                output_paths.append(output_path)

            self._generation.update_progress("complete", 100, None, None)
            self._generation.complete_generation([str(path) for path in output_paths])
            return GenerateImageResponse(status="complete", image_paths=[str(path) for path in output_paths])
        except HTTPError as e:
            self._generation.fail_generation(e.detail)
            raise
        except Exception as e:
            if self._generation.is_generation_cancelled() or "cancelled" in str(e).lower():
                # A cancelled run must surface with a Cancelled state, not an error:
                # align the state machine with the response so the frontend polling
                # loop never sees a cancelled job as failed.
                self._generation.cancel_generation()
                for path in output_paths:
                    path.unlink(missing_ok=True)
                logger.info("Image generation cancelled by user")
                return GenerateImageResponse(status="cancelled")
            self._generation.fail_generation(str(e))
            raise HTTPError(500, str(e)) from e
