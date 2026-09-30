"""ANSI colors for CLI output.

Color is on when stdout is a TTY, unless NO_COLOR is set. FORCE_COLOR overrides
the TTY check so piped or test output can still be colored.
"""

import os
import sys

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
BRIGHT_RED = "\033[91m"
BRIGHT_GREEN = "\033[92m"
BRIGHT_YELLOW = "\033[93m"
BRIGHT_BLUE = "\033[94m"
BRIGHT_MAGENTA = "\033[95m"
BRIGHT_CYAN = "\033[96m"


def enabled() -> bool:
    """Return True when ANSI color codes should be emitted."""
    if os.environ.get("NO_COLOR"):
        return False
    force = os.environ.get("FORCE_COLOR")
    if force is not None:
        return force not in ("0", "false", "False", "")
    return sys.stdout.isatty()


def paint(text: str, *codes: str) -> str:
    """Wrap text in ANSI codes when color is enabled."""
    if not text or not codes or not enabled():
        return text
    return f"{''.join(codes)}{text}{RESET}"
