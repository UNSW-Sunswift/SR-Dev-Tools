#!/usr/bin/env python3

###############################################################################
# Sunswift high level build, test, analysis and package tool
# Authors: Ryan Wong (build, pkg), Vipul Chiluvery (test), Claude + Ryan (analyse)
#   - Requires a .sunswift-evsn marker file in repo root to know where to search from
#     (except `srhigh pkg`, which works in any directory)
#   - build:   wraps CMake to configure, build and install targets into deploy/<platform>
#   - test:    discovers and runs GoogleTest binaries (test_<node>) in build/linux,
#              reporting line/function coverage (gcov), optionally with AddressSanitizer
#   - analyse: runs Scitools Understand CodeCheck (MISRA C++) over the repo
#   - pkg:     creates a new DDS package in the current working directory
# Usage:
#   - srhigh build all (--qnx=<toolchain-file> | --linux [--coverage] [--asan]) [-j N]
#   - srhigh build target <node1> <node2>... (--qnx=<toolchain-file> | --linux [--coverage] [--asan]) [-j N]
#   - srhigh build clean
#   - srhigh test all [--except <node>...] [-f <gtest filter>] [-o <report dir>] [--asan]
#   - srhigh test target <node1> <node2>... [-f <gtest filter>] [-o <report dir>] [--asan]
#   - srhigh analyse (--qnx | --linux)
#   - srhigh pkg create <name>
###############################################################################

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from sr_dev_tools.common_helpers import die, find_repo_root, print_box, setup_logging

logger = logging.getLogger("srhigh")

# =================================================================================================
# CONSTANTS
# =================================================================================================
CWD = Path.cwd().resolve()
# Change these if either change
MARKER_FILE = ".sunswift-evsn"
BUILD_FOLDER_NAME = "build"
INSTALL_FOLDER_NAME = "deploy"

# test
TEST_PLATFORM = "linux"  # test binaries can only run natively on the host
TEST_PREFIX = "test_"
TEST_TIMEOUT_S = 30
LOW_COVERAGE_PCT = 60.0
# Test binaries that require hardware/network daemons and should be skipped
TEST_IGNORE_LIST = {
    "test_can0_gateway",
}
# gcov function name prefixes from the C++ standard library which shouldn't count towards coverage
STL_SYMBOL_PREFIXES = ("_ZNSt", "_ZNKSt", "_ZSt", "_ZN9__gnu", "_ZNK9__gnu")

# analyse
UND_CONFIG_FILE = "misra-cpp2023.json"
ANALYSE_TXT = "analyse.txt"
UND_DB_NAME = "sranalyse.und"
ANALYSIS_DIR_NAME = "analysis"

# pkg. All of these are relative to pkg top level
PKG_NESTED_DIRS = {
    "src": "src",
    "include": "include",
    "param": "param",
    "test": "test",
    "unit_test": "test/unit"
}
PKG_FILES = {
    "metadata": ".srpkg",
    "make": "CMakeLists.txt",
    "readme": "README.md",
    "param": "param/{pkg_name}_param.toml",
    "main": "src/main.cpp",
    "node_header": "include/{pkg_name}.hpp",
    "node_source": "src/{pkg_name}.cpp",
    "logic_header": "include/{pkg_name}_logic.hpp",
    "logic_source": "src/{pkg_name}_logic.cpp",
    "unit_test": "test/unit/test_{pkg_name}.cpp"
}

@dataclass
class BuildData:
    build_root: Path  # dir containing the .sunswift-evsn marker; expected to also contain CMakeLists.txt
    build_dir_path: Path
    install_prefix: Path
    cmakelists_path: Path
    target_platform: str  # e.g. "qnx" or "linux"
    toolchain_path: Optional[Path]  # absolute path to CMake toolchain file, or None for native
    coverage: bool = False  # passed to CMake as SR_ENABLE_COVERAGE
    asan: bool = False  # passed to CMake as SR_ENABLE_ASAN

@dataclass
class PkgPaths:
    pkg_name: str
    abs_pkg_path: Path

@dataclass
class TestResult:
    target: str
    status: str  # PASSED, FAILED, TIMEOUT or ERROR
    line_coverage: str
    function_coverage: str

# =================================================================================================
# BUILD
# =================================================================================================

def safe_rmdir(path: Path, build_root: Path) -> bool:
    """Absolutely every error check again just to confirm before deletion.
    In case any bugs in error checking happen before. Then deletes specified dir.
    """
    if not path.exists():
        logger.error("Clean: Path does not exist")
        return False

    if not path.is_dir():
        logger.error("Clean: Path is not a directory")
        return False

    if path.is_symlink():
        logger.error("Clean: Path is a symlink")
        return False

    try:
        path.relative_to(build_root)
    except ValueError:
        logger.error("Clean: Path is not within build root")
        return False

    if path == build_root or path == Path("/"):
        die("wtf are u doing man")

    shutil.rmtree(path)
    return True

