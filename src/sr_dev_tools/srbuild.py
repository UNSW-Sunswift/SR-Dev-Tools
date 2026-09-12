#!/usr/bin/env python3

###############################################################################
# Sunswift High Level build tool
# Author: Ryan Wong
#
# Wrapper around CMake to allow you to intuitively build and install all, one, or some targets
#
# Searches for directory upward for MARKER_FILE and assumes root CMakeLists is here
# Usage:
#   - srbuild all (--qnx=<toolchain-file> | --linux)
#   - srbuild target node1 node2 ... (--qnx=<toolchain-file> | --linux)
#   - srbuild clean
###############################################################################

import argparse
import subprocess
import time
import shutil
from typing import Optional
from pathlib import Path
from dataclasses import dataclass
from sr_dev_tools.common_helpers import die, find_repo_root, print_box

# =================================================================================================
# CONSTANTS
# =================================================================================================

CWD = Path.cwd().resolve()
# Change these if either change
INSTALL_FOLDER_NAME = "deploy"
MARKER_FILE = ".sunswift-evsn"

@dataclass
class BuildData:
    build_root: Path  # dir containing the .sunswift-evsn marker; expected to also contain CMakeLists.txt
    build_dir_path: Path
    install_prefix: Path
    cmakelists_path: Path
    target_platform: str  # e.g. "qnx", "linux", or "native"
    toolchain_path: Optional[Path]  # absolute path to CMake toolchain file, or None for native

# =================================================================================================
# HELPERS
# =================================================================================================

def safe_rmdir(path: Path, build_root: Path) -> bool:
    """Absolutely every error check again just to confirm before deletion.
    In case any bugs in error checking happen before. Then deletes specified dir.
    """
    if not path.exists():
        print("[srbuild] Clean: Path does not exist")
        return False

    if not path.is_dir():
        print("[srbuild] Clean: Path is not a directory")
        return False

    if path.is_symlink():
        print("[srbuild] Clean: Path is a symlink")
        return False

    try:
        path.relative_to(build_root)
    except ValueError:
        print("[srbuild] Clean: Path is not within build root")
        return False

    if path == build_root or path == Path("/"):
        die("[srbuild] wtf are u doing man")

    shutil.rmtree(path)
    return True


# =================================================================================================
# CORE LOGIC
# =================================================================================================

def configure_cmake(build_data: BuildData) -> None:
    """Creates the build directory if it doesn't exist, and configures cmake
    using build_data.cmakelists_path. Specifies install prefix as
    build_data.install_prefix.

    Args:
        build_data (BuildData)
    """

    print_box("CMake Initialisation", width=60, ch="=")
    print(f"[srbuild] TARGET PLATFORM: {build_data.target_platform}")
    # CMakeLists.txt at build root MUST exist. Makes build dir if does not exist
    if not (build_data.cmakelists_path.exists() and build_data.cmakelists_path.is_file()):
        die(
            f"[srbuild] Build: No CMakeLists.txt found at build root '{build_data.build_root}' "
            f"(the directory containing your {MARKER_FILE} marker)."
        )
    if not (build_data.build_dir_path.exists() and build_data.build_dir_path.is_dir()):
        print("[srbuild] Build: Build directory not found, creating build directory")
        try:
            build_data.build_dir_path.mkdir(parents=True)
        except Exception as e:
            die(f"[srbuild] Error: Failed to create build directory: {e}")

    # Re-init cmake
    cmd = [
        "cmake",
        "-S",
        str(build_data.build_root),
        "-B",
        str(build_data.build_dir_path),
        f"-DCMAKE_INSTALL_PREFIX={build_data.install_prefix}"
    ]

    if build_data.toolchain_path is not None:
        cmd.append(f"-DCMAKE_TOOLCHAIN_FILE={build_data.toolchain_path}")

    try:
        print("[srbuild] Build: Initialising CMake")
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        die(f"[srbuild] Build: Error configuring CMake: {e}")


def build(targets: Optional[list[str]], build_data: BuildData, jobs: int) -> None:
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
    # Build targets
    try:
        if targets is None:
            print("[srbuild] Build: Building all targets")
            subprocess.run([
                "cmake", "--build", str(build_data.build_dir_path), "-j", jobs_str
            ], check=True)
        else:
            print("[srbuild] Build: Building specified targets")
            # Uhh loop is probably less efficient, but the alternative is messy
            # If someone is using --target, build times probably tiny anyway
            for target in targets:
                subprocess.run([
                    "cmake", "--build", str(build_data.build_dir_path), "--target", target, "-j", jobs_str
                ], check=True)
    except subprocess.CalledProcessError:
        die("[srbuild] Build: Error building targets")

    print()
    print_box("Build Complete", width=60, ch="=")
    end_time = time.time()
    print(f"[srbuild] Build finished in {end_time-start_time:.4f} seconds")

