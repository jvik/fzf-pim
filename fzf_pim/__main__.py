"""Entry point for fzf-pim."""

from __future__ import annotations

import argparse

from fzf_pim.app import PimApp


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="fzf-pim",
        description="TUI for activating Azure PIM eligible roles with multiselect.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate activation without calling the Azure API.",
    )
    args = parser.parse_args()
    PimApp(dry_run=args.dry_run).run()


if __name__ == "__main__":
    main()
