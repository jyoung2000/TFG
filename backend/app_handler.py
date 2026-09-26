"""Application state composition root and dependency wiring."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from state.app_settings import AppSettings
from handlers import (
    DownloadHandler,
    FilmDirectorHandler,
    FilmGenerationHandler,
    FilmHandler,
    GenerationHandler,
    HealthHandler,
    IcLoraHandler,
    ModelLibraryHandler,
    ImageGenerationHandler,
    KnowledgeHandler,
    PromptHandler,
    ShotLibraryHandler,
    TimelineHandler,
    ModelsHandler,
    PipelinesHandler,
    SuggestGapPromptHandler,
    RetakeHandler,
    RuntimePolicyHandler,
    SettingsHandler,
    TextHandler,
    VideoAnalysisHandler,
    VideoGenerationHandler,
)
from film.media_runner import MediaRunner
from film.image_recreation import ImageRecreation
from handlers.jobs_handler import JobsHandler
from handlers.vision_handler import VisionHandler
from film.prompt_templates import TemplateStore
from handlers.reproduce_handler import ReproduceHandler
from handlers.video_reproduce_handler import VideoReproduceHandler
from handlers.scene_handler import SceneHandler
from handlers.training_handler import TrainingHandler
from handlers.wangp_server_handler import WanGPServerHandler
from services.lora_fetcher import LoraFetcher
from services.trainer.trainer import LoraTrainer
from services.vision.protocol import VisionService
from services.motion.motion_analyzer import MotionAnalyzer
from services.stitcher.video_stitcher import VideoStitcher
from services.vram.vram_manager import NvmlProbe, VramManager
from runtime_config.runtime_config import RuntimeConfig
from services.wangp_bridge import WanGPBridge
from services.media_probe import MediaProbe
from services.interfaces import (
    A2VPipeline,
    FastVideoPipeline,
    ZitAPIClient,
    ImageGenerationPipeline,
    GpuCleaner,
    GpuInfo,
    HTTPClient,
    IcLoraModelDownloader,
    IcLoraPipeline,
    LTXAPIClient,
    ModelDownloader,
    RetakePipeline,
    TaskRunner,
    TextEncoder,
    VideoProcessor,
)
from _routes._errors import HTTPError
from api_types import GenerateImageRequest, GenerateVideoRequest
from services.job_store.job_models import Job
from state.app_state_types import AppState, StartupPending, TextEncoderState


class AppHandler:
    """Composition-only state service exposing typed domain handlers."""

    def __init__(
        self,
        config: RuntimeConfig,
        default_settings: AppSettings,
        http: HTTPClient,
        gpu_cleaner: GpuCleaner,
        model_downloader: ModelDownloader,
        gpu_info: GpuInfo,
        video_processor: VideoProcessor,
        media_probe: MediaProbe,
        text_encoder: TextEncoder,
        task_runner: TaskRunner,
        ltx_api_client: LTXAPIClient,
        zit_api_client: ZitAPIClient,
        fast_video_pipeline_class: type[FastVideoPipeline],
        image_generation_pipeline_class: type[ImageGenerationPipeline],
        ic_lora_pipeline_class: type[IcLoraPipeline],
        a2v_pipeline_class: type[A2VPipeline],
        retake_pipeline_class: type[RetakePipeline],
        ic_lora_model_downloader: IcLoraModelDownloader,
        vision: VisionService | None = None,
        nvml: NvmlProbe | None = None,
        motion: MotionAnalyzer | None = None,
        stitcher: VideoStitcher | None = None,
        trainers: dict[str, LoraTrainer] | None = None,
        wangp_bridge: WanGPBridge | None = None,
        lora_fetcher: LoraFetcher | None = None,
    ) -> None:
        self.config = config

        # Exposed for tests and diagnostics.
        self.http = http
        self.gpu_cleaner = gpu_cleaner
        self.model_downloader = model_downloader
        self.gpu_info = gpu_info
        self.video_processor = video_processor
        self.media_probe = media_probe
        self.task_runner = task_runner
        self.ltx_api_client = ltx_api_client
        self.zit_api_client = zit_api_client
        self.fast_video_pipeline_class = fast_video_pipeline_class
        self.image_generation_pipeline_class = image_generation_pipeline_class
        self.ic_lora_pipeline_class = ic_lora_pipeline_class
        self.a2v_pipeline_class = a2v_pipeline_class
        self.retake_pipeline_class = retake_pipeline_class
        self.ic_lora_model_downloader = ic_lora_model_downloader
        if wangp_bridge is not None:
            self.wangp_bridge = wangp_bridge
        elif config.wangp_remote_url:
            from services.wangp_remote_bridge import RemoteWanGPBridge

            self.wangp_bridge = RemoteWanGPBridge(
                http=http,
                base_url=config.wangp_remote_url,
                token=config.wangp_remote_token,
                output_dir=config.outputs_dir,
                video_model_type=config.wangp_video_model_type,
                image_model_type=config.wangp_image_model_type,
                camera_motion_prompts=config.camera_motion_prompts,
            )
        else:
            self.wangp_bridge = WanGPBridge(
                enabled=config.wangp_enabled,
                root=config.wangp_root,
                python_executable=config.wangp_python,
                config_dir=config.wangp_config_dir,
                output_dir=config.outputs_dir,
                video_model_type=config.wangp_video_model_type,
                image_model_type=config.wangp_image_model_type,
                camera_motion_prompts=config.camera_motion_prompts,
                extra_args=config.wangp_extra_args,
            )

        self._lock = threading.RLock()

        self.state = AppState(
            available_files={
                "checkpoint": None,
                "upsampler": None,
                "text_encoder": None,
                "zit": None,
            },
            downloading_session=None,
            gpu_slot=None,
            api_generation=None,
            cpu_slot=None,
            text_encoder=TextEncoderState(service=text_encoder),
            startup=StartupPending(message="Not started"),
            app_settings=default_settings.model_copy(deep=True),
        )

        # ============================================================
        # Handlers (wired in dependency order)
        # ============================================================

        self.settings = SettingsHandler(
            state=self.state,
            lock=self._lock,
            settings_file=config.settings_file,
        )
        self.settings.load_settings(default_settings)

        # VRAM arbitration + the local vision stack. `vision` is injected by
        # tests (FakeVision); the real bundle leaves it None so the in-process
        # service can be built around this manager.
        app_data = config.settings_file.parent
        self.vram = VramManager(nvml if nvml is not None else _default_nvml(), http=http)
        # The render guard's per-model thresholds are settings-driven: apply
        # the loaded values now and again after every settings save.
        self.vram.set_overrides(self.state.app_settings.vram_render_needs_mb)
        self.settings.add_listener(lambda s: self.vram.set_overrides(s.vram_render_needs_mb))
        if vision is None:
            from services.vision.local_vision import LocalVision, VisionConfig

            vision = LocalVision(VisionConfig(cache_dir=app_data / "vision-cache" / "models"), self.vram)
        self.vision = VisionHandler(
            state=self.state,
            lock=self._lock,
            vision=vision,
            vram=self.vram,
            http=http,
            cache_dir=app_data / "vision-cache",
            outputs_dir=config.outputs_dir,
        )
        self.settings.add_listener(self.vision.apply_settings)

        # Motion (optical flow) and stitching are plain services: real ones by
        # default, fakes in tests. Neither touches the GPU.
        if motion is None:
            from services.motion.motion_analyzer import OpticalFlowAnalyzer

            motion = OpticalFlowAnalyzer()
        if stitcher is None:
            from services.stitcher.video_stitcher import FfmpegStitcher

            stitcher = FfmpegStitcher()
        self._motion = motion
        self._stitcher = stitcher
        #: Exposed for routes that encode media (Deliver).
        self.stitcher = stitcher
        if trainers is None:
            from pathlib import Path as _Path

            from services.trainer.subprocess_trainer import AiToolkitTrainer, MusubiTrainer

            backend_root = _Path(__file__).resolve().parent
            trainers = {"musubi": MusubiTrainer(backend_root), "ai-toolkit": AiToolkitTrainer(backend_root)}
        self._trainers = trainers
        if lora_fetcher is None:
            from services.lora_fetcher.requests_fetcher import RequestsLoraFetcher

            lora_fetcher = RequestsLoraFetcher()
        self._lora_fetcher = lora_fetcher

        # The unified job store: every handler below that does work reports
        # to it, and the History tab reads nothing else.
        self.jobs = JobsHandler(
            database=config.settings_file.parent / "jobs.sqlite",
            thumbs_dir=config.outputs_dir / "jobs" / "thumbs",
            outputs_dir=config.outputs_dir,
            probe=media_probe,
        )

        self.models = ModelsHandler(
            state=self.state,
            lock=self._lock,
            config=config,
            wangp_bridge=self.wangp_bridge,
        )

        self.downloads = DownloadHandler(
            state=self.state,
            lock=self._lock,
            models_handler=self.models,
            model_downloader=model_downloader,
            task_runner=task_runner,
            config=config,
            jobs=self.jobs,
        )

        self.text = TextHandler(
            state=self.state,
            lock=self._lock,
            config=config,
        )

        self.pipelines = PipelinesHandler(
            state=self.state,
            lock=self._lock,
            text_handler=self.text,
            gpu_cleaner=gpu_cleaner,
            fast_video_pipeline_class=fast_video_pipeline_class,
            image_generation_pipeline_class=image_generation_pipeline_class,
            ic_lora_pipeline_class=ic_lora_pipeline_class,
            a2v_pipeline_class=a2v_pipeline_class,
            retake_pipeline_class=retake_pipeline_class,
            config=config,
            outputs_dir=config.outputs_dir,
            device=config.device,
        )

        self.generation = GenerationHandler(state=self.state, lock=self._lock)
        self.generation.attach_jobs(self.jobs)

        self.video_generation = VideoGenerationHandler(
            state=self.state,
            lock=self._lock,
            generation_handler=self.generation,
            pipelines_handler=self.pipelines,
            text_handler=self.text,
            ltx_api_client=ltx_api_client,
            outputs_dir=config.outputs_dir,
            config=config,
            camera_motion_prompts=config.camera_motion_prompts,
            default_negative_prompt=config.default_negative_prompt,
            wangp_bridge=self.wangp_bridge,
            jobs=self.jobs,
            vision=self.vision,
            media_runner=MediaRunner(http),
        )

        self.image_generation = ImageGenerationHandler(
            state=self.state,
            lock=self._lock,
            generation_handler=self.generation,
            pipelines_handler=self.pipelines,
            outputs_dir=config.outputs_dir,
            config=config,
            zit_api_client=zit_api_client,
            wangp_bridge=self.wangp_bridge,
            jobs=self.jobs,
            vision=self.vision,
        )

        self.health = HealthHandler(
            state=self.state,
            lock=self._lock,
            models_handler=self.models,
            pipelines_handler=self.pipelines,
            gpu_info=gpu_info,
            config=config,
            use_sage_attention=config.use_sage_attention,
            wangp_bridge=self.wangp_bridge,
        )

        self.model_library = ModelLibraryHandler(
            state=self.state,
            lock=self._lock,
            config=config,
            wangp_bridge=self.wangp_bridge,
            http=http,
            gpu_info=gpu_info,
            task_runner=task_runner,
            model_downloader=model_downloader,
            jobs=self.jobs,
            vision=self.vision,
        )

        self.runtime_policy = RuntimePolicyHandler(config=config)

        self.suggest_gap_prompt = SuggestGapPromptHandler(
            state=self.state,
            lock=self._lock,
            http=http,
        )

        self.retake = RetakeHandler(
            state=self.state,
            lock=self._lock,
            ltx_api_client=ltx_api_client,
            config=config,
            generation_handler=self.generation,
            pipelines_handler=self.pipelines,
            text_handler=self.text,
            outputs_dir=config.outputs_dir,
            jobs=self.jobs,
        )

        self.ic_lora = IcLoraHandler(
            state=self.state,
            lock=self._lock,
            generation_handler=self.generation,
            pipelines_handler=self.pipelines,
            text_handler=self.text,
            video_processor=video_processor,
            ic_lora_model_downloader=ic_lora_model_downloader,
            ic_lora_dir=config.ic_lora_dir,
            outputs_dir=config.outputs_dir,
            jobs=self.jobs,
        )

        self.film = FilmHandler(
            state=self.state,
            lock=self._lock,
            film_root=config.outputs_dir / "film_projects",
        )

        self.knowledge = KnowledgeHandler(
            state=self.state,
            lock=self._lock,
            database=config.outputs_dir / "knowledge" / "knowledge.db",
        )

        self.video_analysis = VideoAnalysisHandler(
            state=self.state,
            lock=self._lock,
            root=config.outputs_dir / "video_analyses",
            probe=media_probe,
            task_runner=task_runner,
            film_store=self.film.store,
            jobs=self.jobs,
            vision=self.vision,
            motion=self._motion,
        )

        self.timeline = TimelineHandler(
            state=self.state,
            lock=self._lock,
            film_handler=self.film,
        )

        self.shot_library = ShotLibraryHandler(
            state=self.state,
            lock=self._lock,
            root=config.outputs_dir / "shot_library",
            film_handler=self.film,
        )

        self.prompts = PromptHandler(
            state=self.state,
            lock=self._lock,
            film_handler=self.film,
            analysis_store=self.video_analysis.store,
            templates=TemplateStore(config.settings_file.parent / "prompt_templates.json"),
            knowledge=self.knowledge,
        )

        self.film_generation = FilmGenerationHandler(
            state=self.state,
            lock=self._lock,
            film_handler=self.film,
            video_generation_handler=self.video_generation,
            generation_handler=self.generation,
            gpu_info=gpu_info,
            video_processor=video_processor,
            task_runner=task_runner,
            config=config,
            wangp_bridge=self.wangp_bridge,
            media_runner=MediaRunner(http),
            image_generation_handler=self.image_generation,
            jobs=self.jobs,
        )
        # The queue reports render outcomes to the knowledge engine; the film
        # handler reports what the user did with them.
        self.film_generation.attach_knowledge(self.knowledge)
        self.film.attach_knowledge(self.knowledge)

        self.film_director = FilmDirectorHandler(
            state=self.state,
            lock=self._lock,
            film_handler=self.film,
            film_generation_handler=self.film_generation,
            timeline_handler=self.timeline,
            http=http,
            video_processor=video_processor,
        )
        self.image_recreation = ImageRecreation(
            root=config.outputs_dir / "image_analyses",
            image_generation=self.image_generation,
            image_model=config.wangp_image_model_type if config.wangp_enabled else "Z-Image",
            jobs=self.jobs,
            vision=self.vision,
        )

        self.reproduce = ReproduceHandler(
            state=self.state,
            lock=self._lock,
            root=config.outputs_dir / "image_analyses",
            image_generation=self.image_generation,
            vision=self.vision,
            jobs=self.jobs,
            knowledge=self.knowledge,
            task_runner=task_runner,
            image_model=config.wangp_image_model_type if config.wangp_enabled else "Z-Image",
            wangp_enabled=config.wangp_enabled,
        )

        self.video_reproduce = VideoReproduceHandler(
            state=self.state,
            lock=self._lock,
            video_analysis=self.video_analysis,
            film_handler=self.film,
            film_generation=self.film_generation,
            probe=media_probe,
            motion=self._motion,
            stitcher=self._stitcher,
            task_runner=task_runner,
            config=config,
            jobs=self.jobs,
            vision=self.vision,
            knowledge=self.knowledge,
        )
        self.video_analysis.attach_reproduce(self.video_reproduce)
        self.training = TrainingHandler(
            state=self.state,
            lock=self._lock,
            app_data=app_data,
            trainers=self._trainers,
            lora_fetcher=self._lora_fetcher,
            task_runner=task_runner,
            probe=media_probe,
            vram=self.vram,
            jobs=self.jobs,
            vision=self.vision,
            reproduce_root=config.outputs_dir / "image_analyses",
            analysis_root=config.outputs_dir / "video_analyses",
        )
        self.film_generation.attach_training(self.training, self.vision)
        self.wangp_server = WanGPServerHandler(
            self.state,
            self._lock,
            bridge=self.wangp_bridge,
            outputs_dir=config.outputs_dir,
            task_runner=task_runner,
            jobs=self.jobs,
        )
        self.scene = SceneHandler(
            state=self.state,
            lock=self._lock,
            video_analysis=self.video_analysis,
            film=self.film,
            jobs=self.jobs,
        )

        # History controls: cancel and re-run per job kind. Film-queued shots
        # cancel through the queue; everything else through the single-slot
        # generation state machine.
        def _cancel_video(job: Job) -> bool:
            if job.project_id and job.shot_id:
                try:
                    self.film_generation.cancel_job(job.shot_id)
                    return True
                except HTTPError:
                    pass
            return self.generation.cancel_generation().status == "cancelling"

        def _cancel_generation(_: Job) -> bool:
            return self.generation.cancel_generation().status == "cancelling"

        def _cancel_download(job: Job) -> bool:
            # A LoRA-from-URL download carries its own cancel flag.
            if self.training.cancel_lora_download(job.id):
                return True
            status = self.model_library.download_status()
            if status.active:
                self.model_library.cancel_download()
                return True
            return False

        def _cancel_analysis(job: Job) -> bool:
            analysis_id = str(job.inputs.get("analysis_id", ""))
            if analysis_id:
                self.video_analysis.cancel(analysis_id)
                return True
            return False

        def _rerun_video(job: Job) -> None:
            self.video_generation.generate(GenerateVideoRequest.model_validate(job.params), job_id=job.id, seed=job.seed)

        def _rerun_image(job: Job) -> None:
            self.image_generation.generate(GenerateImageRequest.model_validate(job.params), job_id=job.id, seed=job.seed)

        self.jobs.register_canceller("video_gen", _cancel_video)
        self.jobs.register_canceller("image_gen", _cancel_generation)
        def _cancel_reproduce(job: Job) -> bool:
            analysis_id = str(job.inputs.get("analysis_id", ""))
            if analysis_id:
                try:
                    self.reproduce.cancel(analysis_id)
                    return True
                except HTTPError:
                    pass
            return _cancel_generation(job)

        self.jobs.register_canceller("image_reproduce", _cancel_reproduce)
        def _cancel_video_reproduce(job: Job) -> bool:
            analysis_id = str(job.inputs.get("analysis_id", ""))
            if analysis_id:
                try:
                    self.video_reproduce.cancel(analysis_id)
                    return True
                except HTTPError:
                    pass
            return _cancel_generation(job)

        self.jobs.register_canceller("video_reproduce", _cancel_video_reproduce)

        def _cancel_training(job: Job) -> bool:
            run_id = str(job.inputs.get("run_id", ""))
            if run_id:
                try:
                    self.training.cancel(run_id)
                    return True
                except HTTPError:
                    pass
            return False

        self.jobs.register_canceller("training", _cancel_training)
        self.jobs.register_canceller("download", _cancel_download)
        self.jobs.register_canceller("analysis", _cancel_analysis)
        self.jobs.register_rerunner("video_gen", _rerun_video)
        self.jobs.register_rerunner("image_gen", _rerun_image)

        self.downloads.cleanup_downloading_dir()
        self.models.refresh_available_files()
        self.jobs.recover_interrupted()
        self.film_generation.recover_interrupted_jobs()


@dataclass
class ServiceBundle:
    http: HTTPClient
    gpu_cleaner: GpuCleaner
    model_downloader: ModelDownloader
    gpu_info: GpuInfo
    video_processor: VideoProcessor
    media_probe: MediaProbe
    text_encoder: TextEncoder
    task_runner: TaskRunner
    ltx_api_client: LTXAPIClient
    zit_api_client: ZitAPIClient
    fast_video_pipeline_class: type[FastVideoPipeline]
    image_generation_pipeline_class: type[ImageGenerationPipeline]
    ic_lora_pipeline_class: type[IcLoraPipeline]
    a2v_pipeline_class: type[A2VPipeline]
    retake_pipeline_class: type[RetakePipeline]
    ic_lora_model_downloader: IcLoraModelDownloader
    #: None → the in-process LocalVision is built by AppHandler; tests inject FakeVision.
    vision: VisionService | None = None
    #: None → pynvml; tests inject FakeNvml.
    nvml: NvmlProbe | None = None
    #: None → OpenCV Farneback over PyAV frames; tests inject FakeMotion.
    motion: MotionAnalyzer | None = None
    #: None → ffmpeg concat (imageio-ffmpeg / TFG_FFMPEG); tests inject FakeStitcher.
    stitcher: VideoStitcher | None = None
    #: None → subprocess trainers (musubi-tuner, ai-toolkit); tests inject FakeTrainer.
    trainers: dict[str, LoraTrainer] | None = None
    #: None → the local WanGP bridge, or the remote one when `config.wangp_remote_url` is set; tests inject FakeWanGPBridge.
    wangp_bridge: WanGPBridge | None = None
    #: None → requests-based Hugging Face/Civitai fetcher; tests inject FakeLoraFetcher.
    lora_fetcher: LoraFetcher | None = None


def _default_nvml() -> NvmlProbe:
    from services.vram.vram_manager import PynvmlProbe

    return PynvmlProbe()


def _default_vision(http: HTTPClient) -> VisionService | None:
    """The sidecar when `TFG_VISION_URL` points at a running worker, else None
    (→ in-process). See docs/adr/0001-local-vision-stack.md."""
    import os

    url = os.environ.get("TFG_VISION_URL", "").strip()
    if not url:
        return None
    from services.vision.remote_vision import RemoteVision

    remote = RemoteVision(http, url)
    if remote.reachable():
        return remote
    import logging

    logging.getLogger(__name__).warning("TFG_VISION_URL=%s is not reachable; using the in-process vision stack", url)
    return None


def build_default_service_bundle(config: RuntimeConfig) -> ServiceBundle:
    """Build real runtime services with lazy heavy imports isolated from tests."""
    from services.fast_video_pipeline.ltx_fast_video_pipeline import LTXFastVideoPipeline
    from services.zit_api_client.zit_api_client_impl import ZitAPIClientImpl
    from services.gpu_cleaner.torch_cleaner import TorchCleaner
    from services.gpu_info.gpu_info_impl import GpuInfoImpl
    from services.http_client.http_client_impl import HTTPClientImpl
    from services.ic_lora_model_downloader.ic_lora_model_downloader_impl import IcLoraModelDownloaderImpl
    from services.a2v_pipeline.ltx_a2v_pipeline import LTXa2vPipeline
    from services.ic_lora_pipeline.ltx_ic_lora_pipeline import LTXIcLoraPipeline
    from services.image_generation_pipeline.zit_image_generation_pipeline import ZitImageGenerationPipeline
    from services.ltx_api_client.ltx_api_client_impl import LTXAPIClientImpl
    from services.model_downloader.hugging_face_downloader import HuggingFaceDownloader
    from services.retake_pipeline.ltx_retake_pipeline import LTXRetakePipeline
    from services.task_runner.threading_runner import ThreadingRunner
    from services.text_encoder.ltx_text_encoder import LTXTextEncoder
    from services.media_probe.media_probe_impl import MediaProbeImpl
    from services.video_processor.video_processor_impl import VideoProcessorImpl

    http = HTTPClientImpl()

    return ServiceBundle(
        http=http,
        gpu_cleaner=TorchCleaner(device=config.device),
        model_downloader=HuggingFaceDownloader(),
        gpu_info=GpuInfoImpl(),
        video_processor=VideoProcessorImpl(),
        media_probe=MediaProbeImpl(),
        text_encoder=LTXTextEncoder(
            device=config.device,
            http=http,
            ltx_api_base_url=config.ltx_api_base_url,
        ),
        task_runner=ThreadingRunner(),
        ltx_api_client=LTXAPIClientImpl(http=http, ltx_api_base_url=config.ltx_api_base_url),
        zit_api_client=ZitAPIClientImpl(http=http),
        fast_video_pipeline_class=LTXFastVideoPipeline,
        image_generation_pipeline_class=ZitImageGenerationPipeline,
        ic_lora_pipeline_class=LTXIcLoraPipeline,
        a2v_pipeline_class=LTXa2vPipeline,
        retake_pipeline_class=LTXRetakePipeline,
        ic_lora_model_downloader=IcLoraModelDownloaderImpl(),
        vision=_default_vision(http),
    )


def build_initial_state(
    config: RuntimeConfig,
    default_settings: AppSettings,
    service_bundle: ServiceBundle | None = None,
) -> AppHandler:
    bundle = service_bundle or build_default_service_bundle(config)

    return AppHandler(
        config=config,
        default_settings=default_settings,
        http=bundle.http,
        gpu_cleaner=bundle.gpu_cleaner,
        model_downloader=bundle.model_downloader,
        gpu_info=bundle.gpu_info,
        video_processor=bundle.video_processor,
        media_probe=bundle.media_probe,
        text_encoder=bundle.text_encoder,
        task_runner=bundle.task_runner,
        ltx_api_client=bundle.ltx_api_client,
        zit_api_client=bundle.zit_api_client,
        fast_video_pipeline_class=bundle.fast_video_pipeline_class,
        image_generation_pipeline_class=bundle.image_generation_pipeline_class,
        ic_lora_pipeline_class=bundle.ic_lora_pipeline_class,
        a2v_pipeline_class=bundle.a2v_pipeline_class,
        retake_pipeline_class=bundle.retake_pipeline_class,
        ic_lora_model_downloader=bundle.ic_lora_model_downloader,
        vision=bundle.vision,
        nvml=bundle.nvml,
        motion=bundle.motion,
        stitcher=bundle.stitcher,
        trainers=bundle.trainers,
        wangp_bridge=bundle.wangp_bridge,
        lora_fetcher=bundle.lora_fetcher,
    )
