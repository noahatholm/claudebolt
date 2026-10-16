import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
_tmp = tempfile.mkdtemp(prefix="cbolt_test_")
os.environ["CLAUDEBOLT_CACHE"] = str(Path(_tmp) / "cache")
os.environ["CLAUDEBOLT_CONFIG"] = str(Path(_tmp) / "config")

import make_fixtures


@pytest.fixture(scope="session")
def fx() -> Path:
    return make_fixtures.make()


@pytest.fixture
def media(fx, tmp_path):
    """Copy fixtures into tmp_path so project files never pollute the shared folder."""
    import shutil

    d = tmp_path / "media"
    shutil.copytree(fx, d)
    return d
