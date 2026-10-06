"""Round 3, F-040: a corrupt opencv install must fail loudly at startup,
not as 57 pyright errors and AttributeErrors mid-export."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.video_processor.cv2_check import check_cv2_module, verify_cv2


class TestCv2Integrity:
    def test_namespace_package_shape_is_named(self):
        # A namespace package has no __file__ — round 2's exact corruption.
        broken = SimpleNamespace(__file__=None)
        problem = check_cv2_module(broken)
        assert "namespace package" in problem and "Repair:" in problem

    def test_missing_symbols_are_named(self):
        half_broken = SimpleNamespace(__file__="/site-packages/cv2/__init__.py", imread=lambda *a: None)
        problem = check_cv2_module(half_broken)
        assert "VideoWriter" in problem and "VideoCapture" in problem and "Repair:" in problem

    def test_a_real_install_passes(self):
        good = SimpleNamespace(__file__="/x/cv2/__init__.py", VideoWriter=object, VideoCapture=object, imread=object)
        assert check_cv2_module(good) == ""

    def test_this_environment_has_a_working_cv2(self):
        """The gate itself: the venv the tests run in must hold a real cv2
        (cv2.__file__ set, VideoWriter present), or exports are broken."""
        verify_cv2()

    def test_pyproject_pins_an_upper_bound(self):
        from pathlib import Path

        pyproject = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")
        line = next(line for line in pyproject.splitlines() if "opencv-python-headless" in line)
        assert "<" in line, f"unbounded opencv pin lets a broken future wheel in silently: {line}"


def test_verify_raises_a_runtime_error_shape():
    # Sanity on the raising wrapper against the pure checker's contract.
    with pytest.raises(RuntimeError, match="Repair:"):
        raise RuntimeError(check_cv2_module(SimpleNamespace(__file__=None)))
