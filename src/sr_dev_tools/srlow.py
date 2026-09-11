#!/usr/bin/env python3

###############################################################################
# Sunswift low level build and test tool
# Author: Ryan Wong
#   - Requries a marker file in repo root to know where to search from
#   - Builds all stm32 modules under src/*/ where a CMakeLists.txt is found in each module root.
#   - Then installs each module's binary into a root "deploy" dirctory
#   - Also invokes ceedling for testing and und CodeCheck for static analysis
# Usage: 
#   - srlow build all
#   - srlow build target <target1> <target2>...
#   - srlow build clean
#   - srlow test all
#   - srlow test target <target1> <target2>...
#   - srlow analyse all
#   - srlow analyse target <target1> <target2>...
###############################################################################

import argparse
import subprocess
import sys
import time
import shutil
from enum import Enum
from typing import Callable, Optional
from pathlib import Path
from sr_dev_tools.common_helpers import die, find_repo_root, print_box


class Result(Enum):
    """Outcome of building or testing a single module."""
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"

# =================================================================================================
# CONSTANTS
# =================================================================================================
CWD = Path.cwd().resolve()
# Change these if either change
INSTALL_FOLDER_NAME = "deploy"
SRC_DIR = "src"
MARKER_FILE = ".sunswift-firmware"
UND_CONFIG_FILE = "misra-c2025.json"

# =================================================================================================
# HELPERS
# =================================================================================================
def safe_rmdir(path: Path) -> bool:
    """Meant to safely delete a build directory during srlow build clean"""

    if not path.exists():
        print("[srlow] Clean: Path does not exist")
        return False

    if not path.is_dir():
        print("[srlow] Clean: Path is not a directory")
        return False

    if path.is_symlink():
        print("[srlow] Clean: Path is a symlink")
        return False

    if path.name != "build":
        print("[srlow] Clean: Are you deleting a build directory?")
        return False
        
    shutil.rmtree(path)
    return True

def configure_and_build(module_root: Path, preset: str, repo_root: Path) -> Result:
    """Configures, builds and installs a module using STM32 presets"""
    print_box(f"Building {module_root.name}")
    if not (module_root/"CMakeLists.txt").is_file():
        print(f"[srlow] Build: {module_root.name} doesn't have a CMakeLists.txt")
        return Result.FAIL

    if not (module_root/"CMakePresets.json").is_file():
        print(f"[srlow] Build: {module_root.name} doesn't have a CMakePresets.json")
        return Result.FAIL
    # Configure and build
    try:
        subprocess.run(
            ["cmake", "--preset", preset],
            cwd=module_root,
            check=True,
        )
        subprocess.run(
            ["cmake", "--build", "--preset", preset],
            cwd=module_root,
            check=True
        )
        subprocess.run(
            ["cmake", "--install", f"./build/{preset}", "--prefix", str(repo_root / INSTALL_FOLDER_NAME)],
            cwd=module_root,
            check=True
        )
        return Result.PASS
    except Exception as e:
        print(f"[srlow] Build: Error building - {e}")
        return Result.FAIL


def test_one(module_root: Path) -> Result:
    """Runs ceedling in module_root/Test"""
    print_box(f"Testing {module_root.name}")
    if not (module_root/"Test").is_dir():
        print(f"[srlow] Test: {module_root.name} doesn't have a Test folder, skipping...")
        return Result.SKIP

    try:
        subprocess.run(
            ["ceedling", "test:all", "gcov:all", "valgrind:all"],
            cwd=module_root/"Test",
            check=True,
        )
        return Result.PASS
    except Exception as e:
        print(f"[srlow] Test: Testing failed - {e}")
        return Result.FAIL


