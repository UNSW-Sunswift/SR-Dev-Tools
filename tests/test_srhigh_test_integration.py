###############################################################################
# Integration tests for srhigh test CLI
# Author: Vipul Chiluvery
#
# Made to run automatically on CI. Tests srhigh test end to end by mocking a
# build/linux64 directory full of fake GoogleTest binaries (shell scripts) and
# running the CLI commands. Uses pytest. Requires the sr_dev_tools package to
# be installed (editable install is fine).
###############################################################################

import json
import stat
import sys
import subprocess
from pathlib import Path
import pytest
from sr_dev_tools import srhigh

# =================================================================================================
# HELPER FUNCTIONS
# =================================================================================================
def run(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    """Run `srhigh test <args>` and return the CompletedProcess object."""
    return subprocess.run(
        [sys.executable, "-m", "sr_dev_tools.srhigh", "test", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )

def make_binary(build_dir: Path, name: str, body: str = "exit 0", subdir: str = "src") -> Path:
    """Create an executable fake test binary. It appends its arguments to <name>.args for inspection."""
    path = build_dir / subdir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/bin/sh\necho "$@" >> "{path}.args"\n{body}\n')
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path

def was_run(binary: Path) -> bool:
    return Path(f"{binary}.args").exists()

def args_of(binary: Path) -> str:
    return Path(f"{binary}.args").read_text()

@pytest.fixture
def build_dir(repo: Path) -> Path:
    """build/linux64 under a marked repo, which is where srhigh test looks for binaries."""
    path = repo / "build" / "linux64"
    path.mkdir(parents=True)
    return path


# =================================================================================================
# SANITY CHECK TESTS
# =================================================================================================

def test_fails_without_marker(tmp_path: Path) -> None:
    """No .sunswift-evsn marker anywhere: srhigh test errors out."""
    r = run("all", cwd=tmp_path)
    assert r.returncode != 0
    assert "sunswift-evsn" in r.stderr

def test_fails_without_build_dir(repo: Path) -> None:
    """Should tell the user to build first if build/linux64 doesn't exist."""
    r = run("all", cwd=repo)
    assert r.returncode != 0
    assert "srhigh build all --linux" in r.stderr

def test_requires_action(build_dir: Path) -> None:
    """srhigh test with no all/target should be rejected by argparse."""
    r = run(cwd=build_dir)
    assert r.returncode == 2

def test_target_requires_at_least_one(build_dir: Path) -> None:
    r = run("target", cwd=build_dir)
    assert r.returncode == 2

def test_all_with_no_binaries_succeeds(build_dir: Path) -> None:
    """Nothing to run is not a failure."""
    r = run("all", cwd=build_dir)
    assert r.returncode == 0, r.stderr


# =================================================================================================
# DISCOVERY TESTS
# =================================================================================================

def test_all_runs_every_test_binary(build_dir: Path) -> None:
    a = make_binary(build_dir, "test_node_a")
    b = make_binary(build_dir, "test_node_b", subdir="deeply/nested")
    r = run("all", cwd=build_dir)
    assert r.returncode == 0, r.stderr
    assert was_run(a) and was_run(b)
    assert "node_a" in r.stdout and "node_b" in r.stdout

def test_all_ignores_non_test_files(build_dir: Path) -> None:
    """Non test_ executables, non-executables and files with suffixes aren't run."""
    other = make_binary(build_dir, "node_a")
    with_suffix = make_binary(build_dir, "test_node_a.sh")
    not_exec = build_dir / "test_not_exec"
    not_exec.write_text("#!/bin/sh\nexit 1\n")
    r = run("all", cwd=build_dir)
    assert r.returncode == 0, r.stderr
    assert not was_run(other)
    assert not was_run(with_suffix)

def test_all_skips_ignore_list(build_dir: Path) -> None:
    ignored = make_binary(build_dir, "test_can0_gateway", body="exit 1")
    r = run("all", cwd=build_dir)
    assert r.returncode == 0, r.stderr
    assert not was_run(ignored)

def test_all_except_skips_nodes(build_dir: Path) -> None:
    a = make_binary(build_dir, "test_node_a")
    b = make_binary(build_dir, "test_node_b", body="exit 1")
    c = make_binary(build_dir, "test_node_c", body="exit 1")
    r = run("all", "--except", "node_b", "node_c", cwd=build_dir)
    assert r.returncode == 0, r.stderr
    assert was_run(a)
    assert not was_run(b) and not was_run(c)

def test_target_runs_only_requested(build_dir: Path) -> None:
    a = make_binary(build_dir, "test_node_a")
    b = make_binary(build_dir, "test_node_b")
    r = run("target", "node_a", cwd=build_dir)
    assert r.returncode == 0, r.stderr
    assert was_run(a)
    assert not was_run(b)

def test_target_missing_binary_fails(build_dir: Path) -> None:
    """Asking for a node with no test binary should fail and say so."""
    a = make_binary(build_dir, "test_node_a")
    r = run("target", "node_a", "ghost", cwd=build_dir)
    assert r.returncode != 0
    assert was_run(a)
    assert "test_ghost" in r.stderr

def test_runs_from_subdirectory(build_dir: Path, repo: Path) -> None:
    a = make_binary(build_dir, "test_node_a")
    subdir = repo / "src" / "somewhere"
    subdir.mkdir(parents=True)
    r = run("all", cwd=subdir)
    assert r.returncode == 0, r.stderr
    assert was_run(a)

def test_ignores_qnx_build(repo: Path, build_dir: Path) -> None:
    """QNX binaries can't run on the host, so build/qnx64 is never searched."""
    qnx = make_binary(repo / "build" / "qnx64", "test_node_a")
    r = run("all", cwd=repo)
    assert r.returncode == 0, r.stderr
    assert not was_run(qnx)


# =================================================================================================
# RESULT TESTS
# =================================================================================================

def test_failing_binary_fails_run(build_dir: Path) -> None:
    make_binary(build_dir, "test_node_a")
    make_binary(build_dir, "test_node_b", body='echo "Expected equality"\nexit 1')
    r = run("all", cwd=build_dir)
    assert r.returncode != 0
    assert "FAILED" in r.stdout
    assert "Expected equality" in r.stdout  # diagnostic log is dumped

def test_failure_dumps_stdout_without_asan(build_dir: Path) -> None:
    """GoogleTest failures go to stdout, so that's what gets dumped by default."""
    make_binary(build_dir, "test_node_a", body='echo "gtest says no"\necho "stderr noise" >&2\nexit 1')
    r = run("all", cwd=build_dir)
    assert r.returncode != 0
    assert "gtest says no" in r.stdout
    assert "stderr noise" not in r.stdout

def test_failure_dumps_asan_trace(build_dir: Path) -> None:
    """An ASan report on stderr is always dumped, even without --asan."""
    make_binary(build_dir, "test_node_a", body='echo "ERROR: AddressSanitizer: heap-use-after-free" >&2\nexit 1')
    r = run("all", cwd=build_dir)
    assert r.returncode != 0
    assert "heap-use-after-free" in r.stdout

def test_failure_dumps_leak_report(build_dir: Path) -> None:
    """A LeakSanitizer report on stderr is dumped too."""
    make_binary(build_dir, "test_node_a", body='echo "LeakSanitizer: detected memory leaks" >&2\nexit 1')
    r = run("all", cwd=build_dir)
    assert r.returncode != 0
    assert "detected memory leaks" in r.stdout

def test_asan_flag_removed(build_dir: Path) -> None:
    """ASan is set at build time (srhigh build --asan), so srhigh test has no --asan flag."""
    r = run("all", "--asan", cwd=build_dir)
    assert r.returncode == 2

def test_logs_asan_on_for_asan_build(build_dir: Path) -> None:
    make_binary(build_dir, "test_node_a")
    (build_dir / "CMakeCache.txt").write_text("SR_ENABLE_ASAN:BOOL=ON\n")
    r = run("all", cwd=build_dir)
    assert r.returncode == 0, r.stderr
    assert "AddressSanitizer ON" in r.stderr

def test_logs_asan_off_for_normal_build(build_dir: Path) -> None:
    make_binary(build_dir, "test_node_a")
    (build_dir / "CMakeCache.txt").write_text("SR_ENABLE_ASAN:BOOL=OFF\n")
    r = run("all", cwd=build_dir)
    assert r.returncode == 0, r.stderr
    assert "AddressSanitizer OFF" in r.stderr


# =================================================================================================
# FLAG TESTS
# =================================================================================================

def test_filter_passed_to_gtest(build_dir: Path) -> None:
    a = make_binary(build_dir, "test_node_a")
    r = run("all", "-f", "*Parse*", cwd=build_dir)
    assert r.returncode == 0, r.stderr
    assert "--gtest_filter=*Parse*" in args_of(a)

def test_filter_on_target(build_dir: Path) -> None:
    a = make_binary(build_dir, "test_node_a")
    r = run("target", "node_a", "--filter", "Suite.*", cwd=build_dir)
    assert r.returncode == 0, r.stderr
    assert "--gtest_filter=Suite.*" in args_of(a)

def test_no_flags_passes_no_gtest_args(build_dir: Path) -> None:
    a = make_binary(build_dir, "test_node_a")
    run("all", cwd=build_dir)
    assert args_of(a).strip() == ""

def test_output_writes_reports(build_dir: Path, repo: Path) -> None:
    """-o is relative to CWD, and gets gtest XML paths plus a summary.json"""
    a = make_binary(build_dir, "test_node_a")
    make_binary(build_dir, "test_node_b", body="exit 1")
    r = run("all", "-o", "results", cwd=repo)
    assert r.returncode != 0

    out = repo / "results"
    assert f"--gtest_output=xml:{out.resolve() / 'test_node_a_report.xml'}" in args_of(a)
    summary = json.loads((out / "summary.json").read_text())
    assert summary["metrics"]["total_suites"] == 2
    assert summary["metrics"]["passed"] == 1
    assert summary["metrics"]["failed"] == 1
    statuses = {res["target"]: res["status"] for res in summary["results"]}
    assert statuses == {"node_a": "PASSED", "node_b": "FAILED"}


# =================================================================================================
# UNIT TESTS
# =================================================================================================

@pytest.mark.parametrize("status, line_coverage, expected", [
    ("PASSED", "42.0%", True),
    ("PASSED", "60.0%", False),
    ("PASSED", "95.5%", False),
    ("PASSED", "N/A", False),
    ("PASSED", "ERR", False),
    ("FAILED", "10.0%", False),
])
def test_is_low_coverage(status: str, line_coverage: str, expected: bool) -> None:
    result = srhigh.TestResult("node", status, line_coverage, "1/1")
    assert srhigh.is_low_coverage(result) is expected

def test_coverage_na_without_object_dir(tmp_path: Path) -> None:
    assert srhigh.extract_coverage_metrics(tmp_path, "node_a") == ("N/A", "N/A")

def test_coverage_na_without_gcda(tmp_path: Path) -> None:
    (tmp_path / "src" / "CMakeFiles" / "node_a_logic.dir").mkdir(parents=True)
    assert srhigh.extract_coverage_metrics(tmp_path, "node_a") == ("N/A", "N/A")

def gcov_block(kind: str, name: str, pct: float, count: int) -> str:
    return f"{kind} '{name}'\nLines executed:{pct:.2f}% of {count}\n\n"

def test_gcov_uses_file_totals_not_first_function(tmp_path: Path) -> None:
    """Function blocks come before the File block, so the first percentage isn't the file's."""
    out = (gcov_block("Function", "_Z3addii", 100, 1)
           + gcov_block("Function", "_Z6unusedi", 0, 1)
           + gcov_block("File", str(tmp_path / "src" / "logic.cpp"), 50, 2))
    assert srhigh.parse_gcov_output(out, tmp_path) == (1, 2, 1, 2)

def test_gcov_sums_multiple_files(tmp_path: Path) -> None:
    out = (gcov_block("Function", "_Z1av", 100, 3)
           + gcov_block("File", str(tmp_path / "a.cpp"), 100, 3)
           + gcov_block("Function", "_Z1bv", 0, 1)
           + gcov_block("File", str(tmp_path / "b.cpp"), 0, 1))
    assert srhigh.parse_gcov_output(out, tmp_path) == (3, 4, 1, 2)

def test_gcov_ignores_system_and_build_files(tmp_path: Path) -> None:
    """STL headers and generated build/ sources don't count, nor do their functions."""
    out = (gcov_block("Function", "_ZNSt6vectorIiE4sizeEv", 100, 8)
           + gcov_block("File", "/usr/include/c++/v1/vector", 100, 8)
           + gcov_block("Function", "_Z3genv", 100, 5)
           + gcov_block("File", str(tmp_path / "build" / "linux64" / "gen.cpp"), 100, 5)
           + gcov_block("Function", "_Z3addii", 0, 4)
           + gcov_block("File", str(tmp_path / "src" / "logic.cpp"), 0, 4))
    assert srhigh.parse_gcov_output(out, tmp_path) == (0, 4, 0, 1)

def test_gcov_filters_stl_and_gtest_functions(tmp_path: Path) -> None:
    out = (gcov_block("Function", "_ZNSt6vectorIiE4sizeEv", 100, 1)
           + gcov_block("Function", "testing::Test::Run", 100, 1)
           + gcov_block("Function", "_Z3addii", 100, 1)
           + gcov_block("File", str(tmp_path / "logic.cpp"), 100, 3))
    assert srhigh.parse_gcov_output(out, tmp_path) == (3, 3, 1, 1)

def test_resets_stale_coverage_counters(build_dir: Path) -> None:
    """Old .gcda counters are deleted before the test runs, so stale coverage is never reported."""
    obj_dir = build_dir / "src" / "CMakeFiles" / "node_a_logic.dir"
    obj_dir.mkdir(parents=True)
    stale = obj_dir / "logic.cpp.gcda"
    stale.write_text("stale")
    make_binary(build_dir, "test_node_a")
    r = run("all", cwd=build_dir)
    assert r.returncode == 0, r.stderr
    assert not stale.exists()