def on_off(flag: bool) -> str:
    return "ON" if flag else "OFF"

def unused_cli_flag() -> str:
    """CMake flag that silences the unused -D variable warning. CMake 4.4 renamed it, and each
    version ignores (or warns about) the other spelling
    """
    try:
        out = subprocess.run(["cmake", "--version"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        out = ""  # configure_cmake reports the missing cmake
    match = re.search(r"(\d+)\.(\d+)", out)
    version = (int(match[1]), int(match[2])) if match else (0, 0)
    return "-Wno-unused-cli" if version >= (4, 4) else "--no-warn-unused-cli"

def make_build_data(build_root: Path, target_platform: str, toolchain_path: Optional[Path],
                    coverage: bool = False, asan: bool = False) -> BuildData:
    """Derive all build paths from the repo root and target platform."""
    return BuildData(
        build_root=build_root,
        build_dir_path=build_root / BUILD_FOLDER_NAME / target_platform,
        install_prefix=build_root / INSTALL_FOLDER_NAME / target_platform,
        cmakelists_path=build_root / "CMakeLists.txt",
        target_platform=target_platform,
        toolchain_path=toolchain_path,
        coverage=coverage,
        asan=asan,
    )

def configure_cmake(build_data: BuildData) -> None:
    """Creates the build directory if it doesn't exist, and configures cmake
    using build_data.cmakelists_path. Specifies install prefix as
    build_data.install_prefix.
    """
    print_box("CMake Initialisation", width=60, ch="=")
    logger.info(f"TARGET PLATFORM: {build_data.target_platform}")
    logger.info(f"COVERAGE: {on_off(build_data.coverage)}, ASAN: {on_off(build_data.asan)}")
    # CMakeLists.txt at build root MUST exist. Makes build dir if does not exist
    if not build_data.cmakelists_path.is_file():
        die(
            f"Build: No CMakeLists.txt found at build root '{build_data.build_root}' "
            f"(the directory containing your {MARKER_FILE} marker)."
        )
    if not build_data.build_dir_path.is_dir():
        logger.info("Build: Build directory not found, creating build directory")
        try:
            build_data.build_dir_path.mkdir(parents=True)
        except Exception as e:
            die(f"Build: Failed to create build directory: {e}")

    # Re-init cmake. Coverage and ASan are always passed, so toggling them doesn't need a clean.
    # Projects that don't read them would warn about unused variables, hence unused_cli_flag()
    cmd = [
        "cmake",
        "-S", str(build_data.build_root),
        "-B", str(build_data.build_dir_path),
        unused_cli_flag(),
        f"-DCMAKE_INSTALL_PREFIX={build_data.install_prefix}",
        f"-DSR_ENABLE_COVERAGE={on_off(build_data.coverage)}",
        f"-DSR_ENABLE_ASAN={on_off(build_data.asan)}",
    ]

    if build_data.toolchain_path is not None:
        cmd.append(f"-DCMAKE_TOOLCHAIN_FILE={build_data.toolchain_path}")

    try:
        logger.info("Build: Initialising CMake")
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        die(f"Build: Error configuring CMake: {e}")

def cmake_build(targets: Optional[list[str]], build_data: BuildData, jobs: int) -> None:
    """Builds one, many or all targets using number of jobs. Does not install

    Args:
        targets (Optional[list[str]]): list of target names to build, if None, do all
        build_data (BuildData)
        jobs (int): number of jobs to run in parallel
    """
    print()
    print_box("Building Targets", width=60, ch="=")
    jobs_str = f"{jobs}"
    start_time = time.time()
    try:
        if targets is None:
            logger.info("Build: Building all targets")
            subprocess.run([
                "cmake", "--build", str(build_data.build_dir_path), "-j", jobs_str
            ], check=True)
        else:
            logger.info("Build: Building specified targets")
            # Uhh loop is probably less efficient, but the alternative is messy
            # If someone is using target, build times probably tiny anyway
            for target in targets:
                subprocess.run([
                    "cmake", "--build", str(build_data.build_dir_path), "--target", target, "-j", jobs_str
                ], check=True)
    except subprocess.CalledProcessError:
        die("Build: Error building targets")

    print()
    print_box("Build Complete", width=60, ch="=")
    logger.info(f"Build finished in {time.time()-start_time:.4f} seconds")

def cmake_install(targets: Optional[list[str]], build_data: BuildData) -> None:
    """Calls cmake --install <build_dir> to install bins into <install_prefix>

    Args:
        targets (Optional[list[str]]): none if all targets, else list of targets
        build_data (BuildData):
    """
    print()
    print_box("Installing Targets", width=60, ch="=")
    start_time = time.time()
    try:
        if targets is None:
            logger.info("Install: Installing all targets")
            subprocess.run([
                "cmake", "--install", str(build_data.build_dir_path)
            ], check=True)
        else:
            logger.info("Install: Installing specified targets")
            for target in targets:
                subprocess.run([
                    "cmake", "--install", str(build_data.build_dir_path), "--component", target
                ], check=True)

        # No matter what, always install runtime tools
        subprocess.run([
            "cmake", "--install", str(build_data.build_dir_path), "--component", "tools"
        ], check=True)
    except subprocess.CalledProcessError:
        die("Install: Error installing targets")

    print()
    print_box("Install Complete", width=60, ch="=")
    logger.info(f"Install finished in {time.time()-start_time:.4f} seconds")

def build(targets: Optional[list[str]], jobs: int, build_data: BuildData) -> int:
    """Configure, build, and install all targets (None) or the specified targets."""
    configure_cmake(build_data)
    cmake_build(targets, build_data, jobs)
    cmake_install(targets, build_data)
    return 0

def clean(build_root: Path) -> int:
    """Deletes the entire build/ directory under build_root."""
    print_box("Cleaning Targets", width=60, ch="=")
    path = build_root / BUILD_FOLDER_NAME
    res = input(f"[srhigh] Would you like to remove {path}? (y/n): ")
    if res.lower() != "y":
        die("Cancelling clean..")

    if path.is_dir():
        logger.info(f"Clean: Removing '{path}'")
        if safe_rmdir(path, build_root):
            logger.info(f"Clean: '{path}' removed successfully.")
    else:
        logger.info(f"Clean: {path} does not exist")

    print()
    print_box("Clean Complete", width=60, ch="=")
    return 0

# =================================================================================================
# TEST
# =================================================================================================

def parse_gcov_output(output: str, repo_root: Path) -> tuple[int, int, int, int]:
    """Totals `gcov -f` output into (lines_hit, lines_total, funcs_hit, funcs_total).
    gcov prints each source file's Function blocks followed by its File block. Only source files
    inside repo_root (and not generated under build/) count, which drops STL and system headers.
    """
    build_dir = repo_root / BUILD_FOLDER_NAME
    lines_hit = lines_total = funcs_hit = funcs_total = 0
    pending_funcs: list[tuple[str, float]] = []

    for kind, name, pct, count in re.findall(
        r"(Function|File) '(.*?)'\s+Lines executed:\s*([\d\.]+)% of (\d+)", output
    ):
        if kind == "Function":
            pending_funcs.append((name, float(pct)))
            continue

        source = (repo_root / name).resolve()
        counted = source.is_relative_to(repo_root) and not source.is_relative_to(build_dir)
        if counted:
            lines_total += int(count)
            lines_hit += round(float(pct) * int(count) / 100)
            for func_name, func_pct in pending_funcs:
                # Filter out C++ standard library and GoogleTest template noise
                if func_name.startswith(STL_SYMBOL_PREFIXES) or "testing::" in func_name:
                    continue
                funcs_total += 1
                if func_pct > 0.0:
                    funcs_hit += 1
        pending_funcs = []

    return lines_hit, lines_total, funcs_hit, funcs_total

def find_coverage_dir(build_dir_path: Path, node_name: str) -> Optional[Path]:
    """The node's <node>_logic CMake object directory, falling back to <node>"""
    for dir_name in (f"{node_name}_logic.dir", f"{node_name}.dir"):
        obj_dir = next((p for p in build_dir_path.rglob(dir_name) if p.is_dir()), None)
        if obj_dir:
            return obj_dir
    return None

def reset_coverage(build_dir_path: Path, node_name: str) -> None:
    """Deletes the node's .gcda counters, so coverage reflects only this run. Also stops stale
    counters from an old --coverage build being reported after coverage is turned off
    """
    obj_dir = find_coverage_dir(build_dir_path, node_name)
    if obj_dir:
        for gcda in obj_dir.rglob("*.gcda"):
            gcda.unlink(missing_ok=True)

def extract_coverage_metrics(build_dir_path: Path, node_name: str) -> tuple[str, str]:
    """Invokes gcov to extract line coverage percentage and function ratios, ignoring STL overhead.
    Coverage is read from the node's <node>_logic CMake object directory, falling back to <node>.
    """
    repo_root = build_dir_path.parents[1]  # build_dir_path is <root>/build/<platform>
    obj_dir = find_coverage_dir(build_dir_path, node_name)
    if not obj_dir:
        return "N/A", "N/A"

    gcda_files = list(obj_dir.rglob("*.gcda"))
    if not gcda_files:
        return "N/A", "N/A"

    try:
        # -f generates function-level statistics. gcov writes its .gcov files into cwd
        res = subprocess.run(
            ["gcov", "-f", *map(str, gcda_files)],
            capture_output=True, text=True, cwd=str(obj_dir)
        )
        lines_hit, lines_total, funcs_hit, funcs_total = parse_gcov_output(res.stdout, repo_root)
    except Exception:
        return "ERR", "ERR"

    line_str = f"{100 * lines_hit / lines_total:.1f}%" if lines_total > 0 else "N/A"
    func_str = f"{funcs_hit}/{funcs_total}" if funcs_total > 0 else "N/A"
    return line_str, func_str

def find_test_binaries(build_dir_path: Path) -> list[Path]:
    """Recursively find all executable test_* binaries in the build directory, minus TEST_IGNORE_LIST"""
    return sorted(
        p for p in build_dir_path.rglob(f"{TEST_PREFIX}*")
        if p.is_file() and os.access(p, os.X_OK) and p.suffix == "" and p.name not in TEST_IGNORE_LIST
    )

def run_one_test(binary: Path, build_dir_path: Path, gtest_filter: Optional[str],
                 log_path: Optional[Path], env: dict[str, str], use_asan: bool) -> TestResult:
    """Runs a single GoogleTest binary and collects its coverage."""
    node_name = binary.name.removeprefix(TEST_PREFIX)
    cmd = [str(binary)]
    if gtest_filter:
        cmd.append(f"--gtest_filter={gtest_filter}")
    if log_path:
        cmd.append(f"--gtest_output=xml:{log_path / f'{binary.name}_report.xml'}")

    reset_coverage(build_dir_path, node_name)
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=TEST_TIMEOUT_S, env=env)
    except subprocess.TimeoutExpired:
        return TestResult(node_name, "TIMEOUT", "N/A", "N/A")
    except Exception as e:
        logger.error(f"Test: Could not run {binary.name} - {e}")
        return TestResult(node_name, "ERROR", "N/A", "N/A")

    if res.returncode == 0:
        line_cov, func_cov = extract_coverage_metrics(build_dir_path, node_name)
        return TestResult(node_name, "PASSED", line_cov, func_cov)

    # Dump ASan's stack trace if there is one, otherwise GoogleTest's failure output
    print("\n" + "!" * 60)
    print(f"TEST FAILURE DIAGNOSTIC LOG IN {binary.name}:")
    if "AddressSanitizer" in res.stderr or use_asan:
        print(res.stderr if res.stderr else res.stdout)
    else:
        print(res.stdout)
    print("!" * 60 + "\n")
    return TestResult(node_name, "FAILED", "N/A", "N/A")

def is_low_coverage(result: TestResult) -> bool:
    """True if a passing test's line coverage is a number below LOW_COVERAGE_PCT"""
    if result.status != "PASSED":
        return False
    try:
        return float(result.line_coverage.rstrip("%")) < LOW_COVERAGE_PCT
    except ValueError:
        return False

def print_test_summary(results: list[TestResult], total_time: float) -> None:
    print()
    print_box("Test & Code Coverage Summary", width=75, ch="=")
    print(f"{'Target':<25} | {'Status':<10} | {'Line Coverage':<15} | {'Functions':<10}")
    print("-" * 75)
    for r in results:
        flag = " <-- Warning: Low Coverage!" if is_low_coverage(r) else ""
        print(f"{r.target:<25} | {r.status:<10} | {r.line_coverage:<15} | {r.function_coverage:<10}{flag}")
    print("=" * 75)
    num_passed = sum(r.status == "PASSED" for r in results)
    logger.info(f"Test: Total  - {len(results)}")
    logger.info(f"Test: Passed - {num_passed}")
    logger.info(f"Test: Failed - {len(results) - num_passed}")
    logger.info(f"Test finished in {total_time:.4f} seconds")

def write_test_summary_json(results: list[TestResult], total_time: float, log_path: Path) -> None:
    """High-level metadata payload for CI/CD pipelines"""
    num_passed = sum(r.status == "PASSED" for r in results)
    summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "metrics": {
            "total_suites": len(results),
            "passed": num_passed,
            "failed": len(results) - num_passed,
            "execution_time_seconds": total_time,
        },
        "results": [r.__dict__ for r in results],
    }
    with (log_path / "summary.json").open("w") as f:
        json.dump(summary, f, indent=4)