def analyse_one(module_root: Path, preset: str, repo_root: Path) -> Result:
    """Runs a bunch of und commands to setup and execute CodeCheck"""
    print_box(f"Analysing {module_root.name}")
    if not (module_root/"analyse.txt").is_file():
        print(f"[srlow] No analyse file found, skipping...")
        return Result.SKIP
    
    try:
        subprocess.run(
            ["und", "-db", f"{module_root.name}.und", "create", "-languages", "c++"],
            cwd=module_root,
            check=True
        )
        subprocess.run(
            ["und", "-db", f"{module_root.name}.und", "settings", "-C++MacrosAdd", "__GNUC__=15"],
            cwd=module_root,
            check=True
        )
        subprocess.run(
            ["und", "-db", f"{module_root.name}.und", "add", "-cmake", f"./build/{preset}/compile_commands.json"],
            cwd=module_root,
            check=True
        )
        output_dir_name = {module_root.name}
        subprocess.run(
            [
                "und", 
                "-db", 
                f"{module_root.name}.und", 
                "codecheck", 
                "-files", 
                "./analyse.txt", 
                "-sarif", 
                f"{output_dir_name}/{module_root.name}_codecheck.sarif", 
                "-exitstatus", 
                f"{str(repo_root/UND_CONFIG_FILE)}", 
                f"./{output_dir_name}"
            ],
            cwd=module_root,
            check=True
        )
        return Result.PASS
    except Exception as e:
        print(f"[srlow] Analyse: Analysis failed - {e}")
        return Result.FAIL


def run_over_modules(
    label: str,
    targets: Optional[list[str]],
    repo_root: Path,
    run_one: Callable[[Path], Result],
) -> int:
    """Run `run_one` over every src/ module, tally results.
    Returns the number of FAIL results.
    """
    print_box(f"{label}ing Targets", width=60, ch="=")
    start_time = time.time()

    src_dir = repo_root/SRC_DIR
    modules = []
    num_pass = []
    num_fail = []
    missing = []
    
    
    # figure out which modules to include
    if targets is None:
        modules = [d.name for d in src_dir.iterdir() if d.is_dir()]
    else:
        dir_names = [d.name for d in (repo_root/SRC_DIR).iterdir() if d.is_dir()]
        modules = [t for t in targets if t in dir_names]
        missing = [t for t in targets if t not in modules] 
    
    for module in modules:
        full_path = repo_root/SRC_DIR/module
        if full_path.is_dir():
            retval = run_one(full_path)
            if retval == Result.PASS:
                num_pass.append(module)
            elif retval == Result.FAIL:
                num_fail.append(module)
            print()

    if len(missing) != 0:
        print()
        print_box("Missing", width=60, ch="=")
        print(f"[srlow] {label}: The following targets don't exist:")
        for t in missing:
            print(f"[srlow]   - {t}")
    print()
    print_box(f"{label}ing Complete", width=60, ch="=")
    print(f"[srlow] {label} finished in {time.time()-start_time:.4f} seconds")
    print(f"[srlow] {label}: Number passed - {len(num_pass)}")
    for t in num_pass:
        print(f"[srlow]   - {t}")
    print(f"[srlow] {label}: Number failed - {len(num_fail)}")
    for t in num_fail:
        print(f"[srlow]   - {t}")

    return len(num_fail) + len(missing)


# =================================================================================================
# CORE LOGIC
# =================================================================================================

def build(targets: Optional[list[str]], repo_root: Path, preset: str) -> int:
    """Build every src/ module. Returns the number of failures."""
    return run_over_modules(
        "Build", targets, repo_root, lambda m: configure_and_build(m, preset, repo_root)
    )

def test(targets: Optional[list[str]], repo_root: Path) -> int:
    """Test every src/ module. Returns the number of failures."""
    return run_over_modules("Test", targets, repo_root, test_one)

def analyse(targets: Optional[list[str]], repo_root: Path, preset: str) -> int:
    """Run Understand CodeCheck on every module in src/ or given targets"""
    return run_over_modules("Analyse", targets, repo_root, lambda m: analyse_one(m, preset, repo_root))

