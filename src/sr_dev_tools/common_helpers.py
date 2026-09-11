"""Common utilities shared by srbuild/srpkg."""

from typing import NoReturn
from pathlib import Path
import logging
import sys

def setup_logging(name: str) -> logging.Logger:
    """Configure root logging and return the top-level logger for 'name'."""
    logging.basicConfig(format="[%(levelname)s] [%(name)s] %(message)s", level=logging.INFO)
    return logging.getLogger(name)

def find_repo_root(cwd: Path, marker_file: str) -> Path:
    """Walk up from `cwd` looking for an empty marker_file.
    Returns the directory containing the marker. Dies if no marker is found in
    `cwd` or any parent directory.
    """
    candidate = cwd.resolve()
    for directory in (candidate, *candidate.parents):
        if (directory / marker_file).exists():
            return directory
    die(
        f"No {marker_file} marker found in '{cwd}' or any parent directory.\n"
        f"This script requires a {marker_file} marker file at the root of your project "
    )

def die(msg: str) -> NoReturn:
    logging.getLogger().error(msg)
    sys.exit(1)

def print_box(text: str, width: int = 60, ch: str = "-") -> None:
    """Print `text` centred inside a bordered box `width` characters wide."""
    print(ch * width)
    print(f"{text}".center(width))
    print(ch * width)