def test(targets: Optional[list[str]], exceptions: list[str], build_root: Path,
         gtest_filter: Optional[str], output_dir: Optional[str], use_asan: bool) -> int:
    """Run every test binary (targets=None) or only those of the given nodes.
    Returns the number of failed or missing test binaries.
    """
    build_dir_path = build_root / BUILD_FOLDER_NAME / TEST_PLATFORM
    if not build_dir_path.is_dir():
        logger.error(f"Test: {build_dir_path} not found. Run 'srhigh build all --linux' before testing.")
        return 1

    print_box("Testing Targets", width=60, ch="=")
    binaries = find_test_binaries(build_dir_path)
    missing: list[str] = []
    if targets is None:
        skip = {f"{TEST_PREFIX}{node}" for node in exceptions}
        binaries = [b for b in binaries if b.name not in skip]
    else:
        found = {b.name for b in binaries}
        missing = [t for t in targets if f"{TEST_PREFIX}{t}" not in found]
        wanted = {f"{TEST_PREFIX}{t}" for t in targets}
        binaries = [b for b in binaries if b.name in wanted]

    for t in missing:
        logger.warning(f"Test: No test binary '{TEST_PREFIX}{t}' found in {build_dir_path}")

    if not binaries:
        logger.warning("Test: No test binaries matched the requested targets")
        return len(missing)

    if gtest_filter:
        logger.info(f"Test: Applying GoogleTest filter pattern '{gtest_filter}'")
    if use_asan:
        logger.info("Test: Monitoring AddressSanitizer (ASan) runtime events")

    log_path = None
    if output_dir:
        log_path = (CWD / output_dir).resolve()
        log_path.mkdir(parents=True, exist_ok=True)

    # With --asan, make AddressSanitizer track memory leaks and keep console formatting intact
    env = os.environ.copy()
    if use_asan:
        env["ASAN_OPTIONS"] = "detect_leaks=1:color=always"

    start_time = time.time()
    results = []
    for binary in binaries:
        logger.info(f"Test: Running {binary.name}")
        results.append(run_one_test(binary, build_dir_path, gtest_filter, log_path, env, use_asan))
    total_time = time.time() - start_time

    print_test_summary(results, total_time)
    if log_path:
        write_test_summary_json(results, total_time, log_path)
        logger.info(f"Test: Reports written to {log_path}")

    return sum(r.status != "PASSED" for r in results) + len(missing)

