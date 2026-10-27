###############################################################################
# Integration tests for srhigh build CLI
# Author: Ryan Wong
#
# Made to run automatically on CI. Tests srhigh build end to end by mocking a
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
    """Run `srhigh build <args>` and return the CompletedProcess object."""
    return subprocess.run(
        [sys.executable, "-m", "sr_dev_tools.srhigh", "build", *args],
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
    r = run("all", "--linux64", cwd=repo)
    assert_failure(r)

def test_accepts_valid_repo(configured_repo: Path) -> None:
    """Should pass all srhigh build sanity checks with a fully configured repo."""
    r = run("all", "--linux64", cwd=configured_repo)
    assert_success(r)

def test_fails_without_marker(tmp_path: Path) -> None:
    """No .sunswift-evsn marker anywhere: srhigh build refuses to guess a root and errors out."""
    (tmp_path / "CMakeLists.txt").touch()
    r = run("all", "--linux64", cwd=tmp_path)
    assert r.returncode != 0
    assert "sunswift-evsn" in r.stderr

def test_uses_marker_root_from_subdirectory(configured_repo: Path) -> None:
    """Running from a subdirectory of a marker-containing repo should resolve root correctly."""
    subdir = configured_repo / "some" / "nested" / "dir"
    subdir.mkdir(parents=True)
    r = run("all", "--linux64", cwd=subdir)
    assert_success(r)
    assert (configured_repo / "build" / "linux64").is_dir()


# =================================================================================================
# TARGET TESTS
# =================================================================================================

def test_target_requires_at_least_one(repo: Path) -> None:
    """srhigh build target with no targets specified should fail."""
    r = run("target", "--linux64", cwd=repo)
    assert_failure(r)

def test_target_accepts_single(configured_repo: Path) -> None:
    """srhigh build target with one target should reach cmake and create a build directory."""
    run("target", "my_node", "--linux64", cwd=configured_repo)
    assert (configured_repo / "build" / "linux64").is_dir()

def test_target_accepts_multiple(configured_repo: Path) -> None:
    """srhigh build target with multiple targets should reach cmake and create a build directory."""
    run("target", "node_a", "node_b", "--linux64", cwd=configured_repo)
    assert (configured_repo / "build" / "linux64").is_dir()


# =================================================================================================
# PLATFORM FLAG TESTS
# =================================================================================================

def test_all_accepts_linux_flag(configured_repo: Path) -> None:
    """--linux64 flag should be accepted and result in a successful build of an empty project."""
    r = run("all", "--linux64", cwd=configured_repo)
    assert_success(r)

def test_all_requires_platform_flag(configured_repo: Path) -> None:
    """Neither --qnx nor --linux given should be rejected by argparse."""
    r = run("all", cwd=configured_repo)
    assert r.returncode == 2, f"expected argparse rejection\nstderr: {r.stderr}"

def test_all_accepts_qnx64_flag(configured_repo: Path) -> None:
    """--qnx64 should be accepted by argparse (the toolchain file is hardcoded, not passed in)."""
    r = run("all", "--qnx64", cwd=configured_repo)
    assert r.returncode != 2, f"argparse rejected --qnx64\nstderr: {r.stderr}"

def test_all_rejects_qnx_with_value(configured_repo: Path) -> None:
    """Passing a toolchain file path to a platform flag is no longer supported."""
    r = run("all", "--qnx64=cmake/qnx.cmake", cwd=configured_repo)
    assert r.returncode == 2, f"Expected argparse exit code 2\nstderr: {r.stderr}"

def test_fails_without_toolchain_file(configured_repo: Path) -> None:
    """A missing hardcoded toolchain file should fail the build."""
    (configured_repo / "cmake" / "linux64.toolchain.cmake").unlink()
    r = run("all", "--linux64", cwd=configured_repo)
    assert_failure(r)
    assert "toolchain" in r.stderr + r.stdout

def test_platforms_mutually_exclusive(configured_repo: Path) -> None:
    """Two platform flags together should be rejected by argparse."""
    r = run("all", "--qnx64", "--linux64", cwd=configured_repo)
    assert r.returncode == 2, f"Expected argparse exit code 2\nstderr: {r.stderr}"

def test_target_accepts_linux_flag(configured_repo: Path) -> None:
    """--linux64 flag should be accepted on the target subcommand and create a build directory."""
    run("target", "my_node", "--linux64", cwd=configured_repo)
    assert (configured_repo / "build" / "linux64").is_dir()

def test_all_accepts_jobs_flag(configured_repo: Path) -> None:
    """-j flag should be accepted and not cause an argparse error."""
    r = run("all", "--linux64", "-j", "4", cwd=configured_repo)
    assert_success(r)

def test_all_rejects_invalid_jobs(configured_repo: Path) -> None:
    """-j with a non-integer value should be rejected by argparse."""
    r = run("all", "--linux64", "-j", "fast", cwd=configured_repo)
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
    (configured_repo / "build" / "linux64").mkdir(parents=True)
    (configured_repo / "build" / "qnx64").mkdir(parents=True)
    r = run("clean", cwd=configured_repo, stdin="n\n")
    assert_failure(r)
    assert (configured_repo / "build").exists()

def test_clean_removes_build_dir(configured_repo: Path) -> None:
    """Answering 'y' should remove the entire build/ directory."""
    (configured_repo / "build" / "linux64").mkdir(parents=True)
    (configured_repo / "build" / "qnx64").mkdir(parents=True)
    r = run("clean", cwd=configured_repo, stdin="y\n")
    assert_success(r)
    assert not (configured_repo / "build").exists()

def test_clean_handles_missing_build(configured_repo: Path) -> None:
    """Clean should succeed gracefully when build/ does not exist."""
    r = run("clean", cwd=configured_repo, stdin="y\n")
    assert_success(r)


# =================================================================================================
# COVERAGE / ASAN FLAG TESTS
# =================================================================================================

def flag_repo(repo: Path) -> Path:
    """Repo whose CMakeLists prints the SR_ENABLE_* values srhigh passes in."""
    (repo / "cmake").mkdir(exist_ok=True)
    for platform in ("qnx64", "qnxarm", "linux64", "linuxarm"):
        (repo / "cmake" / f"{platform}.toolchain.cmake").touch()
    (repo / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.16)\n"
        "project(flags NONE)\n"
        'message(STATUS "SR_ENABLE_COVERAGE=${SR_ENABLE_COVERAGE}")\n'
        'message(STATUS "SR_ENABLE_ASAN=${SR_ENABLE_ASAN}")\n'
    )
    return repo

