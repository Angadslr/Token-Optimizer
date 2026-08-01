"""Run with `slashtoken benchmark`; retained as a discoverable repository entry point."""

from __future__ import annotations

import sys

from slashtoken.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["benchmark", *sys.argv[1:]]))
