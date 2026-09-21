#!/usr/bin/env python3

###############################################################################
# Sunswift high level static analysis tool
# Author: Claude + Ryan reviewing
#   - Requires a marker file in repo root to know where to search from
#   - Runs Scitools Understand CodeCheck (MISRA C++) over the whole repo
#     using the compile_commands.json produced by srbuild.
# Usage:
#   - sranalyse --linux
#   - sranalyse --qnx <toolchain-file>
###############################################################################

import argparse
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from sr_dev_tools.common_helpers import die, find_repo_root, print_box, setup_logging

logger = logging.getLogger("sranalyse")

# =================================================================================================
# CONSTANTS
# =================================================================================================
CWD = Path.cwd().resolve()
MARKER_FILE = ".sunswift-evsn"
UND_CONFIG_FILE = "misra-cpp2025.json"
UND_DB_NAME = "sranalyse.und"
OUTPUT_DIR_NAME = "analysis"
ANALYSE_GLOBS = [
    "src/**/*.cpp",
    "src/**/*.hpp",
    "core/sr_node/*.cpp",
    "core/sr_node/*.hpp",
]

# =================================================================================================
# HELPERS
# =================================================================================================
def resolve_analyse_globs(repo_root: Path) -> Path:
    """Und's input files do not allow glob, so manually expand ANALYSE_GLOBS. Returns path to temp file with expanded globs"""
    resolved: list[str] = []

    for pattern in ANALYSE_GLOBS:
        try:
            matches = sorted(repo_root.glob(pattern))
        except Exception as e:
            die(f"Analyse: bad glob pattern '{pattern}' - {e}")

        if not matches:
            logger.warning(f"Analyse: glob pattern matched no files: '{pattern}'")
            continue

        resolved.extend(str(m.relative_to(repo_root)) for m in matches if m.is_file())

    if not resolved:
        die("Analyse: ANALYSE_GLOBS resolved to no files")

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    tmp.write("\n".join(resolved) + "\n")
    tmp.close()
    return Path(tmp.name)


# =================================================================================================
# CORE LOGIC
# =================================================================================================
def analyse(repo_root: Path, build_dir_path: Path) -> int:
    """Uses Scitools Understand CLI to run CodeCheck Misra CPP"""
    if not (repo_root/UND_CONFIG_FILE).is_file():
        logger.error(f"Analyse: {str(repo_root/UND_CONFIG_FILE)} not found")
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
        ("settings", ["und", "-db", UND_DB_NAME, "settings", "-C++MacrosAdd", "__GNUC__=15"]),
        ("add",      ["und", "-db", UND_DB_NAME, "add", "-cmake", str(compile_commands)]),
    ]

    for stage, cmd in setup_steps:
        try:
            subprocess.run(cmd, cwd=repo_root, check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"und '{stage}' failed - {e}")
            return 1

    resolved_files = resolve_analyse_globs(repo_root)
    try:
        result = subprocess.run(
            [
                "und", "-db", UND_DB_NAME,
                "codecheck",
                "-files", str(resolved_files),
                "-sarif", f"{OUTPUT_DIR_NAME}/analysis.sarif",
                "-exitstatus",  
                str(repo_root / UND_CONFIG_FILE),
                f"./{OUTPUT_DIR_NAME}",
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


def parse_args() -> argparse.Namespace:
    """Construct parser and return arguments."""
    parser = argparse.ArgumentParser(
        description="Sunswift high level static analysis tool"
    )
    platform_flags = parser.add_mutually_exclusive_group(required=True)
    platform_flags.add_argument("--qnx", metavar="TOOLCHAIN_FILE", help="Analyse the QNX build (path relative to current working directory)")
    platform_flags.add_argument("--linux", action="store_true", help="Analyse the Linux build")
    return parser.parse_args()


# =================================================================================================
# MAIN
# =================================================================================================
def main() -> int:
    setup_logging("sranalyse")
    repo_root = find_repo_root(CWD, MARKER_FILE)
    args = parse_args()

    target_platform = "qnx" if args.qnx else "linux"
    build_dir_path = repo_root / "build" / target_platform

    result = analyse(repo_root, build_dir_path)
    return result


if __name__ == "__main__":
    sys.exit(main())
