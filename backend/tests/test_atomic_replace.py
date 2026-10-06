"""Atomic document writes must survive a concurrent reader on Windows.

Every store here writes `<doc>.tmp` and then `Path.replace`s the real file.
On Windows that replace fails with `PermissionError: [WinError 5] Access is
denied` while any other handle has the target open - and the documents are
read constantly: Video Reproduce's `_wait` loads `project.json` every 0.25 s
while the film queue renders, and the UI polls `reproduce.json` /
`analysis.json`. MEASURED in the installed app (session log 23:44:35): the
film queue's `_finish_version` hit exactly this, the exception ended the
queue thread, the version stayed "generating" forever, and the reproduce
loop waited on it forever.
"""

from __future__ import annotations

import threading
from pathlib import Path

from film.film_models import FilmProject
from film.film_store import FilmStore


def _hold_open(path: Path, seconds: float) -> threading.Timer:
    """Keep `path` open for reading like a polling reader, then release it."""
    handle = path.open("rb")
    timer = threading.Timer(seconds, handle.close)
    timer.start()
    return timer


def test_film_store_save_waits_out_a_concurrent_reader(tmp_path: Path) -> None:
    store = FilmStore(tmp_path / "film_projects")
    project = FilmProject(id="film-abc123def456", name="before")
    store.save(project)
    reader = _hold_open(store._project_file(project.id), 0.4)  # noqa: SLF001 - the file the queue saves
    project.name = "after"
    store.save(project)
    reader.join()
    assert store.load(project.id).name == "after"


def test_replace_with_retry_gives_up_with_the_original_error(tmp_path: Path) -> None:
    import pytest

    from server_utils.atomic_file import replace_with_retry

    target = tmp_path / "doc.json"
    target.write_text("old")
    tmp = tmp_path / "doc.json.tmp"
    tmp.write_text("new")
    calls: list[int] = []

    def always_denied(src: Path, dst: Path) -> None:
        calls.append(1)
        raise PermissionError(5, "Access is denied")

    with pytest.raises(PermissionError):
        replace_with_retry(tmp, target, timeout_s=0.2, _replace=always_denied)
    assert len(calls) > 1, "it retried before giving up"
    assert target.read_text() == "old"
