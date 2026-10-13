###############################################################################
# Integration tests for srhigh pkg CLI
# Author: Ryan Wong
#
# Made to run automatically on CI. Tests srhigh pkg end to end by mocking a working
# directory and running the CLI commands. Uses pytest. Requires the
# sr_dev_tools package to be installed (editable install is fine).
###############################################################################

import sys
import subprocess
import os
from pathlib import Path

# =================================================================================================
# HELPER FUNCTIONS
# =================================================================================================
def run(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    """Run `srhigh pkg <args>` and return the CompletedProcess object."""
    env = os.environ.copy()
    result = subprocess.run(
        [sys.executable, "-m", "sr_dev_tools.srhigh", "pkg", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env
    )
    return result


# =================================================================================================
# TESTS
# =================================================================================================

### srhigh pkg create tests
def test_create_basic(tmp_path: Path) -> None:
    """Create package called my_node in CWD and verify creation"""
    r = run("create", "my_node", cwd=tmp_path)
    assert r.returncode == 0

    pkg = tmp_path / "my_node"
    assert (pkg / ".srpkg").exists()
    assert (pkg / "src").is_dir()
    assert (pkg / "src" / "main.cpp").exists()
    assert (pkg / "include").is_dir()
    assert (pkg / "param").is_dir()
    assert (pkg / "test").is_dir()
    assert (pkg / "param" / "my_node_param.toml").exists()
    assert (pkg / "CMakeLists.txt").exists()
    assert (pkg / "README.md").exists()

def test_create_cmakelists_has_no_external_function_dependency(tmp_path: Path) -> None:
    """Generated CMakeLists.txt should use plain install(), not sr_install_node."""
    run("create", "my_node", cwd=tmp_path)
    text = (tmp_path / "my_node" / "CMakeLists.txt").read_text()
    assert "sr_install_node" not in text
    assert "install(" in text

def test_create_rejects_local_duplicate(tmp_path: Path) -> None:
    """Creating a package that already exists as a directory in CWD should fail."""
    run("create", "my_node", cwd=tmp_path)
    r = run("create", "my_node", cwd=tmp_path)
    assert r.returncode != 0

def test_create_allows_duplicate_name_elsewhere(tmp_path: Path) -> None:
    """No repo-wide crawl: a same-named package in a different directory is not a conflict."""
    sub = tmp_path / "subsystem"
    sub.mkdir()
    run("create", "my_node", cwd=sub)

    r = run("create", "my_node", cwd=tmp_path)
    assert r.returncode == 0

def test_create_works_outside_any_repo(tmp_path: Path) -> None:
    """No .sunswift-evsn marker or src/ requirement: create just works in any CWD."""
    r = run("create", "my_node", cwd=tmp_path)
    assert r.returncode == 0

def test_create_rejects_bad_name(tmp_path: Path) -> None:
    for bad in ["MyNode", "my-node", "my node", "my.node"]:
        r = run("create", bad, cwd=tmp_path)
        assert r.returncode != 0, f"Expected failure for name: {bad}"
