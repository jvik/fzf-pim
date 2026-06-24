"""Root Textual application for fzf-pim."""

from __future__ import annotations

from textual.app import App

from fzf_pim.screens.scope_screen import ScopeScreen


class PimApp(App):
    """Azure PIM role activation TUI."""

    CSS_PATH = "app.tcss"
    TITLE = "fzf-pim  ·  Azure PIM"
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, dry_run: bool = False) -> None:
        super().__init__()
        self.dry_run = dry_run

    def on_mount(self) -> None:
        if self.dry_run:
            self.title = "fzf-pim  ·  Azure PIM  [DRY RUN]"
        self.push_screen(ScopeScreen())
