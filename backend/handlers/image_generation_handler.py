"""Image generation orchestration handler."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from threading import RLock
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
from services.wangp_bridge import WanGPBridge
from state.app_state_types import AppState

if TYPE_CHECKING:
    from runtime_config.runtime_config import RuntimeConfig

logger = logging.getLogger(__name__)


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
    ) -> GenerateImageResponse:
        """Render images. `job_id` reuses an existing History job; `seed` pins the seed (re-runs)."""
        if self._generation.is_generation_running():
            raise HTTPError(409, "Generation already in progress")
        tracked = self._open_job(req, job_id, seed)
        peak_mb: int | None = None
        try:
            if self._vision is not None:
                model_type = self._config.wangp_image_model_type if self._config.wangp_enabled else "z_image"
                with self._vision.render_scope(model_type) as scope:
                    response = self._dispatch(req, tracked, seed)
                peak_mb = scope.peak_mb
            else:
                response = self._dispatch(req, tracked, seed)
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

    def _dispatch(self, req: GenerateImageRequest, job_id: str, seed_override: int | None) -> GenerateImageResponse:
        if self._config.wangp_enabled:
            return self._generate_via_wangp(req, job_id=job_id, seed_override=seed_override)

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
        self, req: GenerateImageRequest, *, job_id: str = "", seed_override: int | None = None
    ) -> GenerateImageResponse:
        if self._generation.is_generation_running():
            raise HTTPError(409, "Generation already in progress")

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
            )
            self._generation.complete_generation(output_paths)
            return GenerateImageResponse(status="complete", image_paths=output_paths)
        except Exception as e:
            if self._generation.is_generation_cancelled() or "cancelled" in str(e).lower():
                # A cancelled run must surface with a Cancelled state, not an error:
                # align the state machine with the response so the frontend polling
                # loop never sees a cancelled job as failed.
                self._generation.cancel_generation()
                logger.info("WanGP image generation cancelled by user")
                return GenerateImageResponse(status="cancelled")

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