def install(targets: Optional[list[str]], build_data: BuildData) -> None:
    """Calls cmake --install <build_dir> to install bins into <install_prefix>

    Args:
        targets (Optional[list[str]]): none if all targets, else list of targets
        build_data (BuildData):
    """
    print()
    print_box("Installing Targets", width=60, ch="=")
    start_time = time.time()
    # Install targets
    try:
        if targets is None:
            print("[srbuild] Install: Installing all targets")
            subprocess.run([
                "cmake", "--install", str(build_data.build_dir_path)
            ], check=True)
        else:
            print("[srbuild] Install: Installing specified targets")
            for target in targets:
                subprocess.run([
                    "cmake", "--install", str(build_data.build_dir_path), "--component", target
                ], check=True)

        # No matter what, always install runtime tools
        subprocess.run([
            "cmake", "--install", str(build_data.build_dir_path), "--component", "tools"
        ], check=True)
    except subprocess.CalledProcessError:
        die("[srbuild] Build: Error installing targets")


    print()
    print_box("Install Complete", width=60, ch="=")
    end_time = time.time()
    print(f"[srbuild] Install finished in {end_time-start_time:.4f} seconds")

def clean(build_data: BuildData) -> None:
    """Deletes the entire build/ directory under build_data.build_root."""
    print_box("Cleaning Targets", width=60, ch="=")
    path = build_data.build_root / "build"
    res = input(f"[srbuild] Would you like to remove {path}? (y/n): ")
    if res.lower() != "y":
        die("[srbuild] Cancelling clean..")

    if path.exists() and path.is_dir():
        print(f"[srbuild] Clean: Removing '{path}'")
        ret = safe_rmdir(path, build_data.build_root)
        if ret:
            print(f"[srbuild] Clean: '{path}' removed successfully.")
    else:
        print(f"[srbuild] Clean: {path} does not exist")

    print()
    print_box("Clean Complete", width=60, ch="=")

def build_all(jobs: int, build_data: BuildData) -> None:
    """Configure, build, and install all targets."""
    configure_cmake(build_data)
    build(None, build_data, jobs)
    install(None, build_data)

def build_target(targets: list[str], jobs: int, build_data: BuildData) -> None:
    """Configure, build, and install the specified targets."""
    configure_cmake(build_data)
    build(targets, build_data, jobs)
    install(targets, build_data)

def parse_args() -> argparse.Namespace:
    """Construct parser and return arguments."""
    parser = argparse.ArgumentParser(
        description="Sunswift build and staging tool"
    )

    common_flags = argparse.ArgumentParser(add_help=False)
    common_flags.add_argument("--jobs", "-j", default=8, type=int, help="Number of parallel jobs Make runs. Default=8")
    platform_flags = common_flags.add_mutually_exclusive_group(required=True)
    platform_flags.add_argument("--qnx", metavar="TOOLCHAIN_FILE", help="Build QNX packages using the given CMake toolchain file (path relative to current working directory)")
    platform_flags.add_argument("--linux", action="store_true", help="Build Linux packages")

    level1_junction = parser.add_subparsers(dest="command", required=True)
    level1_junction.add_parser("all", parents=[common_flags], help="Build and install all targets")
    level1_junction.add_parser("clean", help="Delete build directories (both by default), but NOT deploy/")
    command_target = level1_junction.add_parser("target", parents=[common_flags], help="Select specific targets to build and install")
    command_target.add_argument("targets", nargs="+", help="One or more target names")
    return parser.parse_args()

# =================================================================================================
# MAIN
# =================================================================================================


def main():
    # build_root: nearest ancestor of CWD containing a .sunswift-evsn marker (dies if none found)
    build_root = find_repo_root(CWD, MARKER_FILE)
    args = parse_args()

    if getattr(args, "qnx", None):
        target_platform = "qnx"
        toolchain_path = (CWD / args.qnx).resolve()
    else:
        target_platform = "linux"
        toolchain_path = None

    build_dir_path = build_root / "build" / target_platform
    cmakelists_path = build_root / "CMakeLists.txt"
    install_prefix = build_root / INSTALL_FOLDER_NAME / target_platform
    build_data = BuildData(build_root, build_dir_path, install_prefix, cmakelists_path, target_platform, toolchain_path)

    if args.command == "all":
        build_all(args.jobs, build_data)
    elif args.command == "target":
        build_target(args.targets, args.jobs, build_data)
    elif args.command == "clean":
        clean(build_data)

if __name__ == "__main__":
    main()
