from __future__ import annotations

import ctypes
import json
import os
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk
import winreg


@dataclass(frozen=True)
class Palette:
    window: str
    surface: str
    surface_alt: str
    text: str
    text_secondary: str
    disabled: str
    border: str
    accent: str
    accent_text: str
    selection: str
    selection_text: str


PALETTES = {
    "light": Palette("#F0F0F0", "#FFFFFF", "#E5E5E5", "#000000", "#3A3A3A", "#767676", "#707070", "#0067C0", "#FFFFFF", "#0067C0", "#FFFFFF"),
    "dark": Palette("#202020", "#2B2B2B", "#333333", "#FFFFFF", "#C8C8C8", "#969696", "#6E6E6E", "#4CC2FF", "#000000", "#2D6BB5", "#FFFFFF"),
    "dark_dim": Palette("#181818", "#222222", "#2A2A2A", "#E6E6E6", "#BBBBBB", "#888888", "#666666", "#60CDFF", "#000000", "#245A91", "#FFFFFF"),
    "dark_high_contrast": Palette("#000000", "#000000", "#161616", "#FFFFFF", "#FFFFFF", "#BDBDBD", "#FFFFFF", "#FFFF00", "#000000", "#005A9E", "#FFFFFF"),
}


def windows_high_contrast() -> bool:
    class HIGHCONTRAST(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwFlags", ctypes.c_uint), ("lpszDefaultScheme", ctypes.c_wchar_p)]

    info = HIGHCONTRAST()
    info.cbSize = ctypes.sizeof(info)
    try:
        ok = ctypes.windll.user32.SystemParametersInfoW(0x0042, info.cbSize, ctypes.byref(info), 0)
        return bool(ok and info.dwFlags & 0x00000001)
    except (AttributeError, OSError):
        return False


def windows_apps_use_dark() -> bool:
    try:
        path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return not bool(value)
    except OSError:
        return False


class ThemeManager:
    MODES = ("system", "light", "dark", "dark_dim", "dark_high_contrast")

    def __init__(self, root: tk.Tk, settings_path: str | os.PathLike[str] | None = None) -> None:
        self.root = root
        self.style = ttk.Style(root)
        self.native_ttk_theme = self.style.theme_use()
        if settings_path is None:
            base = Path(os.environ.get("APPDATA", Path.home())) / "QuickEdit"
            settings_path = base / "settings.json"
        self.settings_path = Path(settings_path)
        self.mode = self.load_mode()
        self.resolved_mode = ""

    def load_mode(self) -> str:
        try:
            value = json.loads(self.settings_path.read_text(encoding="utf-8")).get("theme_mode", "system")
            return value if value in self.MODES else "system"
        except (OSError, ValueError, TypeError):
            return "system"

    def save_mode(self, mode: str) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            pass
        data["theme_mode"] = mode
        self.settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def set_mode(self, mode: str) -> None:
        if mode not in self.MODES:
            raise ValueError(f"Unknown theme mode: {mode}")
        self.mode = mode
        self.save_mode(mode)
        self.apply()

    def resolve_mode(self) -> str:
        if windows_high_contrast():
            return "windows_high_contrast"
        if self.mode == "system":
            return "dark" if windows_apps_use_dark() else "light"
        return self.mode

    def apply(self) -> str:
        resolved = self.resolve_mode()
        self.resolved_mode = resolved
        if resolved == "windows_high_contrast":
            self._apply_windows_colors()
            self._dark_titlebar(False)
        else:
            self._apply_palette(PALETTES[resolved])
            self._dark_titlebar(resolved.startswith("dark"))
        self.apply_tree(self.root)
        return resolved

    def _configure_ttk(self, palette: Palette) -> None:
        if self.style.theme_use() != "clam":
            self.style.theme_use("clam")
        self.style.configure(".", background=palette.window, foreground=palette.text)
        self.style.configure("TFrame", background=palette.window)
        self.style.configure("TLabel", background=palette.window, foreground=palette.text)
        self.style.configure("TButton", background=palette.surface_alt, foreground=palette.text, bordercolor=palette.border, focuscolor=palette.accent)
        self.style.configure("TCheckbutton", background=palette.window, foreground=palette.text, focuscolor=palette.accent)
        self.style.configure("TEntry", fieldbackground=palette.surface, foreground=palette.text, insertcolor=palette.text, bordercolor=palette.border)
        for name in ("TButton", "TCheckbutton"):
            self.style.map(name, background=[("active", palette.selection)], foreground=[("disabled", palette.disabled), ("active", palette.selection_text)])

    def _apply_palette(self, palette: Palette) -> None:
        self.root.configure(background=palette.window)
        self._configure_ttk(palette)
        self._active_palette = palette

    def _apply_windows_colors(self) -> None:
        palette = Palette("SystemButtonFace", "SystemWindow", "SystemButtonFace", "SystemButtonText", "SystemButtonText", "SystemGrayText", "SystemWindowText", "SystemHighlight", "SystemHighlightText", "SystemHighlight", "SystemHighlightText")
        try:
            self.style.theme_use(self.native_ttk_theme)
        except tk.TclError:
            pass
        self.root.configure(background=palette.window)
        self._active_palette = palette

    def apply_tree(self, widget: tk.Misc) -> None:
        palette = getattr(self, "_active_palette", PALETTES["light"])
        self.apply_widget(widget, palette)
        for child in widget.winfo_children():
            self.apply_tree(child)

    @staticmethod
    def apply_widget(widget: tk.Misc, palette: Palette) -> None:
        try:
            if isinstance(widget, tk.Menu):
                widget.configure(background=palette.surface, foreground=palette.text, activebackground=palette.selection, activeforeground=palette.selection_text)
            elif isinstance(widget, tk.Listbox):
                widget.configure(background=palette.surface, foreground=palette.text, selectbackground=palette.selection, selectforeground=palette.selection_text, highlightbackground=palette.border, highlightcolor=palette.accent)
            elif isinstance(widget, tk.Label):
                widget.configure(background=palette.window, foreground=palette.text, highlightcolor=palette.accent)
            elif isinstance(widget, (tk.Frame, tk.Toplevel)):
                widget.configure(background=palette.window)
        except tk.TclError:
            pass

    def _dark_titlebar(self, enabled: bool) -> None:
        try:
            self.root.update_idletasks()
            value = ctypes.c_int(1 if enabled else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(self.root.winfo_id(), 20, ctypes.byref(value), ctypes.sizeof(value))
        except (AttributeError, OSError, tk.TclError):
            pass
