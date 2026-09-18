import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cv.huggingface_tracker import HuggingFaceTracker


def test_raises_clean_error_without_transformers_installed():
    # transformers/torch aren't in this project's test dependencies (heavy,
    # optional) - so this exercises the real "not installed" path, same as
    # ball_tracker.py/roboflow_tracker.py's equivalent guards.
    with pytest.raises(RuntimeError, match="transformers and torch are required"):
        HuggingFaceTracker()
