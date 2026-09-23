import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cv.huggingface_tracker import HuggingFaceTracker


def test_raises_clean_error_without_transformers_installed(monkeypatch):
    # simulate the optional deps being absent (a None entry in sys.modules makes
    # the import raise ImportError), whether or not this machine has them
    monkeypatch.setitem(sys.modules, "transformers", None)
    with pytest.raises(RuntimeError, match="transformers and torch are required"):
        HuggingFaceTracker()


def test_importing_the_module_does_not_load_torch():
    assert "torch" not in dir(sys.modules["src.cv.huggingface_tracker"])
