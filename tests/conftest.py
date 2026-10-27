### This file contains pytest fixtures for the srhigh tests.
import pytest
from pathlib import Path

@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Directory with a .sunswift-evsn marker, discoverable as a build/package root."""
    (tmp_path / ".sunswift-evsn").touch()
    return tmp_path

@pytest.fixture
def configured_repo(repo: Path) -> Path:
    """Repo that passes all srhigh build sanity checks (has CMakeLists.txt)."""
    (repo / "CMakeLists.txt").touch()
    return repo