def test_flags_default_off(repo: Path) -> None:
    r = run("all", "--linux64", cwd=flag_repo(repo))
    assert_success(r)
    assert "SR_ENABLE_COVERAGE=OFF" in r.stdout
    assert "SR_ENABLE_ASAN=OFF" in r.stdout

def test_coverage_flag_on(repo: Path) -> None:
    r = run("all", "--linux64", "--coverage", cwd=flag_repo(repo))
    assert_success(r)
    assert "SR_ENABLE_COVERAGE=ON" in r.stdout
    assert "SR_ENABLE_ASAN=OFF" in r.stdout

def test_asan_flag_on_target(repo: Path) -> None:
    r = run("target", "my_node", "--linux64", "--asan", cwd=flag_repo(repo))
    assert "SR_ENABLE_ASAN=ON" in r.stdout
    assert "SR_ENABLE_COVERAGE=OFF" in r.stdout

def test_flags_toggle_without_clean(repo: Path) -> None:
    """Flags are passed on every configure, so turning them off works on an existing build dir."""
    flag_repo(repo)
    assert "SR_ENABLE_COVERAGE=ON" in run("all", "--linux64", "--coverage", "--asan", cwd=repo).stdout
    r = run("all", "--linux64", cwd=repo)
    assert_success(r)
    assert "SR_ENABLE_COVERAGE=OFF" in r.stdout
    assert "SR_ENABLE_ASAN=OFF" in r.stdout

def test_flags_dont_warn_on_projects_without_them(configured_repo: Path) -> None:
    """Projects that don't read SR_ENABLE_* shouldn't get an unused variable warning."""
    r = run("all", "--linux64", cwd=configured_repo)
    assert_success(r)
    assert "SR_ENABLE_COVERAGE" not in r.stderr
    assert "deprecated" not in r.stderr

def test_coverage_rejected_with_qnx(configured_repo: Path) -> None:
    r = run("all", "--qnx64", "--coverage", cwd=configured_repo)
    assert r.returncode == 2, f"Expected argparse exit code 2\nstderr: {r.stderr}"
    assert "--linux64 only" in r.stderr

def test_asan_rejected_with_qnx(configured_repo: Path) -> None:
    r = run("target", "my_node", "--qnx64", "--asan", cwd=configured_repo)
    assert r.returncode == 2, f"Expected argparse exit code 2\nstderr: {r.stderr}"