def clean(repo_root: Path) -> None:
    """loop through all src/*/. For those with a build/ directory, delete it"""
    res = input("[srlow] Would you like to clean all build/ directories? (y/n): ")
    if res != "y":
        print("[srlow] Cancelling clean..")
        return
    print_box("Cleaning Targets", width=60, ch="=")

    num_pass = []
    num_fail = []
    for module in (repo_root/SRC_DIR).iterdir():
        if not module.is_dir():
            continue

        build_dir = module/"build"
        if not build_dir.exists():
            continue

        print(f"[srlow] Clean: Removing {module.name}/build")
        if safe_rmdir(build_dir):
            num_pass.append(module.name)
        else:
            num_fail.append(module.name)
        print()

    print()
    print_box("Clean Complete", width=60, ch="=")
    print(f"[srlow] Clean: Number removed - {len(num_pass)}")
    for t in num_pass:
        print(f"[srlow]   - {t}")
    print(f"[srlow] Clean: Number failed - {len(num_fail)}")
    for t in num_fail:
        print(f"[srlow]   - {t}")

def parse_args() -> argparse.Namespace:
    """Construct parser and return arguments."""
    parser = argparse.ArgumentParser(
        description="Sunswift low level build and testing tool"
    )
    level1_junction = parser.add_subparsers(dest="command", required=True)

    # common preset flag for srlow build
    build_common = argparse.ArgumentParser(add_help=False)
    build_common.add_argument(
        "--preset", "-p",
        required=True,
        help="CMake preset name (e.g. 'debug', 'release')"
)
    # srlow build...
    command_build = level1_junction.add_parser("build", help="Build and install all or specific modules")
    build_sub = command_build.add_subparsers(dest="build_action", required=True)
    build_sub.add_parser("all", parents=[build_common], help="Build all modules")
    build_sub.add_parser("clean", help="Delete all build/ directories")
    build_target = build_sub.add_parser("target", parents=[build_common], help="Build specific modules")
    build_target.add_argument("targets", nargs="+", help="One or more module names")

    # srlow test...
    command_test = level1_junction.add_parser("test", help="Run Unity unit tests for all or specific modules")
    test_sub = command_test.add_subparsers(dest="test_action", required=True)
    test_sub.add_parser("all", help="Test all modules")
    test_target = test_sub.add_parser("target", help="Test specific modules")
    test_target.add_argument("targets", nargs="+", help="One or more module names")

    # srlow analyse...
    command_analyse = level1_junction.add_parser("analyse", help="Run Scitools und CodeCheck on all or specific modules")
    analyse_sub = command_analyse.add_subparsers(dest="analyse_action", required=True)
    analyse_sub.add_parser("all", parents=[build_common], help="Analyse all modules")
    analyse_target = analyse_sub.add_parser("target", parents=[build_common], help="Analyse specific modules")
    analyse_target.add_argument("targets", nargs="+", help="One or more module names")
    
    return parser.parse_args()

# =================================================================================================
# MAIN
# =================================================================================================
def main() -> int:
    repo_root = find_repo_root(CWD, MARKER_FILE)
    if not (repo_root/SRC_DIR).is_dir():
        die(f"[srlow] src directory not found in {repo_root}")
    args = parse_args()

    failures = 0
    if args.command == "build":
        if args.build_action == "all":
            failures = build(None, repo_root, args.preset)
        elif args.build_action == "clean":
            clean(repo_root)
        elif args.build_action == "target":
            failures = build(args.targets, repo_root, args.preset)
    elif args.command == "test":
        if args.test_action == "all":
            failures = test(None, repo_root)
        elif args.test_action == "target":
            failures = test(args.targets, repo_root)
    elif args.command == "analyse":
        if args.analyse_action == "all":
            failures = analyse(None, repo_root, args.preset)
        elif args.analyse_action == "target":
            failures = analyse(args.targets, repo_root, args.preset)
            

    return 1 if failures else 0

if __name__ == "__main__":
    sys.exit(main())