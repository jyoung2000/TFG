# TFG backend + WanGP bridge + vision sidecar, one image (docs/CONTAINERS.md).
#
# Base: NVIDIA's CUDA 12.8 runtime on Ubuntu 24.04. Python 3.12 for the
# backend venv (pyproject pins) and a second venv for the vision worker so the
# WanGP checkout's transformers pin never fights Florence-2's.
#
# ffmpeg comes from Ubuntu's package (LGPL build of the libraries the app
# links; the binary is used as a subprocess only). No GPL ffmpeg binary is
# added to the repo.

FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG WANGP_REF=main
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu128

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3.12 python3.12-venv python3.12-dev git ffmpeg curl ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/*

# uv drives both venvs exactly like the dev setup scripts do.
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# ---- WanGP (deepbeepmeep/Wan2GP, Apache-2.0) — not vendored, cloned at build ----
RUN git clone --depth 1 --branch "${WANGP_REF}" https://github.com/deepbeepmeep/Wan2GP.git /opt/Wan2GP
RUN uv venv /opt/Wan2GP/.venv --python 3.12 \
    && uv pip install --python /opt/Wan2GP/.venv/bin/python --index-url "${TORCH_INDEX}" torch torchvision torchaudio \
    && uv pip install --python /opt/Wan2GP/.venv/bin/python -r /opt/Wan2GP/requirements.txt

# ---- backend ----
WORKDIR /app/backend
# The lock pins every wheel (torch from the cu128 index, ltx-core/ltx-pipelines
# from their git revisions) exactly as `pnpm setup:dev:*` does on a workstation.
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ /app/backend/
RUN uv sync --frozen --no-dev

# ---- vision sidecar env (backend/vision-requirements.txt) ----
RUN uv venv /opt/venv-vision --python 3.12 \
    && uv pip install --python /opt/venv-vision/bin/python --index-url "${TORCH_INDEX}" torch torchvision \
    && uv pip install --python /opt/venv-vision/bin/python -r /app/backend/vision-requirements.txt

ENV LTX_HOST=0.0.0.0 \
    LTX_PORT=8000 \
    LTX_APP_DATA_DIR=/data \
    WANGP_ROOT=/opt/Wan2GP \
    WANGP_PYTHON=/opt/Wan2GP/.venv/bin/python \
    PYTHONUNBUFFERED=1

VOLUME ["/data", "/opt/Wan2GP/ckpts"]
EXPOSE 8000 8765

CMD ["/opt/venv/bin/python", "ltx2_server.py"]
