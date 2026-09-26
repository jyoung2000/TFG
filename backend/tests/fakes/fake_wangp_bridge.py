"""A WanGP bridge that never imports the checkout: builds settings exactly
like the real one and "renders" by writing a small file per manifest."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from services.wangp_bridge import CancelledCallback, ProgressCallback, WanGPBridge, WanGPBridgeStatus


class FakeWanGPBridge(WanGPBridge):
    def __init__(self, output_dir: Path) -> None:
        super().__init__(
            enabled=True,
            root=None,
            python_executable=None,
            config_dir=output_dir / "wangp_fake",
            output_dir=output_dir,
            video_model_type="ltx2_22B_distilled",
            image_model_type="z_image",
            camera_motion_prompts={},
            extra_args=(),
        )
        self.available = False
        self.reason = "fake WanGP is switched off"
        self.manifests: list[list[dict[str, object]]] = []
        self.fail_with: str = ""
        self.definitions: list[dict[str, object]] = [{"id": "ltx2_22B_distilled", "name": "LTX-2 22B distilled", "downloaded": True}]
        self._serial = 0

    def get_status(self) -> WanGPBridgeStatus:
        if not self.available:
            return WanGPBridgeStatus(available=False, root=None, python_executable=None, reason=self.reason)
        return WanGPBridgeStatus(available=True, root=None, python_executable=None)

    def list_model_definitions(self) -> list[dict[str, object]]:
        return list(self.definitions)

    def weights_installed(self, model_type: str) -> bool | None:
        """The real bridge answers None without a checkout; the fake answers
        from its `definitions` so tests can simulate missing weights."""
        for definition in self.definitions:
            if str(definition.get("id", "")) == model_type:
                value = definition.get("installed", definition.get("downloaded"))
                return None if value is None else bool(value)
        return None

    def _run_manifest(self, *, manifest: list[dict[str, object]], media_suffixes: set[str], on_progress: ProgressCallback, is_cancelled: CancelledCallback) -> list[str]:  # type: ignore[override]
        self.manifests.append(manifest)
        on_progress("starting_wangp", 2, None, None)
        if self.fail_with:
            raise RuntimeError(self.fail_with)
        if is_cancelled():
            raise RuntimeError("Generation was cancelled")
        on_progress("inference", 50, None, None)
        self._serial += 1
        self._output_dir.mkdir(parents=True, exist_ok=True)
        if ".mp4" in media_suffixes:
            out = self._output_dir / f"wangp-fake-{self._serial}.mp4"
            out.write_bytes(b"\x00\x00\x00\x18ftypmp42fake-wangp-render")
        else:
            out = self._output_dir / f"wangp-fake-{self._serial}.png"
            Image.new("RGB", (64, 64), (20, 200, 120)).save(out)
        on_progress("complete", 100, None, None)
        return [str(out)]
