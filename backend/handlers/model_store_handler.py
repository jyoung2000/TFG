"""What AI models are on this computer, how much room they take, uninstalling
them, and where they are stored (user, 2026-10-04: "a place in settings where
they can easily see the local ai models installed, see how much allocation ...
change where ai models are stored, or uninstall ai models entirely").

Three storage areas hold every model file: WanGP's `ckpts` (checkpoints, text
encoders, VAEs), the app's `models` folder (Zero123++, face matching, native
LTX files) and the app's `loras` folder. A WanGP model owns the checkpoint files
its definition names; a file two installed models name is shared and counted
once; anything in `ckpts` no definition names (a text encoder folder, a VAE) is a
shared component. Moving an area moves its folder and leaves a directory
junction at the old path, so WanGP, the trainer and every stored path keep
working unchanged.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, Field

from _routes._errors import HTTPError

logger = logging.getLogger(__name__)

ModelKind = Literal["wangp", "component", "folder", "lora", "lora-file"]
AreaId = Literal["checkpoints", "models", "loras"]

#: Friendly names for folders in the app's models directory.
FOLDER_NAMES: dict[str, str] = {
    "zero123plus-v1.2": "Zero123++ v1.2 - object turnarounds (CC-BY-NC weights)",
    "face": "Face match - OpenCV SFace + YuNet",
    "ic-loras": "IC-LoRAs",
}
#: Friendly names for folders in WanGP's `ckpts` that no model json names.
COMPONENT_NAMES: dict[str, str] = {
    "training": "LoRA training weights (Z-Image)",
    "umt5-xxl": "UMT5-XXL text encoder (Wan)",
    "Qwen2.5-VL-7B-Instruct": "Qwen2.5-VL 7B text encoder (Qwen-Image)",
    "Qwen3": "Qwen3 text encoder (Z-Image)",
    "gemma-3-12b-it-qat-q4_0-unquantized": "Gemma 3 12B text encoder (LTX-2)",
    "xlm-roberta-large": "XLM-RoBERTa text encoder",
    "pose": "Pose detection (3D composer)",
    "depth": "Depth estimation",
    "rembg": "Background removal",
}
AREA_LABELS: dict[str, str] = {
    "checkpoints": "WanGP model checkpoints",
    "models": "App models (Zero123++, face match, LTX)",
    "loras": "LoRAs",
}


class InstalledModel(BaseModel):
    id: str
    name: str
    kind: ModelKind
    area: AreaId
    #: Bytes only this model uses (deleted by uninstall).
    size_bytes: int
    #: Bytes it shares with another installed model (kept by uninstall).
    shared_bytes: int = 0
    files: list[str] = Field(default_factory=list[str])
    note: str = ""


class StorageArea(BaseModel):
    id: AreaId
    label: str
    path: str
    size_bytes: int
    free_bytes: int
    #: Where the files really are when the area was moved (a junction); "" when not.
    moved_to: str = ""


class MoveStatus(BaseModel):
    area: str = ""
    destination: str = ""
    copied_bytes: int = 0
    total_bytes: int = 0
    running: bool = False
    error: str = ""


class InventoryResponse(BaseModel):
    models: list[InstalledModel]
    total_bytes: int
    areas: list[StorageArea]
    move: MoveStatus


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def _inside(child: Path, root: Path) -> bool:
    try:
        child.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return child.resolve() != root.resolve()


def _is_junction(path: Path) -> bool:
    check: Callable[[Path], bool] | None = getattr(os.path, "isjunction", None)
    return bool(check(path)) if check is not None else path.is_symlink()


class ModelStoreHandler:
    def __init__(
        self,
        *,
        checkpoints: Path | None,
        models_dir: Path,
        lora_root: Path,
        definitions: Callable[[], Sequence[Mapping[str, object]]],
        lora_registry: Callable[[], Iterable[Mapping[str, object]]],
        delete_lora: Callable[[str], object],
        busy: Callable[[], str],
        release_models: Callable[[], object] = lambda: None,
    ) -> None:
        self._areas: dict[str, Path] = {"models": models_dir, "loras": lora_root}
        if checkpoints is not None:
            self._areas = {"checkpoints": checkpoints, **self._areas}
        self._definitions = definitions
        self._lora_registry = lora_registry
        self._delete_lora = delete_lora
        self._busy = busy
        self._release_models = release_models
        self._lock = threading.Lock()
        self._move = MoveStatus()
        self._move_thread: threading.Thread | None = None

    # ---- what is installed --------------------------------------------------

    def _checkpoint_files(self) -> dict[str, list[Path]]:
        """Every file under `ckpts`, by file name (a name may sit in a subfolder)."""
        root = self._areas.get("checkpoints")
        index: dict[str, list[Path]] = {}
        if root is None or not root.is_dir():
            return index
        for path in root.rglob("*"):
            if path.is_file():
                index.setdefault(path.name, []).append(path)
        return index

    def _wangp_models(self) -> tuple[list[InstalledModel], set[Path]]:
        root = self._areas.get("checkpoints")
        if root is None:
            return [], set()
        index = self._checkpoint_files()
        claims: dict[str, list[Path]] = {}
        for definition in self._definitions():
            if not definition.get("installed"):
                continue
            raw = definition.get("urls")
            urls = [str(u) for u in cast(list[object], raw)] if isinstance(raw, list) else []
            files = [p for url in urls for p in index.get(url.rsplit("/", 1)[-1], [])]
            if files:
                claims[str(definition.get("id", ""))] = files
        users: dict[Path, int] = {}
        for files in claims.values():
            for path in set(files):
                users[path] = users.get(path, 0) + 1
        names = {str(d.get("id", "")): str(d.get("name", "") or d.get("id", "")) for d in self._definitions()}
        models: list[InstalledModel] = []
        for model_id, files in claims.items():
            unique = sorted(set(files))
            own = [p for p in unique if users[p] == 1]
            shared = [p for p in unique if users[p] > 1]
            models.append(InstalledModel(
                id=f"wangp:{model_id}", name=names.get(model_id, model_id), kind="wangp", area="checkpoints",
                size_bytes=sum(p.stat().st_size for p in own), shared_bytes=sum(p.stat().st_size for p in shared),
                files=[str(p.relative_to(root)) for p in unique],
                note="Shares files with another installed model" if shared else "",
            ))
        return models, set(users)

    def _components(self, claimed: set[Path]) -> list[InstalledModel]:
        """Top-level entries of `ckpts` no installed model names: text encoders, VAEs, helpers."""
        root = self._areas.get("checkpoints")
        if root is None or not root.is_dir():
            return []
        out: list[InstalledModel] = []
        for entry in sorted(root.iterdir()):
            if entry.name.startswith("."):
                continue  # caches and downloads in progress (Hugging Face's .cache) are not models
            if entry.is_file() and entry in claimed:
                continue
            if entry.is_dir() and any(_inside(p, entry) for p in claimed):
                continue
            size = _size(entry)
            if size == 0:
                continue
            out.append(InstalledModel(
                id=f"component:{entry.name}", name=COMPONENT_NAMES.get(entry.name, entry.name), kind="component", area="checkpoints", size_bytes=size,
                note="Shared component (text encoder, VAE or helper): models that need it download it again",
            ))
        return out

    def _folders(self) -> list[InstalledModel]:
        root = self._areas["models"]
        if not root.is_dir():
            return []
        out: list[InstalledModel] = []
        for entry in sorted(root.iterdir()):
            if entry.name.startswith("."):
                continue
            size = _size(entry)
            if size:
                out.append(InstalledModel(id=f"folder:{entry.name}", name=FOLDER_NAMES.get(entry.name, entry.name), kind="folder", area="models", size_bytes=size))
        return out

    def _loras(self) -> list[InstalledModel]:
        root = self._areas["loras"]
        out: list[InstalledModel] = []
        known: set[Path] = set()
        for entry in self._lora_registry():
            file = Path(str(entry.get("file", "")))
            if not file.is_file():
                continue
            known.add(file.resolve())
            out.append(InstalledModel(id=f"lora:{entry.get('id', '')}", name=str(entry.get("name", "") or file.stem), kind="lora", area="loras", size_bytes=file.stat().st_size, files=[file.name]))
        if root.is_dir():
            for file in sorted(root.rglob("*.safetensors")):
                if file.resolve() in known or "previews" in file.relative_to(root).parts:
                    continue
                relative = file.relative_to(root).as_posix()
                out.append(InstalledModel(id=f"lora-file:{relative}", name=file.stem, kind="lora-file", area="loras", size_bytes=file.stat().st_size, files=[relative]))
        return out

    def _storage(self) -> list[StorageArea]:
        out: list[StorageArea] = []
        for area_id, path in self._areas.items():
            real = Path(os.path.realpath(path)) if path.exists() else path
            probe = real if real.exists() else real.parent
            while not probe.exists() and probe != probe.parent:
                probe = probe.parent
            out.append(StorageArea(
                id=area_id,  # type: ignore[arg-type]
                label=AREA_LABELS[area_id], path=str(path), size_bytes=_size(real) if real.exists() else 0,
                free_bytes=shutil.disk_usage(probe).free, moved_to=str(real) if _is_junction(path) else "",
            ))
        return out

    def inventory(self) -> InventoryResponse:
        wangp, claimed = self._wangp_models()
        models = [*wangp, *self._components(claimed), *self._folders(), *self._loras()]
        shared_once = sum(p.stat().st_size for p in claimed if sum(1 for m in wangp if str(p.relative_to(self._areas["checkpoints"])) in m.files) > 1)
        total = sum(m.size_bytes for m in models) + shared_once
        with self._lock:
            move = self._move.model_copy()
        return InventoryResponse(models=sorted(models, key=lambda m: -(m.size_bytes + m.shared_bytes)), total_bytes=total, areas=self._storage(), move=move)

    # ---- uninstall ----------------------------------------------------------

    def _refuse_if_busy(self) -> None:
        reason = self._busy()
        if reason:
            raise HTTPError(409, f"{reason}: wait for it to finish first")
        with self._lock:
            if self._move.running:
                raise HTTPError(409, "Models are being moved: wait for it to finish first")

    def _child(self, area: str, relative: str) -> Path:
        root = self._areas.get(area)
        if root is None or not relative or relative.startswith("."):
            raise HTTPError(404, "No such model")
        path = root / relative
        if not _inside(path, root) or not path.exists():
            raise HTTPError(404, "No such model")
        return path

    def uninstall(self, model_id: str) -> InventoryResponse:
        """Delete a model's files entirely (a WanGP model keeps files another
        installed model shares). The WanGP worker lets go of models first."""
        kind, _, rest = model_id.partition(":")
        if kind not in ("wangp", "component", "folder", "lora", "lora-file") or not rest:
            raise HTTPError(404, f"No such model: {model_id}")
        self._refuse_if_busy()
        targets: list[Path] = []
        if kind == "wangp":
            model = next((m for m in self._wangp_models()[0] if m.id == model_id), None)
            if model is None:
                raise HTTPError(404, f"No such model: {model_id}")
            others = {f for m in self._wangp_models()[0] if m.id != model_id for f in m.files}
            targets = [self._child("checkpoints", f) for f in model.files if f not in others]
        elif kind == "component":
            targets = [self._child("checkpoints", rest)]
        elif kind == "folder":
            targets = [self._child("models", rest)]
        elif kind == "lora-file":
            targets = [self._child("loras", rest)]
        else:
            if not any(str(e.get("id", "")) == rest for e in self._lora_registry()):
                raise HTTPError(404, f"No such model: {model_id}")
            self._delete_lora(rest)
            return self.inventory()
        self._release_models()
        for path in targets:
            try:
                if path.is_dir() and not _is_junction(path):
                    shutil.rmtree(path)
                else:
                    path.unlink()
            except PermissionError as exc:
                raise HTTPError(409, f"{path.name} is in use (a model is loaded): close the app's renders and try again") from exc
        logger.info("Uninstalled %s (%d files)", model_id, len(targets))
        return self.inventory()

    # ---- where models are stored -------------------------------------------

    def move_area(self, area_id: str, destination: str) -> MoveStatus:
        """Move a storage area into `destination` and leave a junction at the old
        path. Same drive: a rename; another drive: a copy in the background."""
        if sys.platform != "win32":
            raise HTTPError(400, "Moving model folders is supported on Windows")
        path = self._areas.get(area_id)
        if path is None:
            raise HTTPError(404, f"No storage area {area_id}")
        self._refuse_if_busy()
        dest_root = Path(destination).expanduser()
        if not dest_root.is_absolute():
            raise HTTPError(400, "Choose an absolute folder")
        real = Path(os.path.realpath(path)) if path.exists() else path
        target = dest_root / path.name
        if dest_root.resolve() == real.resolve() or _inside(dest_root, real) or target.resolve() == real.resolve():
            raise HTTPError(400, "Choose a folder outside the one being moved")
        if target.exists() and any(target.iterdir()):
            raise HTTPError(409, f"{target} already exists and is not empty")
        dest_root.mkdir(parents=True, exist_ok=True)
        total = _size(real) if real.exists() else 0
        same_drive = os.path.splitdrive(str(real.resolve()))[0].lower() == os.path.splitdrive(str(dest_root.resolve()))[0].lower()
        if not same_drive and shutil.disk_usage(dest_root).free < total * 1.05:
            raise HTTPError(507, f"Not enough free space on {dest_root.anchor}: {total / 1e9:.1f} GB needed")
        self._release_models()
        with self._lock:
            self._move = MoveStatus(area=area_id, destination=str(target), total_bytes=total, running=True)
        thread = threading.Thread(target=self._run_move, args=(path, real, target, same_drive), name=f"move-{area_id}", daemon=True)
        self._move_thread = thread
        thread.start()
        with self._lock:
            return self._move.model_copy()

    def wait_for_move(self, timeout: float | None = None) -> MoveStatus:
        thread = self._move_thread
        if thread is not None:
            thread.join(timeout)
        with self._lock:
            return self._move.model_copy()

    def _run_move(self, path: Path, real: Path, target: Path, same_drive: bool) -> None:
        import _winapi  # type: ignore[import-not-found]  # Windows only, guarded by move_area

        try:
            if target.exists():
                target.rmdir()  # an empty folder of the same name
            if real.exists():
                if same_drive:
                    os.replace(real, target)
                else:
                    self._copy(real, target)
                    shutil.rmtree(real)
            else:
                target.mkdir(parents=True)
            if _is_junction(path):
                os.rmdir(path)  # removes the link, not the files
            path.parent.mkdir(parents=True, exist_ok=True)
            # Windows only (move_area refuses elsewhere): not in the typeshed stub for Linux.
            create_junction = cast(Callable[[str, str], None], getattr(_winapi, "CreateJunction"))
            create_junction(str(target), str(path))
            with self._lock:
                self._move.copied_bytes = self._move.total_bytes
        except Exception as exc:  # noqa: BLE001 - reported to the Settings screen
            logger.warning("Moving %s to %s failed: %s", path, target, exc)
            with self._lock:
                self._move.error = str(exc)
        finally:
            with self._lock:
                self._move.running = False

    def _copy(self, source: Path, target: Path) -> None:
        for root, _dirs, files in os.walk(source):
            rel = Path(root).relative_to(source)
            (target / rel).mkdir(parents=True, exist_ok=True)
            for name in files:
                shutil.copy2(Path(root) / name, target / rel / name)
                with self._lock:
                    self._move.copied_bytes += (target / rel / name).stat().st_size
