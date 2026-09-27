"""Drive WanGP's shared.api directly — the F-038 isolation oracle.

Reconstruction of the round-2 diagnostic (`HermesRound2/diagnostics/
direct_render.py`, local to the audit machine) that rendered 5/5 on the
RTX 4070 while every render through the app failed: it proves the model
stack independently of the backend, the worker and the launcher. The
manifest keys here are exactly what `backend/services/wangp_bridge.py`
builds, so a divergence between this script and the app isolates the fault
to the worker/launcher layer, never the models.

Run it INSIDE the WanGP environment, from the checkout:

  cd <Wan2GP root>
  .venv/Scripts/python.exe <repo>/scripts/wangp_direct_render.py \
      --root . --output-dir out --mode image --prompt "a rain-soaked neon alley, cinematic"

Take the idle `nvidia-smi` baseline IMMEDIATELY before each run; report
peak minus that baseline, never a session-global number.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def build_manifest(args: argparse.Namespace) -> list[dict[str, object]]:
    params: dict[str, object] = {
        "prompt": args.prompt,
        "resolution": args.resolution,
        "num_inference_steps": args.steps,
        "seed": args.seed,
    }
    if args.mode == "image":
        params["model_type"] = args.image_model_type
        params["num_images"] = 1
    else:
        params["model_type"] = args.video_model_type
        params["video_length"] = args.frames
        params["force_fps"] = args.fps
        if args.video_model_type.startswith("ltx2_"):
            params["sliding_window_size"] = args.frames
        if args.mode == "i2v":
            if not args.image:
                raise SystemExit("--image is required for --mode i2v")
            params["image_prompt_type"] = "S"
            params["image_start"] = str(Path(args.image).resolve())
    return [{"id": 1, "params": params, "plugin_data": {}}]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Wan2GP checkout (the folder with wgp.py)")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--mode", choices=("image", "t2v", "i2v"), default="image")
    parser.add_argument("--prompt", default="a rain-soaked neon alley, cinematic")
    parser.add_argument("--image", default="", help="start frame for --mode i2v")
    parser.add_argument("--resolution", default="", help="e.g. 1024x1024 (image) or 768x512 (video)")
    parser.add_argument("--frames", type=int, default=49)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--image-model-type", default="z_image")
    parser.add_argument("--video-model-type", default="ltx2_22B_distilled")
    args = parser.parse_args()
    if not args.resolution:
        args.resolution = "1024x1024" if args.mode == "image" else "768x512"

    root = Path(args.root).resolve()
    if not (root / "shared" / "api.py").exists():
        raise SystemExit(f"{root} does not look like a Wan2GP checkout (no shared/api.py)")
    sys.path.insert(0, str(root))
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    print(f"[direct] importing shared.api from {root} ...", flush=True)
    from shared.api import WanGPSession  # noqa: PLC0415 - after sys.path setup

    print(f"[direct] import done in {time.monotonic() - started:.1f}s", flush=True)
    session = WanGPSession(root=root, config_path=root / "wgp_config.json", output_dir=output_dir, cli_args=())
    manifest = build_manifest(args)
    print(f"[direct] manifest: {json.dumps(manifest)}", flush=True)
    job = session.submit_manifest(manifest)
    while True:
        event = job.events.get(timeout=0.5)
        if event is not None:
            kind = getattr(event, "kind", "")
            data = getattr(event, "data", None)
            if kind in ("status", "info", "error"):
                print(f"[wangp {kind}] {data}", flush=True)
            elif kind == "progress":
                print(f"[wangp progress] {getattr(data, 'phase', '?')} {getattr(data, 'progress', '?')}%", flush=True)
        if job.done and event is None:
            break
    result = job.result()
    wall = time.monotonic() - started
    if not result.success:
        print(f"[direct] FAILED after {wall:.1f}s", flush=True)
        return 1
    for path in result.generated_files:
        print(f"[direct] output: {path}", flush=True)
    print(f"[direct] done in {wall:.1f}s (includes import)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
