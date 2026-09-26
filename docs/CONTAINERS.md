# Containers, remote backend, Unraid

`deploy/docker-compose.yml` runs TFG's backend where the GPU is — a NAS, a
workstation, a rented box — and the desktop app (or any MCP agent) talks to
it over the network.

| Service | Image | Port | Role |
|---|---|---|---|
| `backend` | `deploy/backend.Dockerfile` (CUDA 12.8 runtime, Python 3.12, WanGP cloned at build) | 8000 | the whole API: Create, Reproduce, Train, History, film queue, `/mcp` |
| `vision` | same image, `vision_worker.py` | 8765 (internal) | Florence-2, CLIP, Depth-Anything, DINOv2 in their own env |
| `ollama` | `ollama/ollama` (profile `vlm`) | 11434 | optional VLM, `qwen2.5vl:3b` pulled on first start, `keep_alive 0` |

Everything persistent lives on two volumes: `tfg-data` (`/data`: models,
outputs, settings.json, training datasets, LoRA registry, History) and
`wangp-ckpts` (WanGP's weights).

## Bring it up

```bash
cp deploy/.env.example deploy/.env      # set LTX_AUTH_TOKEN
docker compose -f deploy/docker-compose.yml up -d --build
# optional VLM
docker compose -f deploy/docker-compose.yml --profile vlm up -d
curl -H "Authorization: Bearer $LTX_AUTH_TOKEN" http://localhost:8000/health
```

Requirements: an NVIDIA driver with the container toolkit (`nvidia-smi`
works on the host, `docker info` lists the `nvidia` runtime). The first
`up` builds the image (WanGP + two Python envs, ~10 GB of wheels) and the
first renders download weights into the volumes.

`pnpm deploy:config` validates the compose file without a daemon.

**Verified in this session:** the compose file parses (`docker compose
config`) and the Dockerfile follows the same `uv` steps the dev setup
scripts use. Building the image and passing `/health` inside a container
needs a Docker daemon and an NVIDIA GPU, which the authoring environment
did not have — recorded as *BLOCKED — ENVIRONMENT* in
`docs/RTX_4070_TEST_MATRIX.md`, together with the desktop-to-stack
connection test.

## Connect the desktop

Settings → General → **Remote backend**: URL (`http://<host>:8000`) and the
token from `deploy/.env`, *Test connection* (shows the GPU the stack sees),
*Use this backend*. The app stops its local Python process, every request
goes to the remote, and media comes through the authenticated
`/api/film/output` route rather than `file://` (which cannot reach another
machine). *Back to this computer* restarts the local backend.

What still needs the local machine: picking files with the OS dialog gives
*local* paths; a remote backend cannot read them. Reproduce/Train imports
that take a path therefore need files that live on the backend host (drop
them on the `tfg-data` volume or a mounted share), or use the History /
analysis imports that reference the backend's own outputs.

## Drive only the WanGP inside

The desktop can keep running its own backend and hand just the WanGP
renders to the container:

```
WANGP_REMOTE_URL=http://unraid.local:8000
WANGP_REMOTE_TOKEN=<LTX_AUTH_TOKEN>
```

set in the backend's environment before it starts. `services/wangp_remote_bridge.py`
then replaces the in-process bridge: every setting is built exactly as for
a local WanGP (same resolution maps, LoRA keys, guide videos), the files
the render needs are uploaded, the manifest runs on the container
(`/api/wangp/*`, `handlers/wangp_server_handler.py`) and the outputs are
downloaded into the local outputs folder. The concept follows
Open-Generative-AI's "Wan2GP as a remote server" (MIT); the transport is
this project's own API so it stays testable with fakes
(`backend/tests/test_wangp_remote.py`).

## Agents against the stack

`POST http://<host>:8000/mcp` is the MCP endpoint; see `docs/AGENTS_GUIDE.md`
and `skills/tfg/SKILL.md` for Hermes / Claude Code / Cursor configuration.

## Unraid

1. Install the **Nvidia-Driver** plugin (Community Applications) and confirm
   `nvidia-smi` in the Unraid terminal.
2. Install **Compose Manager** (Community Applications) or use the Docker
   CLI over SSH.
3. Put this repo (or just `deploy/`) on the array, e.g.
   `/mnt/user/appdata/tfg/`, copy `deploy/.env.example` to `deploy/.env`
   and set the token.
4. In Compose Manager: *Add New Stack* → point it at
   `/mnt/user/appdata/tfg/deploy/docker-compose.yml` → *Compose Up*.
   To keep models on the array instead of Docker's image volume, replace
   the `tfg-data` volume with a bind mount:
   `- /mnt/user/appdata/tfg/data:/data`.
5. The backend answers on `http://<unraid-ip>:8000`; the desktop's Remote
   backend card and the MCP URL use that address.

Unraid's `/mnt/user` shares are slower than a cache pool for the weights;
put `/data/models` and `wangp-ckpts` on the cache when possible.

## Docker Desktop on Windows: "The file cannot be accessed by the system"

> Seen and resolved on the reference 4070 machine (2026-09-26); the notes
> below stay for the next time an unclean shutdown leaves the sockets behind.

If Docker Desktop (4.77–4.90) refuses to start with

```
starting services: initializing Ingest server: listening on
unix://C:/Users/<you>/AppData/Local/Docker/run/sailor-ingest.sock:
rename …sailor-ingest.sock …sailor-ingest.sock.stale:
The file cannot be accessed by the system.
```

it is a known crash loop after an unclean exit: the 0-byte AF_UNIX socket
reparse points under `%LOCALAPPDATA%\Docker\run` (and
`%LOCALAPPDATA%\docker-secrets-engine`) are held by the kernel and cannot be
renamed or deleted until a reboot — Docker's own recovery fails on exactly
that rename. A **factory reset is not needed**: moving the directory aside
works even when the file cannot be touched, and Docker recreates it.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\docker-desktop-repair.ps1
```

stops the Docker processes, moves the two folders to `*.stale-<timestamp>`,
restarts Docker Desktop and prints the folders to delete afterwards. If the
move itself is refused, reboot once and run it again. Images, containers,
volumes and WSL distros are untouched. References:
[docker/for-win#15063](https://github.com/docker/for-win/issues/15063),
[docker/desktop-feedback#676](https://github.com/docker/desktop-feedback/issues/676),
[#692](https://github.com/docker/desktop-feedback/issues/692),
[#460](https://github.com/docker/desktop-feedback/issues/460),
[#554](https://github.com/docker/desktop-feedback/issues/554).

Docker Desktop on Windows runs this stack through WSL 2 with GPU
passthrough (`wsl --update`, an NVIDIA driver with WSL support). It is a
fine way to try the stack on the same PC; on the 4070 itself the desktop
app's built-in local backend is the faster path.