# =================================================================================================
# ANALYSE
# =================================================================================================

def resolve_analyse_globs(analyse_txt: Path, repo_root: Path) -> Path:
    """Und's input files do not allow glob, so manually expand globs. Returns path to temp file with expanded globs"""
    resolved: list[str] = []

    for lineno, raw_line in enumerate(analyse_txt.read_text().splitlines(), start=1):
        pattern = raw_line.split("#", 1)[0].strip()
        if not pattern:
            continue

        try:
            matches = sorted(repo_root.glob(pattern))
        except Exception as e:
            die(f"Analyse: bad glob pattern on {analyse_txt}:{lineno}: '{pattern}' - {e}")

        if not matches:
            logger.warning(f"Analyse: glob pattern on {analyse_txt}:{lineno} matched no files: '{pattern}'")
            continue

        resolved.extend(str(m.relative_to(repo_root)) for m in matches if m.is_file())

    if not resolved:
        die(f"Analyse: {analyse_txt} resolved to no files")

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    tmp.write("\n".join(resolved) + "\n")
    tmp.close()
    return Path(tmp.name)

def analyse(repo_root: Path, build_dir_path: Path) -> int:
    """Uses Scitools Understand CLI to run CodeCheck Misra CPP"""
    if not (repo_root/UND_CONFIG_FILE).is_file():
        logger.error(f"Analyse: {str(repo_root/UND_CONFIG_FILE)} not found")
        return 1

    if not (repo_root/ANALYSE_TXT).is_file():
        logger.error(f"Analyse: {str(repo_root/ANALYSE_TXT)} not found")
        return 1

    try:
        subprocess.run(
            ["und", "-isundlicensed"],
            cwd=repo_root,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        logger.error(f"An error has occurred: {e}")
        logger.error("Scitools Understand is probably not licensed or installed")
        return 1

    compile_commands = build_dir_path/"compile_commands.json"
    if not compile_commands.is_file():
        logger.error(f"Analyse: {compile_commands} not found, please build first")
        return 1

    print_box("Analysing Repo")

    setup_steps = [
        ("create",   ["und", "-db", UND_DB_NAME, "create", "-languages", "c++"]),
        ("settings", ["und", "-db", UND_DB_NAME, "settings",
                      "-C++MacrosAdd", "__GNUC__=12"]),
        ("add",      ["und", "-db", UND_DB_NAME, "add", "-cmake", str(compile_commands)]),
    ]

    for stage, cmd in setup_steps:
        try:
            subprocess.run(cmd, cwd=repo_root, check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"und '{stage}' failed - {e}")
            return 1

    resolved_files = resolve_analyse_globs(repo_root/ANALYSE_TXT, repo_root)
    try:
        result = subprocess.run(
            [
                "und", "-db", UND_DB_NAME,
                "codecheck",
                "-files", str(resolved_files),
                "-sarif", f"{ANALYSIS_DIR_NAME}/analysis.sarif",
                "-exitstatus",
                str(repo_root / UND_CONFIG_FILE),
                f"./{ANALYSIS_DIR_NAME}",
            ],
            cwd=repo_root,
        )
    finally:
        resolved_files.unlink(missing_ok=True)

    if result.returncode == 0:
        logger.info("Analyse: no violations found")
        return 0
    elif result.returncode > 0:
        logger.info(f"Analyse: {result.returncode} violation(s) found")
        return 1
    else:
        logger.error(f"Analyse: und codecheck crashed (exit {result.returncode})")
        return 1

# =================================================================================================
# PKG
# =================================================================================================

def fill_readme(paths: PkgPaths) -> None:
    text = f"""# {paths.pkg_name} DDS Package

## Description
Briefly describe the purpose of this DDS node.

## Topics Published to
Enter topics published to below
Topic | Topic Type | Description
------|----------|------------
/domain/subsystem/topic|`Topic Type`|BMS Voltage

## Topics Subscribed to
Enter topics subscribed to below
Topic | Topic Type | Description
------|----------|------------
/domain/subsystem/topic|`Topic Type`|BMS Voltage

## Parameters
Under construction!

## Contributors
Written by `Your name here` | `Your zID here`"""
    with (paths.abs_pkg_path / PKG_FILES["readme"]).open("w") as file:
        file.write(text)

def fill_cmakelists(paths: PkgPaths) -> None:
    text = f"""# Per-node info
set(TARGET_NAME {paths.pkg_name})
set(SOURCES
    src/main.cpp
    src/{paths.pkg_name}.cpp
    # Add your sources here
)
set(INCLUDE_DIRS
    include
)
set (LIBS
    sr_node
    ${{TARGET_NAME}}_logic
    # add your type libraries here
    # add other dependencies here
)
set(PARAM_FILE param/{paths.pkg_name}_param.toml)

# Testable logic, no DDS
add_library(${{TARGET_NAME}}_logic STATIC src/${{TARGET_NAME}}_logic.cpp)
target_include_directories(${{TARGET_NAME}}_logic PUBLIC ${{INCLUDE_DIRS}})

# Compile and link
add_executable(${{TARGET_NAME}} ${{SOURCES}})
target_include_directories(${{TARGET_NAME}} PRIVATE ${{INCLUDE_DIRS}})
target_link_libraries(${{TARGET_NAME}} PRIVATE ${{LIBS}})

# Unit tests, only if GoogleTest is available
if(TARGET GTest::gtest_main)
    add_executable(test_${{TARGET_NAME}} test/unit/test_${{TARGET_NAME}}.cpp)
    target_link_libraries(test_${{TARGET_NAME}} PRIVATE ${{TARGET_NAME}}_logic GTest::gtest_main)
endif()

# Install time
install(
    TARGETS ${{TARGET_NAME}}
    RUNTIME DESTINATION bin
    COMPONENT ${{TARGET_NAME}}
)
if(PARAM_FILE)
    install(
        FILES ${{PARAM_FILE}}
        DESTINATION param
        COMPONENT ${{TARGET_NAME}}
    )
endif()
"""
    with (paths.abs_pkg_path / PKG_FILES["make"]).open("w") as file:
        file.write(text)

def fill_param(paths: PkgPaths) -> None:
    text = f"""# {paths.pkg_name}_param.toml
# Parameter file for {paths.pkg_name}
# All parameters are optional. Missing keys fall back to declared defaults in the node.
# Undeclared parameters are ignored

[params]
# example_string = "hello"
# example_int    = 42
# example_float  = 3.14
# example_bool   = true

"""
    with (paths.abs_pkg_path / PKG_FILES["param"].format(pkg_name=paths.pkg_name)).open("w") as file:
        file.write(text)

def class_name(pkg_name: str) -> str:
    """my_node -> MyNode. C++ names can't start with a digit"""
    name = "".join(part.capitalize() for part in pkg_name.split("_"))
    return f"Pkg{name}" if name[:1].isdigit() else name

def gtest_suite_name(pkg_name: str) -> str:
    return f"{class_name(pkg_name)}Test"

def fill_main(paths: PkgPaths) -> None:
    text = f"""// Starts the node. No need to edit
#include "{paths.pkg_name}.hpp"

int main(int argc, char* argv[]) {{
    {class_name(paths.pkg_name)} node;
    node.spin();
}}
"""
    with (paths.abs_pkg_path / PKG_FILES["main"]).open("w") as file:
        file.write(text)

def fill_node(paths: PkgPaths) -> None:
    cls = class_name(paths.pkg_name)
    header = f"""// Declare your publishers, subscribers and handler functions here
#pragma once

#include "sr_node.hpp"
#include "{paths.pkg_name}_logic.hpp"

class {cls} : public SRNode {{
public:
    {cls}();
    ~{cls}() override;

private:
    {cls}Logic logic_;
}};
"""
    source = f"""// Create publishers, subscribers and timers, and handle incoming data here
#include "{paths.pkg_name}.hpp"

{cls}::{cls}() : SRNode("{paths.pkg_name}") {{
    // TODO: create publishers, subscribers and timers
}}

{cls}::~{cls}() = default;
"""
    with (paths.abs_pkg_path / PKG_FILES["node_header"].format(pkg_name=paths.pkg_name)).open("w") as file:
        file.write(header)
    with (paths.abs_pkg_path / PKG_FILES["node_source"].format(pkg_name=paths.pkg_name)).open("w") as file:
        file.write(source)

def fill_logic(paths: PkgPaths) -> None:
    cls = class_name(paths.pkg_name)
    header = f"""// Declare your logic functions here
#pragma once

class {cls}Logic {{
public:
    // TODO: add your functions
}};
"""
    source = f"""// Write your logic here
#include "{paths.pkg_name}_logic.hpp"
"""
    with (paths.abs_pkg_path / PKG_FILES["logic_header"].format(pkg_name=paths.pkg_name)).open("w") as file:
        file.write(header)
    with (paths.abs_pkg_path / PKG_FILES["logic_source"].format(pkg_name=paths.pkg_name)).open("w") as file:
        file.write(source)

def fill_unit_test(paths: PkgPaths) -> None:
    text = f"""// Write unit tests for your logic here
#include <gtest/gtest.h>
#include "{paths.pkg_name}_logic.hpp"

TEST({gtest_suite_name(paths.pkg_name)}, Placeholder) {{
    SUCCEED(); // TODO: replace with real tests
}}
"""
    with (paths.abs_pkg_path / PKG_FILES["unit_test"].format(pkg_name=paths.pkg_name)).open("w") as file:
        file.write(text)

def validate_pkg_name(name: str) -> PkgPaths:
    if not re.match(r"^[a-z0-9_]+$", name):
        die("Pkg: Invalid package name: must be in 'snake_case'")
    return PkgPaths(name, CWD / name)

def mkdir_package(paths: PkgPaths) -> None:
    """Create the package directory tree and empty files."""
    paths.abs_pkg_path.mkdir()
    for dir in PKG_NESTED_DIRS.values():
        (paths.abs_pkg_path / dir).mkdir()
    for file in PKG_FILES.values():
        (paths.abs_pkg_path / file.format(pkg_name=paths.pkg_name)).touch()

def pkg_create(name: str) -> int:
    """Create a new package in CWD if no directory with that name already exists."""
    paths = validate_pkg_name(name)
    if paths.abs_pkg_path.exists():
        die(f"Pkg: '{paths.pkg_name}' already exists at '{paths.abs_pkg_path}'")

    try:
        mkdir_package(paths)
        fill_readme(paths)
        fill_cmakelists(paths)
        fill_param(paths)
        fill_main(paths)
        fill_node(paths)
        fill_logic(paths)
        fill_unit_test(paths)
    except Exception as e:
        if paths.abs_pkg_path.exists():
            shutil.rmtree(paths.abs_pkg_path)
        die(f"Pkg: Error creating package: {e}")

    logger.info(f"Pkg: Package '{paths.pkg_name}' created successfully!")
    logger.info(f"Pkg: Location: {paths.abs_pkg_path}")
    logger.info("Pkg: Created structure:")
    for dir in PKG_NESTED_DIRS.values():
        logger.info(f"  {dir}")
    for file_name in PKG_FILES.values():
        logger.info(f"  {file_name.format(pkg_name=paths.pkg_name)}")
    return 0

# =================================================================================================
# CLI
# =================================================================================================

def parse_args() -> argparse.Namespace:
    """Construct parser and return arguments."""
    parser = argparse.ArgumentParser(
        description="Sunswift high level build, test, analysis and package tool"
    )
    level1_junction = parser.add_subparsers(dest="command", required=True)

    # srhigh build...
    build_common = argparse.ArgumentParser(add_help=False)
    build_common.add_argument("--jobs", "-j", default=8, type=int, help="Number of parallel jobs Make runs. Default=8")
    build_platform = build_common.add_mutually_exclusive_group(required=True)
    build_platform.add_argument("--qnx", metavar="TOOLCHAIN_FILE", help="Build QNX packages using the given CMake toolchain file (path relative to current working directory)")
    build_platform.add_argument("--linux", action="store_true", help="Build Linux packages")
    build_common.add_argument("--coverage", action="store_true", help="Instrument for gcov coverage, sets SR_ENABLE_COVERAGE=ON (Linux only)")
    build_common.add_argument("--asan", action="store_true", help="Build with AddressSanitizer, sets SR_ENABLE_ASAN=ON (Linux only)")

    command_build = level1_junction.add_parser("build", help="Configure, build and install all or specific targets")
    build_sub = command_build.add_subparsers(dest="build_action", required=True)
    build_sub.add_parser("all", parents=[build_common], help="Build and install all targets")
    build_sub.add_parser("clean", help="Delete the build/ directory, but NOT deploy/")
    build_target = build_sub.add_parser("target", parents=[build_common], help="Build and install specific targets")
    build_target.add_argument("targets", nargs="+", help="One or more target names")

    # srhigh test...
    test_common = argparse.ArgumentParser(add_help=False)
    test_common.add_argument("--filter", "-f", default=None, help="GoogleTest case filter pattern")
    test_common.add_argument("--output", "-o", default=None, help="Directory to save structured XML/JSON reports")
    test_common.add_argument("--asan", "-a", action="store_true", help="Monitor runtime memory profiles via AddressSanitizer")

    command_test = level1_junction.add_parser("test", help=f"Run GoogleTest binaries from {BUILD_FOLDER_NAME}/{TEST_PLATFORM}")
    test_sub = command_test.add_subparsers(dest="test_action", required=True)
    test_all = test_sub.add_parser("all", parents=[test_common], help="Discover and run every test binary")
    test_all.add_argument("--except", "-e", nargs="+", dest="except_nodes", default=[], help="Node names to skip")
    test_target = test_sub.add_parser("target", parents=[test_common], help="Run tests for specific nodes")
    test_target.add_argument("targets", nargs="+", help="One or more node names")

    # srhigh analyse...
    command_analyse = level1_junction.add_parser("analyse", help="Run Scitools und CodeCheck (MISRA C++) over the repo")
    analyse_platform = command_analyse.add_mutually_exclusive_group(required=True)
    analyse_platform.add_argument("--qnx", action="store_true", help="Analyse the QNX build (build/qnx)")
    analyse_platform.add_argument("--linux", action="store_true", help="Analyse the Linux build (build/linux)")

    # srhigh pkg...
    command_pkg = level1_junction.add_parser("pkg", help="DDS package management. Packages are created in your current working directory")
    pkg_sub = command_pkg.add_subparsers(dest="pkg_action", required=True)
    pkg_create_cmd = pkg_sub.add_parser("create", help="Create a new DDS package")
    pkg_create_cmd.add_argument("name", help="Name of package to create (snake_case)")

    args = parser.parse_args()
    if getattr(args, "qnx", None) and args.command == "build" and (args.coverage or args.asan):
        parser.error("--coverage and --asan are Linux only, as unit tests only run on Linux")
    return args

# =================================================================================================
# MAIN
# =================================================================================================
def main() -> int:
    setup_logging("srhigh")
    args = parse_args()

    # pkg works in any directory, everything else needs the repo root
    if args.command == "pkg":
        return pkg_create(args.name)

    # repo_root: nearest ancestor of CWD containing a .sunswift-evsn marker (dies if none found)
    repo_root = find_repo_root(CWD, MARKER_FILE)

    failures = 0
    if args.command == "build":
        if args.build_action == "clean":
            failures = clean(repo_root)
        else:
            if args.qnx:
                build_data = make_build_data(repo_root, "qnx", (CWD / args.qnx).resolve())
            else:
                build_data = make_build_data(repo_root, "linux", None, args.coverage, args.asan)
            targets = None if args.build_action == "all" else args.targets
            failures = build(targets, args.jobs, build_data)
    elif args.command == "test":
        if args.test_action == "all":
            failures = test(None, args.except_nodes, repo_root, args.filter, args.output, args.asan)
        elif args.test_action == "target":
            failures = test(args.targets, [], repo_root, args.filter, args.output, args.asan)
    elif args.command == "analyse":
        target_platform = "qnx" if args.qnx else "linux"
        failures = analyse(repo_root, repo_root / BUILD_FOLDER_NAME / target_platform)

    return 1 if failures else 0

if __name__ == "__main__":
    sys.exit(main())
