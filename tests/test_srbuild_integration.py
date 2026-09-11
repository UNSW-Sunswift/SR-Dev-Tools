###############################################################################
# Integration tests for srbuild CLI
# Author: Ryan Wong
#
# Made to run automatically on CI. Tests srbuild end to end by mocking a
# working directory and running the CLI commands. Uses pytest. Requires the
# sr_dev_tools package to be installed (editable install is fine).
# Uses fixtures from conftest.py to set up a temporary directory with the
# expected structure.
###############################################################################

import sys
import subprocess
from pathlib import Path

# =================================================================================================
# HELPER FUNCTIONS
# =================================================================================================
def run(*args: str, cwd: Path, stdin: str = "") -> subprocess.CompletedProcess:
    """Run srbuild CLI and return the CompletedProcess object."""
    return subprocess.run(
        [sys.executable, "-m", "sr_dev_tools.srbuild", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        input=stdin,
    )


def assert_success(r: subprocess.CompletedProcess) -> None:
    assert r.returncode == 0, f"Expected success.\nstdout: {r.stdout}\nstderr: {r.stderr}"


def assert_failure(r: subprocess.CompletedProcess) -> None:
    assert r.returncode != 0, f"Expected failure.\nstdout: {r.stdout}\nstderr: {r.stderr}"


# =================================================================================================
# SANITY CHECK TESTS
# =================================================================================================

def test_rejects_missing_cmake(repo: Path) -> None:
    """Must fail when CMakeLists.txt is missing."""
    r = run("all", "--linux", cwd=repo)
    assert_failure(r)

def test_accepts_valid_repo(configured_repo: Path) -> None:
    """Should pass all srbuild sanity checks with a fully configured repo."""
    # Have to add linux flag because we don't have a toolchain file
    r = run("all", "--linux", cwd=configured_repo)
    assert_success(r)

def test_fails_without_marker(tmp_path: Path) -> None:
    """No .sunswift-evsn marker anywhere: srbuild refuses to guess a root and errors out."""
    (tmp_path / "CMakeLists.txt").touch()
    r = run("all", "--linux", cwd=tmp_path)
    assert r.returncode != 0
    assert "sunswift-evsn" in r.stderr

def test_uses_marker_root_from_subdirectory(configured_repo: Path) -> None:
    """Running from a subdirectory of a marker-containing repo should resolve root correctly."""
    subdir = configured_repo / "some" / "nested" / "dir"
    subdir.mkdir(parents=True)
    r = run("all", "--linux", cwd=subdir)
    assert_success(r)
    assert (configured_repo / "build" / "linux").is_dir()


# =================================================================================================
# TARGET TESTS
# =================================================================================================

def test_target_requires_at_least_one(repo: Path) -> None:
    """srbuild target with no targets specified should fail."""
    r = run("target", "--linux", cwd=repo)
    assert_failure(r)

def test_target_accepts_single(configured_repo: Path) -> None:
    """srbuild target with one target should reach cmake and create a build directory."""
    run("target", "my_node", "--linux", cwd=configured_repo)
    assert (configured_repo / "build" / "linux").is_dir()

def test_target_accepts_multiple(configured_repo: Path) -> None:
    """srbuild target with multiple targets should reach cmake and create a build directory."""
    run("target", "node_a", "node_b", "--linux", cwd=configured_repo)
    assert (configured_repo / "build" / "linux").is_dir()


# =================================================================================================
# PLATFORM FLAG TESTS
# =================================================================================================

def test_all_accepts_linux_flag(configured_repo: Path) -> None:
    """--linux flag should be accepted and result in a successful build of an empty project."""
    r = run("all", "--linux", cwd=configured_repo)
    assert_success(r)

def test_all_requires_platform_flag(configured_repo: Path) -> None:
    """Neither --qnx nor --linux given should be rejected by argparse."""
    r = run("all", cwd=configured_repo)
    assert r.returncode == 2, f"expected argparse rejection\nstderr: {r.stderr}"

def test_all_accepts_qnx_with_toolchain_value(configured_repo: Path) -> None:
    """--qnx=<path> should be accepted by argparse; cmake will fail since the path doesn't exist."""
    r = run("all", "--qnx=cmake/qnx_toolchain.cmake", cwd=configured_repo)
    assert r.returncode != 2, f"argparse rejected --qnx=<path>\nstderr: {r.stderr}"

def test_all_rejects_bare_qnx_without_value(configured_repo: Path) -> None:
    """--qnx without a toolchain file value should be rejected by argparse."""
    r = run("all", "--qnx", cwd=configured_repo)
    assert r.returncode == 2, f"Expected argparse exit code 2\nstderr: {r.stderr}"

def test_qnx_and_linux_mutually_exclusive(configured_repo: Path) -> None:
    """--qnx and --linux together should be rejected by argparse."""
    r = run("all", "--qnx=cmake/qnx.cmake", "--linux", cwd=configured_repo)
    assert r.returncode == 2, f"Expected argparse exit code 2\nstderr: {r.stderr}"

def test_target_accepts_linux_flag(configured_repo: Path) -> None:
    """--linux flag should be accepted on the target subcommand and create a build directory."""
    run("target", "my_node", "--linux", cwd=configured_repo)
    assert (configured_repo / "build" / "linux").is_dir()

def test_all_accepts_jobs_flag(configured_repo: Path) -> None:
    """-j flag should be accepted and not cause an argparse error."""
    r = run("all", "--linux", "-j", "4", cwd=configured_repo)
    assert_success(r)

def test_all_rejects_invalid_jobs(configured_repo: Path) -> None:
    """-j with a non-integer value should be rejected by argparse."""
    r = run("all", "--linux", "-j", "fast", cwd=configured_repo)
    assert r.returncode == 2, f"Expected argparse exit code 2\nstderr: {r.stderr}"


# =================================================================================================
# UNKNOWN SUBCOMMAND TESTS
# =================================================================================================

def test_rejects_unknown_subcommand(configured_repo: Path) -> None:
    """An unrecognised subcommand should fail."""
    r = run("bogus", cwd=configured_repo)
    assert_failure(r)


# =================================================================================================
# CLEAN TESTS
# =================================================================================================

def test_clean_cancels_on_no(configured_repo: Path) -> None:
    """Answering 'n' to the clean prompt should cancel and leave build/ intact."""
    (configured_repo / "build" / "linux").mkdir(parents=True)
    (configured_repo / "build" / "qnx").mkdir(parents=True)
    r = run("clean", cwd=configured_repo, stdin="n\n")
    assert_failure(r)
    assert (configured_repo / "build").exists()

def test_clean_removes_build_dir(configured_repo: Path) -> None:
    """Answering 'y' should remove the entire build/ directory."""
    (configured_repo / "build" / "linux").mkdir(parents=True)
    (configured_repo / "build" / "qnx").mkdir(parents=True)
    r = run("clean", cwd=configured_repo, stdin="y\n")
    assert_success(r)
    assert not (configured_repo / "build").exists()

def test_clean_handles_missing_build(configured_repo: Path) -> None:
    """Clean should succeed gracefully when build/ does not exist."""
    r = run("clean", cwd=configured_repo, stdin="y\n")
    assert_success(r)
