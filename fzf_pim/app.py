"""Root Textual application for fzf-pim."""

from __future__ import annotations

import os
import subprocess

from textual.app import App

from fzf_pim.screens.scope_screen import ScopeScreen


def _system_is_dark() -> bool:
    """Return True if the system prefers a dark colour scheme."""
    # Freedesktop portal — most reliable cross-DE method
    # Returns: 0 = no preference, 1 = dark, 2 = light
    try:
        result = subprocess.run(
            [
                "dbus-send", "--session",
                "--dest=org.freedesktop.portal.Desktop",
                "--print-reply",
                "/org/freedesktop/portal/desktop",
                "org.freedesktop.portal.Settings.Read",
                "string:org.freedesktop.appearance",
                "string:color-scheme",
            ],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if result.returncode == 0:
            # Output contains "uint32 <value>" — extract last integer
            for token in reversed(result.stdout.split()):
                if token.isdigit():
                    scheme = int(token)
                    if scheme == 1:
                        return True
                    if scheme == 2:
                        return False
                    break  # 0 = no preference, fall through
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # GNOME / colour-scheme setting
    try:
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if result.returncode == 0:
            val = result.stdout.strip().strip("'\"")
            if val == "prefer-dark":
                return True
            if val == "prefer-light":
                return False
            # 'default' means no preference — fall through to gtk-theme
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # GTK theme name (e.g. "Adwaita-dark", "Arc-Dark")
    try:
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if result.returncode == 0 and result.stdout.strip():
            return "dark" in result.stdout.lower()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # KDE plasma
    try:
        result = subprocess.run(
            ["kreadconfig5", "--group", "General", "--key", "ColorScheme"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if result.returncode == 0 and result.stdout.strip():
            return "dark" in result.stdout.lower()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # GTK_THEME env var (e.g. "Adwaita:dark")
    gtk_theme = os.environ.get("GTK_THEME", "")
    if gtk_theme:
        return "dark" in gtk_theme.lower()

    # Default: dark
    return True


class PimApp(App):
    """Azure PIM role activation TUI."""

    CSS_PATH = "app.tcss"
    TITLE = "fzf-pim  ·  Azure PIM"
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, dry_run: bool = False) -> None:
        super().__init__()
        self.dry_run = dry_run
        self.theme = "textual-dark" if _system_is_dark() else "textual-light"

    def on_mount(self) -> None:
        if self.dry_run:
            self.title = "fzf-pim  ·  Azure PIM  [DRY RUN]"
        self.push_screen(ScopeScreen())
