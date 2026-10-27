###############################################################################
# Integration tests for srhigh analyse CLI
#
# Made to run automatically on CI. Understand (und) isn't available on CI, so
# these only cover argument handling, pre-flight checks and glob resolution.
###############################################################################

import sys
import subprocess
from pathlib import Path
import pytest
from sr_dev_tools import srhigh

# =================================================================================================
# HELPER FUNCTIONS
# =================================================================================================
def run(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    """Run `srhigh analyse <args>` and return the CompletedProcess object."""
    return subprocess.run(
        [sys.executable, "-m", "sr_dev_tools.srhigh", "analyse", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


# =================================================================================================
# CLI TESTS
# =================================================================================================

def test_requires_platform_flag(repo: Path) -> None:
    r = run(cwd=repo)
    assert r.returncode == 2

def test_qnx_and_linux_mutually_exclusive(repo: Path) -> None:
    r = run("--qnx64", "--linux64", cwd=repo)
    assert r.returncode == 2

def test_fails_without_marker(tmp_path: Path) -> None:
    r = run("--linux64", cwd=tmp_path)
    assert r.returncode != 0
    assert "sunswift-evsn" in r.stderr

def test_fails_without_und_config(repo: Path) -> None:
    (repo / "analyse.txt").write_text("src/*.cpp\n")
    r = run("--linux64", cwd=repo)
    assert r.returncode == 1
    assert "misra-cpp2023.json" in r.stderr

def test_fails_without_analyse_txt(repo: Path) -> None:
    (repo / "misra-cpp2023.json").write_text("{}")
    r = run("--linux64", cwd=repo)
    assert r.returncode == 1
    assert "analyse.txt" in r.stderr


# =================================================================================================
# GLOB RESOLUTION TESTS
# =================================================================================================

@pytest.fixture
def sources(tmp_path: Path) -> Path:
    for f in ["src/a/main.cpp", "src/a/util.cpp", "src/b/deep/node.cpp", "src/b/node.hpp"]:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).touch()
    return tmp_path

def resolve(sources: Path, analyse_txt: str) -> list[str]:
    txt = sources / "analyse.txt"
    txt.write_text(analyse_txt)
    out = srhigh.resolve_analyse_globs(txt, sources)
    try:
        return out.read_text().splitlines()
    finally:
        out.unlink()

def test_globs_expand_relative_to_root(sources: Path) -> None:
    assert resolve(sources, "src/a/*.cpp\n") == ["src/a/main.cpp", "src/a/util.cpp"]

def test_globs_recursive(sources: Path) -> None:
    assert resolve(sources, "src/**/*.cpp\n") == ["src/a/main.cpp", "src/a/util.cpp", "src/b/deep/node.cpp"]

def test_globs_skip_comments_and_blanks(sources: Path) -> None:
    text = "# a comment\n\nsrc/b/node.hpp   # inline comment\n"
    assert resolve(sources, text) == ["src/b/node.hpp"]

def test_globs_skip_unmatched_pattern(sources: Path) -> None:
    assert resolve(sources, "nothing/*.cpp\nsrc/b/node.hpp\n") == ["src/b/node.hpp"]

def test_globs_no_matches_dies(sources: Path) -> None:
    (sources / "analyse.txt").write_text("nothing/*.cpp\n")
    with pytest.raises(SystemExit):
        srhigh.resolve_analyse_globs(sources / "analyse.txt", sources)
