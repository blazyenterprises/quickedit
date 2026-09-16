from __future__ import annotations

import copy
import ctypes
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, messagebox, simpledialog, ttk
import wave
import winsound

from media_backend import AudioDevice, MediaBackend, MediaError
from online_backend import OnlineBackend, OnlineResult
from credential_store import CredentialStore
from theme_manager import ThemeManager
import audio_effects
import signal_generator
from soundfont_tools import Preset, list_presets, one_note_midi

# PyInstaller's Tk hook still points Python 3.14 at pre-3.14 library folders.
# Tcl/Tk 9 carries its standard library in zipfs, so let it use that default.
if getattr(sys, "frozen", False) and sys.version_info >= (3, 14):
    os.environ.pop("TCL_LIBRARY", None)
    os.environ.pop("TK_LIBRARY", None)


def application_dir() -> str:
    """Return the directory containing bundled runtime resources."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


class ScreenReaderAnnouncer:
    """Speak through NVDA when its controller client is available."""

    def __init__(self) -> None:
        app_dir = application_dir()
        candidates = (
            os.path.join(app_dir, "nvdaControllerClient64.dll"),
            os.path.normpath(
                os.path.join(
                    app_dir,
                    "..",
                    "work",
                    "quickedit",
                    "apricot-player",
                    "ApricotPlayer",
                    "_internal",
                    "nvda",
                    "nvdaControllerClient64.dll",
                )
            ),
        )
        self.client = None
        for path in candidates:
            if os.path.isfile(path):
                try:
                    self.client = ctypes.WinDLL(path)
                    self.client.nvdaController_speakText.argtypes = [ctypes.c_wchar_p]
                    self.client.nvdaController_speakText.restype = ctypes.c_int
                    self.client.nvdaController_cancelSpeech.restype = ctypes.c_int
                    break
                except (OSError, AttributeError):
                    self.client = None

    def speak(self, message: str) -> None:
        if not self.client:
            return
        try:
            self.client.nvdaController_cancelSpeech()
            self.client.nvdaController_speakText(message)
        except (OSError, AttributeError):
            self.client = None


def format_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int(seconds % 3600 // 60)
    whole = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis == 1000:
        whole += 1
        millis = 0
    if hours:
        return f"{hours}:{minutes:02d}:{whole:02d}.{millis:03d}"
    return f"{minutes}:{whole:02d}.{millis:03d}"


def parse_time(value: str) -> float:
    parts = [part.strip() for part in value.strip().split(":")]
    if not parts or len(parts) > 3 or any(not part for part in parts):
        raise ValueError("Enter seconds, minutes:seconds, or hours:minutes:seconds.")
    try:
        numbers = [float(part) for part in parts]
    except ValueError as exc:
        raise ValueError("Time must contain numbers.") from exc
    if any(number < 0 for number in numbers):
        raise ValueError("Time cannot be negative.")
    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60 + number
    return seconds


def next_prefix_index(names: list[str], current: int, prefix: str) -> int | None:
    """Find the next matching name, wrapping around after the current item."""
    if not names or not prefix:
        return None
    prefix = prefix.casefold()
    for offset in range(1, len(names) + 1):
        index = (current + offset) % len(names)
        if names[index].casefold().startswith(prefix):
            return index
    return None


@dataclass
class AudioDocument:
    channels: int
    sample_width: int
    frame_rate: int
    frames: bytes
    source_path: str
    save_path: str | None = None
    midi_path: str | None = None
    soundfont_path: str | None = None
    cursor_frame: int = 0
    selection_start: int | None = None
    selection_end: int | None = None

    @property
    def frame_size(self) -> int:
        return self.channels * self.sample_width

    @property
    def frame_count(self) -> int:
        return len(self.frames) // self.frame_size

    @property
    def duration(self) -> float:
        return self.frame_count / self.frame_rate

    def frame_at(self, seconds: float) -> int:
        return max(0, min(self.frame_count, round(seconds * self.frame_rate)))

    def seconds_at(self, frame: int) -> float:
        return frame / self.frame_rate

    def selection(self) -> tuple[int, int] | None:
        if self.selection_start is None or self.selection_end is None:
            return None
        start, end = sorted((self.selection_start, self.selection_end))
        return (start, end) if start != end else None

    def slice_bytes(self, start: int, end: int) -> bytes:
        return self.frames[start * self.frame_size : end * self.frame_size]

    def reversed_bytes(self, start: int = 0, end: int | None = None) -> bytes:
        """Reverse complete sample frames while preserving bytes within each frame."""
        if end is None:
            end = self.frame_count
        source = self.slice_bytes(start, end)
        size = self.frame_size
        result = bytearray(len(source))
        for byte_offset in range(size):
            result[byte_offset::size] = source[byte_offset::size][::-1]
        return bytes(result)


class QuickEdit(tk.Tk):
    BUILTIN_EFFECT_PRESETS = {
        "Amplify or Reduce Volume": {"Whisper": {"db": -24}, "Very Quiet": {"db": -18}, "Quiet": {"db": -12}, "Half Volume": {"db": -6}, "Slight Cut": {"db": -3}, "Slight Boost": {"db": 3}, "Strong Boost": {"db": 6}, "Double Volume": {"db": 9}, "Huge Boost": {"db": 15}, "Maximum Boost": {"db": 24}},
        "Echo": {"Tiny Reflection": {"delay": 35, "feedback": 8, "wet": 12}, "Slapback": {"delay": 90, "feedback": 18, "wet": 30}, "Rockabilly": {"delay": 125, "feedback": 24, "wet": 38}, "Bathroom": {"delay": 55, "feedback": 42, "wet": 32}, "Vocal Delay": {"delay": 220, "feedback": 25, "wet": 28}, "Quarter Note Feel": {"delay": 375, "feedback": 38, "wet": 40}, "Deep Echo": {"delay": 430, "feedback": 58, "wet": 52}, "Canyon": {"delay": 720, "feedback": 68, "wet": 62}, "Space Transmission": {"delay": 1100, "feedback": 75, "wet": 72}, "Infinite-ish": {"delay": 650, "feedback": 92, "wet": 82}},
        "Room Reverb": {"Closet": {"wet": 12, "size": 18, "decay": 18}, "Studio Booth": {"wet": 18, "size": 24, "decay": 24}, "Small Room": {"wet": 25, "size": 32, "decay": 32}, "Bedroom": {"wet": 30, "size": 40, "decay": 38}, "Live Room": {"wet": 38, "size": 50, "decay": 48}, "Large Room": {"wet": 48, "size": 62, "decay": 58}, "Auditorium": {"wet": 58, "size": 74, "decay": 68}, "Concert Hall": {"wet": 70, "size": 88, "decay": 82}, "Cathedral": {"wet": 82, "size": 100, "decay": 92}, "Bottomless Cathedral": {"wet": 100, "size": 100, "decay": 98}},
        "Flanger": {"Barely There": {"rate": .08, "depth": 1, "wet": 15}, "Gentle Sweep": {"rate": .18, "depth": 2, "wet": 32}, "Slow Wide": {"rate": .1, "depth": 8, "wet": 52}, "Classic": {"rate": .35, "depth": 5, "wet": 50}, "Stereo Dream": {"rate": .22, "depth": 10, "wet": 58}, "Jet Sweep": {"rate": .7, "depth": 8, "wet": 70}, "Fast Jet": {"rate": 1.5, "depth": 6, "wet": 75}, "Metallic": {"rate": 3, "depth": 2, "wet": 80}, "Underwater": {"rate": .12, "depth": 18, "wet": 72}, "Extreme": {"rate": 6, "depth": 25, "wet": 95}},
        "Chorus": {"Subtle Widening": {"wet": 12}, "Light Chorus": {"wet": 25}, "Acoustic Double": {"wet": 35}, "Vocal Double": {"wet": 42}, "Classic Chorus": {"wet": 50}, "Wide Chorus": {"wet": 65}, "Eighties": {"wet": 72}, "Dreamy": {"wet": 80}, "Underwater Ensemble": {"wet": 90}, "Maximum Swarm": {"wet": 100}},
        "Noise Gate": {"Breath Friendly": {"threshold": -55, "attack": 12, "release": 300}, "Gentle Voice": {"threshold": -48, "attack": 8, "release": 220}, "Voice Gate": {"threshold": -42, "attack": 5, "release": 120}, "Podcast": {"threshold": -38, "attack": 4, "release": 160}, "Studio": {"threshold": -35, "attack": 3, "release": 100}, "Drum Cleanup": {"threshold": -30, "attack": 1, "release": 70}, "Hard Gate": {"threshold": -28, "attack": 1, "release": 45}, "Choppy": {"threshold": -24, "attack": 0, "release": 20}, "Sustained": {"threshold": -40, "attack": 15, "release": 800}, "Extreme Cut": {"threshold": -18, "attack": 0, "release": 10}},
        "Noise Reduction": {"Barely There": {"strength": 10}, "Gentle Cleanup": {"strength": 25}, "Light Hiss": {"strength": 35}, "Room Noise": {"strength": 45}, "Voice Recording": {"strength": 55}, "Moderate": {"strength": 65}, "Strong Cleanup": {"strength": 75}, "Heavy Hiss": {"strength": 85}, "Rescue": {"strength": 92}, "Maximum": {"strength": 100}},
        "Vinyl Click and Crackle Removal": {"Gentle Vinyl": {"sensitivity": 20, "passes": 1, "burst": 1}, "Normal Vinyl": {"sensitivity": 35, "passes": 1, "burst": 2}, "Old LP": {"sensitivity": 45, "passes": 2, "burst": 2}, "Frequent Clicks": {"sensitivity": 55, "passes": 2, "burst": 3}, "Light Crackle": {"sensitivity": 60, "passes": 3, "burst": 3}, "Heavy Crackle": {"sensitivity": 70, "passes": 3, "burst": 4}, "Shellac 78": {"sensitivity": 75, "passes": 4, "burst": 5}, "SuperScan Four Pass": {"sensitivity": 65, "passes": 4, "burst": 4}, "SuperScan Five Pass": {"sensitivity": 72, "passes": 5, "burst": 5}, "Extreme Rescue": {"sensitivity": 90, "passes": 5, "burst": 8}},
        "Tape Hiss Reduction": {"Barely There": {"reduction": 3, "floor": -65}, "Gentle Cassette": {"reduction": 6, "floor": -60}, "Normal Cassette": {"reduction": 10, "floor": -55}, "Chrome Tape": {"reduction": 12, "floor": -58}, "Reel to Reel": {"reduction": 14, "floor": -62}, "Old Cassette": {"reduction": 18, "floor": -52}, "Heavy Hiss": {"reduction": 24, "floor": -48}, "Very Heavy Hiss": {"reduction": 32, "floor": -44}, "Rescue": {"reduction": 45, "floor": -40}, "Maximum": {"reduction": 60, "floor": -35}},
        "Add Tape Hiss": {"Fresh Cassette": {"level": -48, "color": 45}, "Quiet Cassette": {"level": -42, "color": 50}, "Normal Cassette": {"level": -36, "color": 55}, "Cheap Tape": {"level": -31, "color": 62}, "Old Cassette": {"level": -28, "color": 68}, "Reel to Reel": {"level": -40, "color": 35}, "VHS Hi-Fi": {"level": -44, "color": 58}, "Dictation Recorder": {"level": -25, "color": 75}, "Damaged Tape": {"level": -20, "color": 82}, "Hiss Apocalypse": {"level": -12, "color": 90}},
        "Add Vinyl Crackle": {"Clean LP": {"density": 5, "level": -36}, "Occasional Dust": {"density": 12, "level": -30}, "Normal LP": {"density": 20, "level": -26}, "Used Record": {"density": 32, "level": -22}, "Old Vinyl": {"density": 45, "level": -19}, "Scratchy LP": {"density": 58, "level": -16}, "Thrift Store": {"density": 68, "level": -14}, "Shellac 78": {"density": 78, "level": -12}, "Ruined Record": {"density": 90, "level": -8}, "Crackle Apocalypse": {"density": 100, "level": -4}},
        "Low-Pass Filter": {"Air Trim": {"cutoff": 18000}, "Gentle Warmth": {"cutoff": 14000}, "Warm": {"cutoff": 10000}, "Dark": {"cutoff": 7000}, "Old Radio": {"cutoff": 4500}, "Telephone High Cut": {"cutoff": 3400}, "Muffled": {"cutoff": 2200}, "Behind a Wall": {"cutoff": 1200}, "Deep Underwater": {"cutoff": 600}, "Sub Bass Only": {"cutoff": 180}},
        "High-Pass Filter": {"Remove Rumble": {"cutoff": 30}, "Voice Rumble Cut": {"cutoff": 70}, "Podcast": {"cutoff": 90}, "Thin Mix": {"cutoff": 180}, "Small Speaker": {"cutoff": 350}, "Telephone Low Cut": {"cutoff": 500}, "Tinny": {"cutoff": 1000}, "No Bass": {"cutoff": 2000}, "Treble Only": {"cutoff": 5000}, "Extreme": {"cutoff": 10000}},
        "Compressor": {"Transparent": {"threshold": -10, "ratio": 1.5, "attack": 30, "release": 250}, "Gentle": {"threshold": -14, "ratio": 2, "attack": 20, "release": 180}, "Vocal Smooth": {"threshold": -18, "ratio": 3, "attack": 12, "release": 160}, "Voice Leveler": {"threshold": -22, "ratio": 4, "attack": 8, "release": 120}, "Podcast Firm": {"threshold": -24, "ratio": 5, "attack": 5, "release": 100}, "Drum Punch": {"threshold": -12, "ratio": 6, "attack": 25, "release": 80}, "Bass Control": {"threshold": -18, "ratio": 7, "attack": 10, "release": 140}, "Broadcast": {"threshold": -28, "ratio": 8, "attack": 3, "release": 80}, "Heavy": {"threshold": -32, "ratio": 12, "attack": 2, "release": 60}, "Brick Wall": {"threshold": -36, "ratio": 100, "attack": .1, "release": 40}},
        "Expander": {"Gentle Cleanup": {"threshold": -50, "ratio": 1.5, "attack": 15, "release": 250}, "Voice Room Tone": {"threshold": -45, "ratio": 2, "attack": 10, "release": 220}, "Podcast": {"threshold": -40, "ratio": 2.5, "attack": 8, "release": 180}, "Music Gentle": {"threshold": -48, "ratio": 1.8, "attack": 25, "release": 350}, "Drum Separation": {"threshold": -32, "ratio": 4, "attack": 2, "release": 100}, "Cassette Cleanup": {"threshold": -42, "ratio": 3, "attack": 12, "release": 280}, "Strong": {"threshold": -36, "ratio": 6, "attack": 5, "release": 140}, "Very Strong": {"threshold": -30, "ratio": 10, "attack": 2, "release": 80}, "Choppy": {"threshold": -24, "ratio": 15, "attack": 1, "release": 40}, "Extreme": {"threshold": -18, "ratio": 20, "attack": .1, "release": 15}},
        "Limiter": {"Safety Ceiling": {"ceiling": -1, "attack": 5, "release": 80}, "Streaming Safe": {"ceiling": -1.5, "attack": 8, "release": 120}, "Transparent": {"ceiling": -.3, "attack": 20, "release": 250}, "Vocal Peak Catcher": {"ceiling": -2, "attack": 3, "release": 100}, "Podcast": {"ceiling": -1, "attack": 10, "release": 180}, "Drum Peaks": {"ceiling": -.5, "attack": 1, "release": 50}, "Firm": {"ceiling": -3, "attack": 5, "release": 100}, "Loud": {"ceiling": -6, "attack": 2, "release": 60}, "Crushed": {"ceiling": -10, "attack": 1, "release": 30}, "Brick Wall": {"ceiling": -12, "attack": .1, "release": 10}},
        "Band-Pass Filter": {"Full Midrange": {"frequency": 1500, "q": .5}, "Wide Voice": {"frequency": 1800, "q": .8}, "Telephone": {"frequency": 1700, "q": 1.2}, "AM Radio": {"frequency": 2200, "q": 1}, "Megaphone": {"frequency": 1200, "q": 2}, "Nasal": {"frequency": 900, "q": 4}, "Presence": {"frequency": 3500, "q": 3}, "Bass Focus": {"frequency": 180, "q": 2}, "Treble Whistle": {"frequency": 8000, "q": 6}, "Extreme Narrow": {"frequency": 1000, "q": 15}},
        "Notch Filter": {"Power Hum 50 Hz": {"frequency": 50, "q": 12}, "Power Hum 60 Hz": {"frequency": 60, "q": 12}, "Hum Harmonic 100 Hz": {"frequency": 100, "q": 14}, "Hum Harmonic 120 Hz": {"frequency": 120, "q": 14}, "Whistle 1 kHz": {"frequency": 1000, "q": 20}, "Whistle 2 kHz": {"frequency": 2000, "q": 20}, "Whistle 4 kHz": {"frequency": 4000, "q": 20}, "Feedback 6 kHz": {"frequency": 6000, "q": 25}, "Broad Mid Cut": {"frequency": 1500, "q": 1}, "Surgical": {"frequency": 3000, "q": 50}},
        "Graphic Equalizer": {"Bass Boost": {"b60": 8, "b250": 4, "b1000": 0, "b4000": 0, "b12000": -1}, "Treble Boost": {"b60": -1, "b250": 0, "b1000": 0, "b4000": 4, "b12000": 8}, "Smile": {"b60": 6, "b250": 3, "b1000": -2, "b4000": 3, "b12000": 6}, "Voice Clarity": {"b60": -6, "b250": -2, "b1000": 2, "b4000": 5, "b12000": 2}, "Podcast": {"b60": -8, "b250": 1, "b1000": 3, "b4000": 3, "b12000": -2}, "Warm": {"b60": 4, "b250": 3, "b1000": 1, "b4000": -1, "b12000": -3}, "Bright": {"b60": -3, "b250": -1, "b1000": 1, "b4000": 4, "b12000": 6}, "Lo-Fi": {"b60": -8, "b250": 3, "b1000": 4, "b4000": -1, "b12000": -10}, "Telephone": {"b60": -18, "b250": -8, "b1000": 5, "b4000": 3, "b12000": -18}, "Extreme V": {"b60": 15, "b250": 8, "b1000": -10, "b4000": 8, "b12000": 15}},
        "Parametric Equalizer": {"Voice Presence": {"frequency": 3500, "gain": 4, "q": 1.2}, "Remove Mud": {"frequency": 300, "gain": -5, "q": 1.4}, "Remove Boxiness": {"frequency": 600, "gain": -4, "q": 2}, "Add Warmth": {"frequency": 180, "gain": 4, "q": .8}, "Bass Punch": {"frequency": 90, "gain": 6, "q": 1.1}, "Air": {"frequency": 12000, "gain": 5, "q": .7}, "Tame Harshness": {"frequency": 4500, "gain": -5, "q": 2.5}, "Nasal Cut": {"frequency": 1000, "gain": -6, "q": 3}, "Surgical Cut": {"frequency": 2500, "gain": -15, "q": 12}, "Resonant Boost": {"frequency": 2000, "gain": 12, "q": 8}},
        "De-Esser": {"Gentle Voice": {"intensity": 25, "maximum": 35, "frequency": 55}, "Male Voice": {"intensity": 40, "maximum": 50, "frequency": 42}, "Female Voice": {"intensity": 45, "maximum": 55, "frequency": 65}, "Podcast": {"intensity": 50, "maximum": 60, "frequency": 60}, "Bright Mic": {"intensity": 58, "maximum": 65, "frequency": 70}, "Sharp S Sounds": {"intensity": 65, "maximum": 75, "frequency": 62}, "Strong": {"intensity": 72, "maximum": 80, "frequency": 60}, "Very Strong": {"intensity": 82, "maximum": 90, "frequency": 65}, "High Frequency Only": {"intensity": 65, "maximum": 75, "frequency": 85}, "Maximum": {"intensity": 100, "maximum": 100, "frequency": 65}},
        "Bass and Treble": {"Gentle Warmth": {"bass": 3, "treble": -1}, "Bass Boost": {"bass": 6, "treble": 0}, "Huge Bass": {"bass": 12, "treble": -2}, "Gentle Clarity": {"bass": 0, "treble": 3}, "Treble Boost": {"bass": 0, "treble": 6}, "Bright": {"bass": -2, "treble": 10}, "Smile Curve": {"bass": 6, "treble": 6}, "Mid Focus": {"bass": -4, "treble": -4}, "Telephone": {"bass": -12, "treble": 8}, "Lo-Fi": {"bass": -10, "treble": -10}},
        "Tremolo": {"Gentle Sway": {"rate": .8, "depth": 20}, "Slow Pulse": {"rate": 2, "depth": 45}, "Classic": {"rate": 4, "depth": 50}, "Guitar Amp": {"rate": 5, "depth": 60}, "Fast Pulse": {"rate": 8, "depth": 70}, "Helicopter": {"rate": 12, "depth": 90}, "Stutter": {"rate": 20, "depth": 100}, "Slow Chop": {"rate": 1.5, "depth": 100}, "Nervous": {"rate": 35, "depth": 75}, "Ring Buzz": {"rate": 70, "depth": 95}},
        "Distortion": {"Soft Saturation": {"amount": 5}, "Warm Drive": {"amount": 15}, "Tube Crunch": {"amount": 25}, "Blues Drive": {"amount": 35}, "Rock Rhythm": {"amount": 45}, "Hard Rock": {"amount": 60}, "Heavy Drive": {"amount": 70}, "Metal": {"amount": 82}, "Destroyed Speaker": {"amount": 92}, "Maximum Carnage": {"amount": 100}},
    }
    NAVIGATION_STEPS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0)

    def __init__(self) -> None:
        super().__init__()
        self.title("QuickEdit")
        self.geometry("760x430")
        self.minsize(620, 360)
        self.document: AudioDocument | None = None
        self.app_dir = application_dir()
        self.media = MediaBackend(self.app_dir)
        self.online = OnlineBackend(self.app_dir)
        self.credential_store = CredentialStore()
        self.audiovault_credentials = self.credential_store.load()
        self.audiovault_logged_in = False
        self.undo_stack: list[AudioDocument] = []
        self.redo_stack: list[AudioDocument] = []
        self.playing = False
        self.paused = False
        self.play_direction = 1
        self.play_origin_frame = 0
        self.play_media_origin_frame = 0
        self.play_target_frame = 0
        self.play_started_at = 0.0
        self.playback_speed = 1.0
        self.playback_pitch_semitones = 0.0
        self.playback_pitch_preserves_speed = True
        self.playback_pitch_preserve_var = tk.BooleanVar(value=True)
        self.playback_time_factor = 1.0
        self.recent_files: list[str] = []
        self.favorite_files: list[str] = []
        self.transport_timer: str | None = None
        self.temp_play_path: str | None = None
        self.play_process = None
        self.preview_process = None
        self.effect_preview_files: set[str] = set()
        self.record_process = None
        self.record_path: str | None = None
        self.record_append = False
        self.input_device: AudioDevice | None = None
        self.output_device = "auto"
        self.soundfont_path: str | None = None
        self.export_sample_rate: int | None = None
        self.export_bit_depth: int | None = None
        self.export_channels: int | None = None
        self.export_bitrate = 192
        self.online_download_format = ".mp3"
        self.online_download_sample_rate = 44100
        self.online_download_bitrate = 192
        self.last_open_directory = ""
        self.navigation_step_index = self.NAVIGATION_STEPS.index(0.1)
        self.screen_reader = ScreenReaderAnnouncer()
        self._active_menu: tk.Menu | None = None
        self._menu_watch_timer: str | None = None
        self.theme_manager = ThemeManager(self)
        self._load_file_history()
        self.theme_var = tk.StringVar(value=self.theme_manager.mode)
        self.status_var = tk.StringVar(value="Ready. Open a PCM WAV file with Control O.")
        self.details_var = tk.StringVar(value="No audio is open.")
        self._build_menu()
        self._build_ui()
        self._bind_keys()
        self.theme_manager.apply()
        self.bind_all("<Map>", self._theme_new_widget, add="+")
        self.after(1500, self._poll_system_theme)

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="New Audio\tCtrl+N", command=self.new_file)
        file_menu.add_command(label="Open Audio\tCtrl+O", command=self.open_file)
        self.recent_menu = tk.Menu(file_menu, tearoff=False, postcommand=self._refresh_recent_menu)
        file_menu.add_cascade(label="Recent Files", menu=self.recent_menu)
        self.favorites_menu = tk.Menu(file_menu, tearoff=False, postcommand=self._refresh_favorites_menu)
        file_menu.add_cascade(label="Favorites", menu=self.favorites_menu)
        file_menu.add_command(label="Save\tCtrl+S", command=self.save)
        file_menu.add_command(label="Save As\tCtrl+Shift+S", command=self.save_as)
        file_menu.add_command(label="Output Format Settings", command=self.output_format_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Exit\tAlt+F4", command=self.destroy)
        menu.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menu, tearoff=False)
        edit_menu.add_command(label="Undo\tCtrl+Z", command=self.undo)
        edit_menu.add_command(label="Redo\tCtrl+Y", command=self.redo)
        edit_menu.add_separator()
        edit_menu.add_command(label="Select All\tCtrl+A", command=self.select_all)
        edit_menu.add_command(label="Delete Selection\tDelete", command=self.delete_selection)
        edit_menu.add_command(label="Crop to Selection\tCtrl+T", command=self.crop_selection)
        edit_menu.add_separator()
        edit_menu.add_command(label="Mix Audio File at Cursor", command=self.mix_audio_file)
        edit_menu.add_command(label="Crossfade Selected Halves", command=self.crossfade_selection)
        menu.add_cascade(label="Edit", menu=edit_menu)

        effects = tk.Menu(menu, tearoff=False)
        effects.add_command(label="Amplify or Reduce Volume", command=self.amplify)
        effects.add_command(label="Normalize to -1 dB", command=self.normalize_audio)
        effects.add_separator()
        effects.add_command(label="Echo", command=self.echo_audio)
        effects.add_command(label="Room Reverb", command=self.reverb_audio)
        effects.add_command(label="Flanger", command=self.flanger_audio)
        effects.add_command(label="Chorus", command=self.chorus_audio)
        effects.add_separator()
        effects.add_command(label="Noise Gate", command=self.noise_gate_audio)
        effects.add_command(label="Noise Reduction", command=self.noise_reduction_audio)
        effects.add_command(label="Tape Hiss Reduction", command=self.tape_hiss_reduction)
        effects.add_command(label="Vinyl Click and Crackle Removal", command=self.vinyl_crackle_reduction)
        effects.add_command(label="Add Tape Hiss", command=self.add_tape_hiss)
        effects.add_command(label="Add Vinyl Crackle", command=self.add_vinyl_crackle)
        effects.add_command(label="Low-Pass Filter", command=self.lowpass_audio)
        effects.add_command(label="High-Pass Filter", command=self.highpass_audio)
        effects.add_command(label="Compressor", command=self.compressor_audio)
        effects.add_command(label="Expander", command=self.expander_audio)
        effects.add_command(label="Limiter", command=self.limiter_audio)
        effects.add_command(label="Band-Pass Filter", command=self.bandpass_audio)
        effects.add_command(label="Notch Filter", command=self.notch_audio)
        effects.add_command(label="Graphic Equalizer", command=self.graphic_equalizer_audio)
        effects.add_command(label="Parametric Equalizer", command=self.parametric_equalizer_audio)
        effects.add_command(label="De-Esser", command=self.deesser_audio)
        effects.add_command(label="Bass and Treble", command=self.bass_treble_audio)
        effects.add_command(label="Tremolo", command=self.tremolo_audio)
        effects.add_command(label="Distortion", command=self.distortion_audio)
        effects.add_separator()
        effects.add_command(label="Change Speed, Preserve Pitch", command=self.change_speed)
        effects.add_command(label="Change Pitch, Preserve Speed", command=self.change_pitch)
        effects.add_command(label="Tape Pitch and Speed Together", command=self.change_tape_speed)
        effects.add_separator()
        effects.add_command(label="Fade In", command=lambda: self.fade_audio(True))
        effects.add_command(label="Fade Out", command=lambda: self.fade_audio(False))
        effects.add_command(label="Reverse Audio", command=self.reverse_audio)
        effects.add_command(label="Replace with Silence", command=self.silence_audio)
        effects.add_command(label="Swap Left and Right Channels", command=self.swap_channels)
        menu.add_cascade(label="Effects", menu=effects)

        generate = tk.Menu(menu, tearoff=False)
        generate.add_command(label="Tone or Noise", command=self.generate_tone)
        generate.add_command(label="DTMF Telephone Keys", command=lambda: self.generate_phone_keys("DTMF"))
        generate.add_command(label="MF Telephone Keys", command=lambda: self.generate_phone_keys("MF"))
        generate.add_separator()
        generate.add_command(label="Censor Selection", command=self.censor_selection)
        menu.add_cascade(label="Generate and Censor", menu=generate)

        transport = tk.Menu(menu, tearoff=False)
        transport.add_command(label="Play or Pause\tSpace", command=self.toggle_play)
        transport.add_command(label="Master Play from Start\tF2", command=self.master_play)
        transport.add_command(label="Play Backward from Cursor\tF3", command=self.play_reverse)
        transport.add_command(label="Play Whole File Backward\tShift+F3", command=self.play_whole_reverse)
        transport.add_command(label="Set Double-Speed Playback\tF4", command=lambda: self.set_playback_speed_preset(2.0))
        transport.add_command(label="Set Half-Speed Playback\tShift+F4", command=lambda: self.set_playback_speed_preset(0.5))
        transport.add_command(label="Play Selection\tShift+Space", command=self.play_selection)
        transport.add_command(label="Go to Time\tCtrl+G", command=self.go_to_time)
        transport.add_command(label="Zoom In / Finer Movement\tShift+Up", command=self.zoom_in)
        transport.add_command(label="Zoom Out / Wider Movement\tShift+Down", command=self.zoom_out)
        transport.add_command(label="Set Selection Start\t[", command=self.set_selection_start)
        transport.add_command(label="Set Selection End\t]", command=self.set_selection_end)
        transport.add_command(label="Announce Status\tF6", command=self.announce_status)
        transport.add_separator()
        transport.add_command(label="Playback Speed\tCtrl+Up/Down", command=self.set_playback_speed)
        transport.add_command(label="Playback Pitch\tAlt+Up/Down", command=self.set_playback_pitch)
        transport.add_command(label="Reset Playback Speed and Pitch\tCtrl+Alt+0", command=self.reset_playback_speed_pitch)
        transport.add_checkbutton(label="Preserve Speed When Changing Playback Pitch", variable=self.playback_pitch_preserve_var, command=self.toggle_playback_pitch_mode)
        menu.add_cascade(label="Transport", menu=transport)

        record = tk.Menu(menu, tearoff=False)
        record.add_command(label="Record or Stop Recording\tF9", command=self.toggle_recording)
        record.add_command(label="Choose Input Device", command=self.choose_input_device)
        record.add_command(label="Choose Output Device", command=self.choose_output_device)
        menu.add_cascade(label="Record and Devices", menu=record)

        midi_menu = tk.Menu(menu, tearoff=False)
        midi_menu.add_command(label="Choose SoundFont", command=self.choose_soundfont)
        midi_menu.add_command(label="Re-render MIDI with Current SoundFont", command=self.rerender_midi)
        midi_menu.add_command(label="Virtual MIDI and Sample Keyboard", command=self.virtual_midi_keyboard)
        menu.add_cascade(label="MIDI and SoundFonts", menu=midi_menu)

        plugins = tk.Menu(menu, tearoff=False)
        plugins.add_command(label="Open Isolated VST2 and VST3 Rack", command=self.open_carla_host)
        plugins.add_command(label="Choose VST Plug-in to Locate", command=self.locate_vst_plugin)
        menu.add_cascade(label="VST Plug-ins", menu=plugins)

        online = tk.Menu(menu, tearoff=False)
        online.add_command(label="Import Direct Link", command=self.import_online_link)
        online.add_command(label="Download Direct Link", command=self.download_online_link)
        online.add_command(label="Download Format Settings", command=self.online_download_settings)
        online.add_command(label="Preview Direct URL or Radio Playlist", command=self.preview_direct_url)
        online.add_command(label="Stop Direct URL Preview", command=self.stop_direct_url_preview)
        online.add_command(label="Search YouTube", command=lambda: self.search_online("YouTube"))
        online.add_command(label="Search SoundCloud", command=lambda: self.search_online("SoundCloud"))
        online.add_separator()
        online.add_command(label="Log in to AudioVault", command=self.login_audiovault)
        online.add_command(label="Log out and Forget AudioVault Login", command=self.logout_audiovault)
        online.add_command(label="Search AudioVault Movies", command=lambda: self.search_audiovault("movies"))
        online.add_command(label="Search AudioVault TV Shows", command=lambda: self.search_audiovault("shows"))
        menu.add_cascade(label="Online Audio", menu=online)

        appearance = tk.Menu(menu, tearoff=False)
        for label, value in (
            ("Follow Windows", "system"),
            ("Light", "light"),
            ("Dark", "dark"),
            ("Dark Dim", "dark_dim"),
            ("Dark High Contrast", "dark_high_contrast"),
        ):
            appearance.add_radiobutton(label=label, variable=self.theme_var, value=value, command=lambda selected=value: self.set_theme(selected))
        menu.add_cascade(label="Appearance", menu=appearance)
        self.config(menu=menu)
        self._apply_menu_mnemonics(menu)
        self.recent_menu.configure(postcommand=self._post_recent_menu)
        self.favorites_menu.configure(postcommand=self._post_favorites_menu)

    def set_theme(self, mode: str) -> None:
        resolved = self.theme_manager.resolve_mode() if mode == self.theme_manager.mode else ""
        self.theme_manager.set_mode(mode)
        resolved = self.theme_manager.resolved_mode
        label = "Windows high contrast" if resolved == "windows_high_contrast" else mode.replace("_", " ")
        message = f"Appearance set to {label}."
        self.status_var.set(message)
        self.screen_reader.speak(message)

    def _theme_new_widget(self, event) -> None:
        self.theme_manager.apply_widget(event.widget, self.theme_manager._active_palette)

    def _poll_system_theme(self) -> None:
        resolved = self.theme_manager.resolve_mode()
        if resolved != self.theme_manager.resolved_mode:
            self.theme_manager.apply()
        self.after(1500, self._poll_system_theme)

    def _apply_menu_mnemonics(self, menu: tk.Menu) -> None:
        """Expose a mnemonic on every menu label and recurse into submenus."""
        menu.bind("<Home>", self._menu_home)
        menu.bind("<End>", self._menu_end)
        menu.bind("<KeyPress>", self._menu_first_letter, add="+")
        menu.configure(postcommand=lambda current=menu: self._menu_posted(current))
        end = menu.index("end")
        if end is None:
            return
        for index in range(end + 1):
            if menu.type(index) == "separator":
                continue
            label = menu.entrycget(index, "label")
            underline = next((position for position, char in enumerate(label) if char.isalnum()), -1)
            if underline >= 0:
                menu.entryconfigure(index, underline=underline)
            if menu.type(index) == "cascade":
                child_name = menu.entrycget(index, "menu")
                if child_name:
                    self._apply_menu_mnemonics(self.nametowidget(child_name))

    def _menu_posted(self, menu: tk.Menu) -> None:
        self._active_menu = menu
        if self._menu_watch_timer:
            self.after_cancel(self._menu_watch_timer)
        self._menu_watch_timer = self.after(100, self._watch_posted_menu)

    def _watch_posted_menu(self) -> None:
        self._menu_watch_timer = None
        menu = self._active_menu
        if menu is None:
            return
        try:
            mapped = bool(menu.winfo_ismapped())
        except tk.TclError:
            mapped = False
        if mapped:
            self._menu_watch_timer = self.after(100, self._watch_posted_menu)
        else:
            self._active_menu = None

    def _posted_menu(self) -> tk.Menu | None:
        menu = self._active_menu
        if menu is None:
            return None
        try:
            return menu if menu.winfo_ismapped() else None
        except tk.TclError:
            return None

    def _build_ui(self) -> None:
        frame = tk.Frame(self, padx=18, pady=18)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text="QuickEdit", font=("Segoe UI", 22, "bold")).pack(anchor="w")
        tk.Label(
            frame,
            text="Keyboard-first audio editing prototype",
            font=("Segoe UI", 11),
        ).pack(anchor="w", pady=(0, 18))
        details = tk.Label(
            frame,
            textvariable=self.details_var,
            justify="left",
            anchor="nw",
            relief="groove",
            padx=12,
            pady=12,
            takefocus=True,
        )
        details.pack(fill="both", expand=True)
        details.focus_set()
        tk.Label(
            frame,
            textvariable=self.status_var,
            anchor="w",
            justify="left",
            relief="sunken",
            padx=8,
            pady=6,
        ).pack(fill="x", pady=(12, 0))

    def _bind_keys(self) -> None:
        # One dispatcher is more reliable with screen readers than a collection
        # of Tk accelerator patterns, especially for arrows and OEM bracket keys.
        self.bind_all("<KeyPress>", self._dispatch_key, add="+")
        # Do not replace Tk's Menu class bindings here. Every menu receives the
        # extra Home, End, and first-letter handlers in _apply_menu_mnemonics;
        # replacing the class binding removes native arrows, Enter, Escape, and
        # submenu activation for screen-reader users.

    @staticmethod
    def _menu_selectable_indices(menu: tk.Menu) -> list[int]:
        end = menu.index("end")
        if end is None:
            return []
        return [
            index for index in range(end + 1)
            if menu.type(index) != "separator" and menu.entrycget(index, "state") != "disabled"
        ]

    def _menu_home(self, event) -> str:
        self._activate_menu_boundary(event.widget, first=True)
        return "break"

    def _menu_end(self, event) -> str:
        self._activate_menu_boundary(event.widget, first=False)
        return "break"

    def _activate_menu_boundary(self, menu: tk.Menu, first: bool) -> bool:
        indices = self._menu_selectable_indices(menu)
        if indices:
            index = indices[0] if first else indices[-1]
            menu.activate(index)
            self.screen_reader.speak(menu.entrycget(index, "label"))
            return True
        return False

    def _menu_first_letter(self, event):
        if not event.char or not event.char.isprintable() or event.state & 0x000C:
            return None
        return "break" if self._activate_menu_letter(event.widget, event.char.lower()) else None

    def _activate_menu_letter(self, menu: tk.Menu, letter: str) -> bool:
        indices = self._menu_selectable_indices(menu)
        if not indices:
            return False
        active = menu.index("active")
        start = indices.index(active) + 1 if active in indices else 0
        ordered = indices[start:] + indices[:start]
        for index in ordered:
            label = menu.entrycget(index, "label").lstrip()
            if label and label[0].lower() == letter:
                menu.activate(index)
                self.screen_reader.speak(label)
                return True
        return False

    def _dispatch_key(self, event):
        posted_menu = self._posted_menu()
        if posted_menu is not None:
            key = event.keysym.lower()
            if key == "home":
                self._activate_menu_boundary(posted_menu, first=True)
                return "break"
            if key == "end":
                self._activate_menu_boundary(posted_menu, first=False)
                return "break"
            if event.char and event.char.isprintable() and not event.state & 0x000C:
                if self._activate_menu_letter(posted_menu, event.char.lower()):
                    return "break"
            return None
        focus = self.focus_get()
        if focus and focus.winfo_toplevel() is not self:
            return None
        if focus and focus.winfo_class() in {"Entry", "TEntry", "Text", "Spinbox", "TSpinbox"}:
            return None

        key = event.keysym.lower()
        shift = bool(event.state & 0x0001)
        control = bool(event.state & 0x0004)
        alt = bool(event.state & 0x0008) or bool(event.state & 0x20000)

        callback = None
        if key == "f2":
            callback = self.master_play
        elif key == "f3":
            callback = self.play_whole_reverse if shift else self.play_reverse
        elif key == "f4" and not alt:
            callback = (lambda: self.set_playback_speed_preset(0.5)) if shift else (lambda: self.set_playback_speed_preset(2.0))
        elif key == "f9":
            callback = self.toggle_recording
        elif key == "f6":
            callback = self.announce_status
        elif key == "space":
            callback = self.play_selection if shift else self.toggle_play
        elif key == "home":
            callback = lambda: self.set_cursor_frame(0)
        elif key == "end":
            callback = lambda: self.set_cursor_frame(self.document.frame_count if self.document else 0)
        elif key == "left":
            amount = 1.0 if control else 5.0 if alt else self.navigation_step
            callback = lambda: self.move_cursor(-amount)
        elif key == "right":
            amount = 1.0 if control else 5.0 if alt else self.navigation_step
            callback = lambda: self.move_cursor(amount)
        elif key == "up" and control:
            callback = lambda: self.adjust_playback_speed(0.1)
        elif key == "down" and control:
            callback = lambda: self.adjust_playback_speed(-0.1)
        elif key == "up" and alt:
            callback = lambda: self.adjust_playback_pitch(1.0)
        elif key == "down" and alt:
            callback = lambda: self.adjust_playback_pitch(-1.0)
        elif key == "0" and control and alt:
            callback = self.reset_playback_speed_pitch
        elif key == "up" and shift:
            callback = self.zoom_in
        elif key == "down" and shift:
            callback = self.zoom_out
        elif key == "bracketleft" or event.keycode == 219:
            callback = self.set_selection_start
        elif key == "bracketright" or event.keycode == 221:
            callback = self.set_selection_end
        elif key == "delete":
            callback = self.delete_selection
        elif control:
            callback = {
                "o": self.open_file,
                "n": self.new_file,
                "s": self.save_as if shift else self.save,
                "a": self.select_all,
                "t": self.crop_selection,
                "z": self.undo,
                "y": self.redo,
                "g": self.go_to_time,
            }.get(key)

        if callback:
            return self._invoke(callback)
        return None

    @staticmethod
    def _invoke(callback):
        callback()
        return "break"

    def announce(self, message: str) -> None:
        self.status_var.set("")
        self.update_idletasks()
        self.status_var.set(message)
        self.screen_reader.speak(message)

    def set_status(self, message: str) -> None:
        """Update visible status without interrupting the audio with speech."""
        self.status_var.set(message)

    def accessible_button(self, parent, text: str, command) -> ttk.Button:
        button = ttk.Button(parent, text=text, command=command, takefocus=True)
        button.bind("<FocusIn>", lambda event, label=text: self.screen_reader.speak(f"{label}, button."))
        return button

    @property
    def navigation_step(self) -> float:
        return self.NAVIGATION_STEPS[self.navigation_step_index]

    def navigation_step_text(self) -> str:
        step = self.navigation_step
        if step < 1:
            milliseconds = round(step * 1000)
            unit = "millisecond" if milliseconds == 1 else "milliseconds"
            return f"{milliseconds} {unit}"
        unit = "second" if step == 1 else "seconds"
        return f"{step:g} {unit}"

    def zoom_in(self) -> None:
        if self.navigation_step_index > 0:
            self.navigation_step_index -= 1
            self.set_status(f"Zoomed in. Left and right move {self.navigation_step_text()}.")
        else:
            self.set_status(f"Maximum zoom. Left and right move {self.navigation_step_text()}.")

    def zoom_out(self) -> None:
        if self.navigation_step_index < len(self.NAVIGATION_STEPS) - 1:
            self.navigation_step_index += 1
            self.set_status(f"Zoomed out. Left and right move {self.navigation_step_text()}.")
        else:
            self.set_status(f"Minimum zoom. Left and right move {self.navigation_step_text()}.")

    def require_document(self) -> AudioDocument | None:
        if self.document is None:
            self.announce("No audio is open.")
        return self.document

    def new_file(self) -> None:
        self.stop(announce=False)
        self.document = AudioDocument(
            channels=2,
            sample_width=2,
            frame_rate=44100,
            frames=b"",
            source_path="Untitled.wav",
        )
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.title("QuickEdit - Untitled")
        self.refresh_details()
        self.announce("Created new stereo audio at 44,100 Hertz and 16 bits.")

    def open_file(self) -> None:
        path = self._choose_audio_file()
        if not path:
            return
        self._open_path(path)

    def _open_path(self, path: str) -> None:
        if not os.path.isfile(path):
            self.announce(f"File not found: {os.path.basename(path)}.")
            self._forget_missing_path(path)
            return
        extension = os.path.splitext(path)[1].lower()
        if extension in {".raw", ".pcm"}:
            self._open_raw_pcm(path)
            return
        try:
            decoded_path = path
            temporary = None
            if extension in {".mid", ".midi"}:
                if not self.soundfont_path:
                    self.choose_soundfont(rerender=False)
                if not self.soundfont_path:
                    self.announce("MIDI was not opened because no SoundFont was selected.")
                    return
                handle, temporary = tempfile.mkstemp(prefix="quickedit-import-", suffix=".wav")
                os.close(handle)
                self.media.render_midi(path, self.soundfont_path, temporary)
                decoded_path = temporary
                source = wave.open(decoded_path, "rb")
            else:
                try:
                    source = wave.open(path, "rb")
                except (wave.Error, EOFError):
                    handle, temporary = tempfile.mkstemp(prefix="quickedit-import-", suffix=".wav")
                    os.close(handle)
                    self.media.decode(path, temporary)
                    decoded_path = temporary
                    source = wave.open(decoded_path, "rb")
            with source:
                if source.getcomptype() != "NONE":
                    raise ValueError("This prototype supports uncompressed PCM WAV files only.")
                document = AudioDocument(
                    channels=source.getnchannels(),
                    sample_width=source.getsampwidth(),
                    frame_rate=source.getframerate(),
                    frames=source.readframes(source.getnframes()),
                    source_path=path,
                    save_path=path if os.path.splitext(path)[1].lower() == ".wav" else None,
                    midi_path=path if extension in {".mid", ".midi"} else None,
                    soundfont_path=self.soundfont_path if extension in {".mid", ".midi"} else None,
                )
            if temporary:
                os.remove(temporary)
        except (wave.Error, OSError, ValueError, MediaError) as exc:
            messagebox.showerror("Could not open audio", str(exc), parent=self)
            return
        self.stop()
        self.document = document
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.title(f"QuickEdit - {os.path.basename(path)}")
        self.refresh_details()
        self._remember_recent(path)
        self.announce(f"Opened {os.path.basename(path)}. Duration {format_time(document.duration)}.")

    @property
    def _history_path(self) -> str:
        folder = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "QuickEdit")
        return os.path.join(folder, "settings.json")

    def _load_file_history(self) -> None:
        try:
            with open(self._history_path, "r", encoding="utf-8") as source:
                settings = json.load(source)
            self.recent_files = [str(path) for path in settings.get("recent_files", [])][:20]
            self.favorite_files = [str(path) for path in settings.get("favorite_files", [])]
            extension = str(settings.get("online_download_format", self.__dict__.get("online_download_format", ".mp3"))).lower()
            if extension in {".wav", ".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wma"}:
                self.online_download_format = extension
            self.online_download_sample_rate = int(settings.get("online_download_sample_rate", self.__dict__.get("online_download_sample_rate", 44100)))
            self.online_download_bitrate = int(settings.get("online_download_bitrate", self.__dict__.get("online_download_bitrate", 192)))
            self.last_open_directory = str(settings.get("last_open_directory", self.__dict__.get("last_open_directory", "")))
        except (OSError, ValueError, TypeError):
            pass

    def _save_file_history(self) -> None:
        os.makedirs(os.path.dirname(self._history_path), exist_ok=True)
        settings = {}
        try:
            with open(self._history_path, "r", encoding="utf-8") as source:
                settings = json.load(source)
        except (OSError, ValueError, TypeError):
            pass
        settings.update(
            recent_files=self.recent_files,
            favorite_files=self.favorite_files,
            online_download_format=self.__dict__.get("online_download_format", ".mp3"),
            online_download_sample_rate=self.__dict__.get("online_download_sample_rate", 44100),
            online_download_bitrate=self.__dict__.get("online_download_bitrate", 192),
            last_open_directory=self.__dict__.get("last_open_directory", ""),
        )
        with open(self._history_path, "w", encoding="utf-8") as target:
            json.dump(settings, target, indent=2)

    def _remember_recent(self, path: str) -> None:
        path = os.path.abspath(path)
        self.recent_files = [item for item in self.recent_files if os.path.normcase(item) != os.path.normcase(path)]
        self.recent_files.insert(0, path)
        self.recent_files = self.recent_files[:20]
        self._save_file_history()

    def _forget_missing_path(self, path: str) -> None:
        self.recent_files = [item for item in self.recent_files if os.path.normcase(item) != os.path.normcase(path)]
        self.favorite_files = [item for item in self.favorite_files if os.path.normcase(item) != os.path.normcase(path)]
        self._save_file_history()

    def _refresh_recent_menu(self) -> None:
        self.recent_menu.delete(0, "end")
        if not self.recent_files:
            self.recent_menu.add_command(label="No Recent Files", state="disabled")
        for path in self.recent_files:
            self.recent_menu.add_command(label=os.path.basename(path), command=lambda selected=path: self._open_path(selected))
        if self.recent_files:
            self.recent_menu.add_separator()
            self.recent_menu.add_command(label="Clear Recent Files", command=self.clear_recent_files)
        self._apply_menu_mnemonics(self.recent_menu)

    def _post_recent_menu(self) -> None:
        self._refresh_recent_menu()
        self._menu_posted(self.recent_menu)
        self.recent_menu.configure(postcommand=self._post_recent_menu)

    def _refresh_favorites_menu(self) -> None:
        self.favorites_menu.delete(0, "end")
        self.favorites_menu.add_command(label="Add Current File", command=self.add_current_favorite)
        self.favorites_menu.add_command(label="Remove Current File", command=self.remove_current_favorite)
        if self.favorite_files:
            self.favorites_menu.add_separator()
            for path in self.favorite_files:
                self.favorites_menu.add_command(label=os.path.basename(path), command=lambda selected=path: self._open_path(selected))
        self._apply_menu_mnemonics(self.favorites_menu)

    def _post_favorites_menu(self) -> None:
        self._refresh_favorites_menu()
        self._menu_posted(self.favorites_menu)
        self.favorites_menu.configure(postcommand=self._post_favorites_menu)

    def clear_recent_files(self) -> None:
        self.recent_files.clear(); self._save_file_history(); self.announce("Recent files cleared.")

    def add_current_favorite(self) -> None:
        if not self.document or not os.path.isfile(self.document.source_path):
            self.announce("The current audio does not have a local source file to favorite."); return
        path = os.path.abspath(self.document.source_path)
        if not any(os.path.normcase(item) == os.path.normcase(path) for item in self.favorite_files):
            self.favorite_files.append(path); self._save_file_history()
        self.announce(f"Added {os.path.basename(path)} to favorites.")

    def remove_current_favorite(self) -> None:
        if not self.document:
            self.announce("No audio is open."); return
        path = os.path.abspath(self.document.source_path)
        self.favorite_files = [item for item in self.favorite_files if os.path.normcase(item) != os.path.normcase(path)]
        self._save_file_history(); self.announce(f"Removed {os.path.basename(path)} from favorites.")

    def _choose_audio_file(self) -> str | None:
        dialog = tk.Toplevel(self)
        dialog.title("Open audio with preview")
        dialog.geometry("760x520")
        dialog.transient(self)
        dialog.grab_set()
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        starting_folder = self.last_open_directory if os.path.isdir(self.last_open_directory) else downloads
        current_dir = [starting_folder if os.path.isdir(starting_folder) else os.getcwd()]
        entries: list[tuple[str, bool]] = []
        result: list[str] = []
        preview_enabled = tk.BooleanVar(value=False)
        path_var = tk.StringVar(value=current_dir[0])
        selection_var = tk.StringVar(value="")

        tk.Label(dialog, text="Folder:").pack(anchor="w", padx=12, pady=(10, 0))
        tk.Label(dialog, textvariable=path_var, anchor="w", relief="sunken", padx=6).pack(fill="x", padx=12)
        file_list = tk.Listbox(dialog, exportselection=False, width=90, height=18)
        file_list.pack(fill="both", expand=True, padx=12, pady=8)
        preview_check = ttk.Checkbutton(
            dialog,
            text="Preview selected audio while browsing",
            variable=preview_enabled,
            takefocus=True,
        )
        preview_check.pack(anchor="w", padx=12)
        tk.Label(dialog, textvariable=selection_var, anchor="w", padx=12, pady=5).pack(fill="x")
        buttons = tk.Frame(dialog)
        buttons.pack(fill="x", padx=12, pady=10)

        def stop_preview() -> None:
            if self.preview_process and self.preview_process.poll() is None:
                self.preview_process.terminate()
            self.preview_process = None

        def populate(folder: str) -> None:
            stop_preview()
            try:
                items = list(os.scandir(folder))
            except OSError as exc:
                self.screen_reader.speak(f"Could not open folder. {exc}")
                return
            current_dir[0] = folder
            self.last_open_directory = os.path.abspath(folder)
            self._save_file_history()
            path_var.set(folder)
            entries.clear()
            file_list.delete(0, "end")
            for item in sorted(items, key=lambda value: (not value.is_dir(), value.name.lower())):
                entries.append((item.path, item.is_dir()))
                file_list.insert("end", f"Folder: {item.name}" if item.is_dir() else item.name)
            if entries:
                file_list.selection_set(0)
                file_list.activate(0)
                file_list.see(0)
                dialog.after(100, selection_changed)

        def selection_changed(event=None) -> None:
            selected = file_list.curselection()
            if not selected:
                return
            index = selected[0]
            path, is_dir = entries[index]
            kind = "folder" if is_dir else "file"
            message = f"{os.path.basename(path)}, {kind}, {index + 1} of {len(entries)}."
            selection_var.set(message)
            self.screen_reader.speak(message)
            stop_preview()
            if preview_enabled.get() and not is_dir:
                self.preview_process = self.media.start_playback(path, self.output_device)

        def select_index(index: int) -> None:
            if not entries:
                return
            index = max(0, min(len(entries) - 1, index))
            file_list.selection_clear(0, "end")
            file_list.selection_set(index)
            file_list.activate(index)
            file_list.see(index)
            selection_changed()

        def first_letter(event) -> str | None:
            if event.state & 0x000C or not event.char or not event.char.isprintable():
                return None
            selected = file_list.curselection()
            current = selected[0] if selected else -1
            names = [os.path.basename(path) for path, _ in entries]
            match = next_prefix_index(names, current, event.char)
            if match is not None:
                select_index(match)
            else:
                self.screen_reader.speak(f"No item begins with {event.char}.")
            return "break"

        def list_home(event=None) -> str:
            select_index(0)
            return "break"

        def list_end(event=None) -> str:
            select_index(len(entries) - 1)
            return "break"

        def activate(event=None) -> None:
            selected = file_list.curselection()
            if not selected:
                return
            path, is_dir = entries[selected[0]]
            if is_dir:
                populate(path)
            else:
                result.append(path)
                stop_preview()
                dialog.destroy()

        def go_up(event=None) -> str:
            parent = os.path.dirname(current_dir[0])
            if parent and parent != current_dir[0]:
                populate(parent)
            return "break"

        def toggle_preview() -> None:
            state = "on" if preview_enabled.get() else "off"
            self.screen_reader.speak(f"Preview {state}.")
            selection_changed()

        def preview_selected() -> None:
            selected = file_list.curselection()
            if not selected:
                self.screen_reader.speak("No file is selected.")
                return
            path, is_dir = entries[selected[0]]
            if is_dir:
                self.screen_reader.speak("The selected item is a folder.")
                return
            stop_preview()
            self.preview_process = self.media.start_playback(path, self.output_device)
            self.screen_reader.speak(f"Previewing {os.path.basename(path)}.")

        preview_check.configure(command=toggle_preview)
        preview_check.bind(
            "<FocusIn>",
            lambda event: self.screen_reader.speak(
                f"Preview selected audio while browsing, {'checked' if preview_enabled.get() else 'not checked'}."
            ),
        )
        file_list.bind("<<ListboxSelect>>", selection_changed)
        file_list.bind("<Return>", activate)
        file_list.bind("<Double-Button-1>", activate)
        file_list.bind("<BackSpace>", go_up)
        file_list.bind("<Home>", list_home)
        file_list.bind("<End>", list_end)
        file_list.bind("<KeyPress>", first_letter, add="+")
        self.accessible_button(buttons, "Open Selected File", activate).pack(side="left")
        self.accessible_button(buttons, "Preview Selected File", preview_selected).pack(side="left", padx=8)
        self.accessible_button(buttons, "Stop Preview", stop_preview).pack(side="left")
        self.accessible_button(buttons, "Up One Folder", go_up).pack(side="left", padx=8)
        self.accessible_button(buttons, "Cancel Open Dialog", dialog.destroy).pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", lambda: (stop_preview(), dialog.destroy()))
        populate(current_dir[0])
        file_list.focus_set()
        self.wait_window(dialog)
        stop_preview()
        return result[0] if result else None

    def _open_raw_pcm(self, path: str) -> None:
        rate = simpledialog.askinteger("Raw PCM sample rate", "Sample rate in Hertz:", initialvalue=44100, minvalue=1000, maxvalue=768000, parent=self)
        if rate is None:
            return
        channels = simpledialog.askinteger("Raw PCM channels", "Number of channels:", initialvalue=2, minvalue=1, maxvalue=32, parent=self)
        if channels is None:
            return
        bits = simpledialog.askinteger("Raw PCM bit depth", "Bit depth: 8, 16, 24, or 32:", initialvalue=16, parent=self)
        if bits not in {8, 16, 24, 32}:
            messagebox.showerror("Invalid bit depth", "Choose 8, 16, 24, or 32 bits.", parent=self)
            return
        try:
            with open(path, "rb") as source:
                frames = source.read()
        except OSError as exc:
            messagebox.showerror("Could not open raw PCM", str(exc), parent=self)
            return
        frame_size = channels * (bits // 8)
        frames = frames[: len(frames) - (len(frames) % frame_size)]
        self.stop(announce=False)
        self.document = AudioDocument(channels, bits // 8, rate, frames, path)
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.title(f"QuickEdit - {os.path.basename(path)}")
        self.refresh_details()
        self._remember_recent(path)
        self.announce(f"Opened raw PCM. {rate} Hertz, {bits} bit, {channels} channels. Duration {format_time(self.document.duration)}.")

    def _load_online_wav(self, path: str, title: str) -> None:
        try:
            with wave.open(path, "rb") as source:
                document = AudioDocument(
                    source.getnchannels(), source.getsampwidth(), source.getframerate(),
                    source.readframes(source.getnframes()), title,
                )
        except (wave.Error, OSError) as exc:
            messagebox.showerror("Could not import online audio", str(exc), parent=self)
            return
        self.stop(announce=False)
        self.document = document
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.title(f"QuickEdit - {title}")
        self.refresh_details()
        self.announce(f"Imported {title}. Duration {format_time(document.duration)}.")

    def import_online_link(self) -> None:
        url = simpledialog.askstring("Import online audio", "YouTube, SoundCloud, or other supported address:", parent=self)
        if not url:
            return
        self._import_online_result(OnlineResult(url, url, "Direct link"))

    def download_online_link(self) -> None:
        url = simpledialog.askstring("Download online audio", "YouTube, SoundCloud, or other supported address:", parent=self)
        if not url:
            return
        self._download_online_result(OnlineResult(url, url, "Direct link"))

    def online_download_settings(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Online Download Settings")
        dialog.transient(self)
        dialog.grab_set()
        format_var = tk.StringVar(value=self.online_download_format.lstrip(".").upper())
        rate_var = tk.StringVar(value=str(self.online_download_sample_rate))
        bitrate_var = tk.StringVar(value=str(self.online_download_bitrate))

        tk.Label(dialog, text="Download format").grid(row=0, column=0, sticky="w", padx=12, pady=(12, 4))
        format_box = ttk.Combobox(
            dialog, textvariable=format_var, state="readonly", takefocus=True,
            values=("WAV", "MP3", "FLAC", "OGG", "OPUS", "M4A", "WMA"),
        )
        format_box.grid(row=1, column=0, sticky="ew", padx=12)
        tk.Label(dialog, text="Sample rate in Hertz").grid(row=2, column=0, sticky="w", padx=12, pady=(10, 4))
        rate_box = ttk.Combobox(
            dialog, textvariable=rate_var, state="readonly", takefocus=True,
            values=("8000", "11025", "16000", "22050", "32000", "44100", "48000", "88200", "96000", "192000"),
        )
        rate_box.grid(row=3, column=0, sticky="ew", padx=12)
        tk.Label(dialog, text="Compressed audio bitrate in kilobits per second").grid(row=4, column=0, sticky="w", padx=12, pady=(10, 4))
        bitrate_box = ttk.Combobox(
            dialog, textvariable=bitrate_var, state="readonly", takefocus=True,
            values=("32", "48", "64", "96", "128", "160", "192", "256", "320", "512"),
        )
        bitrate_box.grid(row=5, column=0, sticky="ew", padx=12)

        def save_settings(event=None) -> str:
            self.online_download_format = f".{format_var.get().lower()}"
            self.online_download_sample_rate = int(rate_var.get())
            self.online_download_bitrate = int(bitrate_var.get())
            self._save_file_history()
            dialog.destroy()
            bitrate_note = " Bitrate is ignored for WAV and FLAC." if self.online_download_format in {".wav", ".flac"} else ""
            self.announce(
                f"Online downloads set to {format_var.get()}, {self.online_download_sample_rate} Hertz, "
                f"{self.online_download_bitrate} kilobits per second.{bitrate_note}"
            )
            return "break"

        buttons = tk.Frame(dialog)
        buttons.grid(row=6, column=0, sticky="ew", padx=12, pady=12)
        self.accessible_button(buttons, "Save Download Settings", save_settings).pack(side="left")
        self.accessible_button(buttons, "Cancel Download Settings", dialog.destroy).pack(side="right")
        for box, spoken_name in (
            (format_box, "Download format"), (rate_box, "Sample rate"), (bitrate_box, "Compressed audio bitrate")
        ):
            box.bind("<FocusIn>", lambda event, name=spoken_name: self.screen_reader.speak(name))
            box.bind("<Return>", save_settings)
        dialog.columnconfigure(0, weight=1)
        format_box.focus_set()
        self.wait_window(dialog)

    def preview_direct_url(self) -> None:
        url = simpledialog.askstring("Preview direct URL", "Media, stream, PLS, M3U, or M3U8 address:", parent=self)
        if not url:
            return
        try:
            stream = self.online.preview_url(url)
            self.stop_direct_url_preview()
            self.preview_process = self.media.start_playback(stream, self.output_device)
            self.announce("Direct URL preview started.")
        except (MediaError, OSError) as exc:
            messagebox.showerror("Could not preview URL", str(exc), parent=self)

    def stop_direct_url_preview(self) -> None:
        if self.preview_process and self.preview_process.poll() is None:
            self.preview_process.terminate()
        self.preview_process = None

    def search_online(self, provider: str) -> None:
        result_kind = "videos"
        if provider == "YouTube":
            options = self.youtube_search_options()
            if not options:
                return
            query, result_kind = options
        else:
            query = simpledialog.askstring(f"Search {provider}", "Search terms:", parent=self)
        if not query:
            return
        self.announce(f"Searching {provider} for {query}.")
        try:
            results = self.online.search(provider, query, kind=result_kind)
        except (MediaError, ValueError) as exc:
            messagebox.showerror(f"{provider} search failed", str(exc), parent=self)
            return
        self._choose_online_result(results, f"{provider} results")

    def youtube_search_options(self) -> tuple[str, str] | None:
        """Collect a YouTube query and result type with explicitly named controls."""
        dialog = tk.Toplevel(self)
        dialog.title("Search YouTube")
        dialog.transient(self)
        dialog.grab_set()
        result: list[tuple[str, str]] = []
        query_var = tk.StringVar()
        tk.Label(dialog, text="YouTube search terms").pack(anchor="w", padx=12, pady=(12, 4))
        query_entry = ttk.Entry(dialog, textvariable=query_var, width=60, takefocus=True)
        query_entry.pack(fill="x", padx=12)
        tk.Label(dialog, text="Result type").pack(anchor="w", padx=12, pady=(12, 4))
        type_list = tk.Listbox(dialog, exportselection=False, height=3, takefocus=True)
        for label in ("Videos", "Playlists", "Channels"):
            type_list.insert("end", label)
        type_list.selection_set(0)
        type_list.activate(0)
        type_list.pack(fill="x", padx=12)
        buttons = tk.Frame(dialog)
        buttons.pack(fill="x", padx=12, pady=12)

        def announce_type(event=None) -> None:
            selected = type_list.curselection()
            if selected:
                self.screen_reader.speak(f"YouTube result type: {type_list.get(selected[0])}. {selected[0] + 1} of 3.")

        def submit(event=None) -> str:
            query = query_var.get().strip()
            selected = type_list.curselection()
            if not query:
                self.screen_reader.speak("Enter YouTube search terms.")
                query_entry.focus_set()
                return "break"
            kind = (type_list.get(selected[0]) if selected else "Videos").lower()
            result.append((query, kind))
            dialog.destroy()
            return "break"

        query_entry.bind("<FocusIn>", lambda event: self.screen_reader.speak("YouTube search terms, edit."))
        query_entry.bind("<Return>", submit)
        type_list.bind("<FocusIn>", announce_type)
        type_list.bind("<<ListboxSelect>>", announce_type)
        type_list.bind("<Return>", submit)
        self.accessible_button(buttons, "Search YouTube", submit).pack(side="left")
        self.accessible_button(buttons, "Cancel YouTube Search", dialog.destroy).pack(side="right")
        query_entry.focus_set()
        self.wait_window(dialog)
        return result[0] if result else None

    def login_audiovault(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("AudioVault login")
        dialog.transient(self)
        dialog.grab_set()
        saved = self.audiovault_credentials or ("", "")
        email_var = tk.StringVar(value=saved[0])
        password_var = tk.StringVar(value=saved[1])
        remember_var = tk.BooleanVar(value=self.audiovault_credentials is not None)
        tk.Label(dialog, text="AudioVault email").grid(row=0, column=0, sticky="w", padx=12, pady=(12, 4))
        email_entry = ttk.Entry(dialog, textvariable=email_var, width=48)
        email_entry.bind("<FocusIn>", lambda event: self.screen_reader.speak("AudioVault email, edit."))
        email_entry.grid(row=1, column=0, sticky="ew", padx=12)
        tk.Label(dialog, text="Password").grid(row=2, column=0, sticky="w", padx=12, pady=(10, 4))
        password_entry = ttk.Entry(dialog, textvariable=password_var, show="*", width=48)
        password_entry.bind("<FocusIn>", lambda event: self.screen_reader.speak("AudioVault password, protected edit."))
        password_entry.grid(row=3, column=0, sticky="ew", padx=12)
        remember_check = ttk.Checkbutton(
            dialog, text="Remember me on this computer", variable=remember_var, takefocus=True
        )
        remember_check.grid(row=4, column=0, sticky="w", padx=12, pady=10)
        remember_check.bind(
            "<FocusIn>",
            lambda event: self.screen_reader.speak(
                f"Remember me on this computer, {'checked' if remember_var.get() else 'not checked'}."
            ),
        )
        completed = [False]

        def submit(event=None) -> None:
            email = email_var.get().strip()
            password = password_var.get()
            if not email or not password:
                self.screen_reader.speak("Enter both email and password.")
                return
            self.announce("Logging in to AudioVault.")
            try:
                self.online.audiovault_login(email, password)
                if remember_var.get():
                    self.credential_store.save(email, password)
                    self.audiovault_credentials = (email, password)
                else:
                    self.credential_store.clear()
                    self.audiovault_credentials = (email, password)
                self.audiovault_logged_in = True
            except (MediaError, OSError) as exc:
                messagebox.showerror("AudioVault login failed", str(exc), parent=dialog)
                return
            completed[0] = True
            dialog.destroy()

        button = self.accessible_button(dialog, "Log In to AudioVault", submit)
        button.grid(row=5, column=0, pady=(0, 12))
        dialog.columnconfigure(0, weight=1)
        password_entry.bind("<Return>", submit)
        (password_entry if saved[0] else email_entry).focus_set()
        self.wait_window(dialog)
        if completed[0]:
            storage = "remembered securely by Windows" if remember_var.get() else "kept for this session only"
            self.announce(f"Logged in to AudioVault. Login is {storage}.")

    def logout_audiovault(self) -> None:
        self.online.audiovault_logout()
        self.credential_store.clear()
        self.audiovault_credentials = None
        self.audiovault_logged_in = False
        self.announce("Logged out of AudioVault and forgot the saved login.")

    def ensure_audiovault_login(self) -> bool:
        if self.audiovault_logged_in:
            return True
        if self.audiovault_credentials:
            try:
                self.online.audiovault_login(*self.audiovault_credentials)
                self.audiovault_logged_in = True
                return True
            except (MediaError, OSError):
                self.audiovault_credentials = None
        self.login_audiovault()
        return self.audiovault_logged_in

    def search_audiovault(self, section: str) -> None:
        if not self.ensure_audiovault_login():
            return
        query = simpledialog.askstring("Search AudioVault", "Title or search terms:", parent=self)
        if query is None:
            return
        self.announce("Searching AudioVault.")
        try:
            results = self.online.audiovault_search(query, section)
        except (MediaError, OSError) as exc:
            messagebox.showerror("AudioVault search failed", str(exc), parent=self)
            return
        self._choose_online_result(results, f"AudioVault {section}", allow_preview=False)

    def _choose_online_result(self, results: list[OnlineResult], title: str, allow_preview: bool = True) -> None:
        if not results:
            self.announce("No online results were found.")
            return
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.geometry("820x520")
        dialog.transient(self)
        dialog.grab_set()
        tk.Label(dialog, text="Results. Press Enter to import, Shift Enter to download, or Space to preview.").pack(anchor="w", padx=12, pady=8)
        choices = tk.Listbox(dialog, exportselection=False, width=100, height=20)
        for result in results:
            choices.insert("end", f"{result.title}; {result.detail}" if result.detail else result.title)
        choices.selection_set(0)
        choices.pack(fill="both", expand=True, padx=12, pady=6)
        status = tk.StringVar()
        tk.Label(dialog, textvariable=status, anchor="w", padx=12, pady=4).pack(fill="x")
        action_buttons = tk.Frame(dialog)
        action_buttons.pack(fill="x", padx=12, pady=(2, 10))

        def current() -> OnlineResult | None:
            selected = choices.curselection()
            return results[selected[0]] if selected else None

        def speak(event=None) -> None:
            selected = choices.curselection()
            if selected:
                item = results[selected[0]]
                message = f"{item.title}. {item.detail}. {selected[0] + 1} of {len(results)}."
                status.set(message)
                self.screen_reader.speak(message)

        def preview(event=None) -> str:
            item = current()
            if item and item.kind != "video":
                self.screen_reader.speak(f"{item.kind.title()} results cannot be previewed directly. Press Enter to browse its videos.")
            elif item and allow_preview:
                try:
                    stream = self.online.preview_url(item.url)
                    if self.preview_process and self.preview_process.poll() is None:
                        self.preview_process.terminate()
                    self.preview_process = self.media.start_playback(stream, self.output_device)
                    self.screen_reader.speak(f"Previewing {item.title}.")
                except MediaError as exc:
                    self.screen_reader.speak(f"Preview failed. {exc}")
            return "break"

        def import_selected(event=None) -> str:
            item = current()
            if item:
                if self.preview_process and self.preview_process.poll() is None:
                    self.preview_process.terminate()
                self.preview_process = None
                dialog.destroy()
                if item.provider == "YouTube" and item.kind in {"playlist", "channel"}:
                    self._browse_youtube_collection(item)
                else:
                    self._import_online_result(item)
            return "break"

        def download_selected(event=None) -> str:
            item = current()
            if item:
                if self.preview_process and self.preview_process.poll() is None:
                    self.preview_process.terminate()
                self.preview_process = None
                dialog.destroy()
                if item.provider == "YouTube" and item.kind in {"playlist", "channel"}:
                    self._download_youtube_collection(item)
                else:
                    self._download_online_result(item)
            return "break"

        def stop_online_preview() -> None:
            if self.preview_process and self.preview_process.poll() is None:
                self.preview_process.terminate()
            self.preview_process = None
            self.screen_reader.speak("Preview stopped.")

        choices.bind("<<ListboxSelect>>", speak)
        choices.bind("<space>", preview)
        choices.bind("<Return>", import_selected)
        choices.bind("<Shift-Return>", download_selected)
        self.accessible_button(action_buttons, "Import Selected Result", import_selected).pack(side="left")
        self.accessible_button(action_buttons, "Download Selected Result", download_selected).pack(side="left", padx=8)
        if allow_preview:
            self.accessible_button(action_buttons, "Preview Selected Result", preview).pack(side="left", padx=8)
            self.accessible_button(action_buttons, "Stop Result Preview", stop_online_preview).pack(side="left")
        self.accessible_button(action_buttons, "Cancel Results", dialog.destroy).pack(side="right")
        choices.focus_set()
        dialog.after(150, speak)
        self.wait_window(dialog)
        if self.preview_process and self.preview_process.poll() is None:
            self.preview_process.terminate()
        self.preview_process = None

    def _youtube_collection_limit(self, item: OnlineResult) -> int | None:
        prompt = (
            f"Maximum number of videos to use from {item.title}. "
            "Enter 0 for the entire collection; large channels may take a very long time:"
        )
        return simpledialog.askinteger(
            "YouTube collection size", prompt, parent=self,
            initialvalue=20 if item.kind == "channel" else 0, minvalue=0, maxvalue=10000,
        )

    def _youtube_collection_entries(self, item: OnlineResult) -> list[OnlineResult] | None:
        limit = self._youtube_collection_limit(item)
        if limit is None:
            return None
        self.announce(f"Reading {item.title}. This may take a while.")
        try:
            entries = self.online.collection_entries(item.url, limit)
        except (MediaError, ValueError) as exc:
            messagebox.showerror("Could not read YouTube collection", str(exc), parent=self)
            return None
        if not entries:
            self.announce("No downloadable videos were found in that collection.")
            return None
        return entries

    def _browse_youtube_collection(self, item: OnlineResult) -> None:
        entries = self._youtube_collection_entries(item)
        if entries:
            self._choose_online_result(entries, f"{item.title}; {len(entries)} videos")

    def _download_youtube_collection(self, item: OnlineResult) -> None:
        entries = self._youtube_collection_entries(item)
        if not entries:
            return
        folder = filedialog.askdirectory(title=f"Choose folder for {item.title}", parent=self)
        if not folder:
            return
        completed = 0
        failures: list[str] = []
        extension = self.online_download_format
        for index, entry in enumerate(entries, 1):
            safe_title = (re.sub(r'[<>:"/\\|?*]+', "_", entry.title).strip(" .") or f"video {index}")[:100]
            target = os.path.join(folder, f"{index:04d} - {safe_title}{extension}")
            handle, wav_path = tempfile.mkstemp(prefix="quickedit-batch-", suffix=".wav"); os.close(handle)
            raw_path = wav_path + ".download"
            try:
                self.announce(f"Downloading {index} of {len(entries)}: {entry.title}.")
                self.online.download_source(entry.url, raw_path)
                self.media.decode(raw_path, wav_path)
                self.media.encode(
                    wav_path, target,
                    sample_rate=self.online_download_sample_rate,
                    bitrate_kbps=self.online_download_bitrate,
                )
                completed += 1
            except (MediaError, OSError) as exc:
                failures.append(f"{entry.title}: {exc}")
            finally:
                for temporary in (wav_path, raw_path):
                    if os.path.isfile(temporary):
                        os.remove(temporary)
        message = f"Downloaded {completed} of {len(entries)} videos to {folder}."
        if failures:
            message += f" {len(failures)} failed. First failure: {failures[0]}"
        self.announce(message)
        messagebox.showinfo("YouTube collection download finished", message, parent=self)

    def _import_online_result(self, item: OnlineResult) -> None:
        handle, download_path = tempfile.mkstemp(prefix="quickedit-online-", suffix=".wav")
        os.close(handle)
        raw_path = download_path + ".download"
        try:
            self.announce(f"Importing {item.title}. This may take a while.")
            if item.provider == "AudioVault":
                if not self.ensure_audiovault_login():
                    return
                self.online.audiovault_download(item.url, raw_path)
                self.media.decode(raw_path, download_path)
            else:
                self.online.download_source(item.url, raw_path)
                self.media.decode(raw_path, download_path)
            self._load_online_wav(download_path, item.title)
        except (MediaError, OSError) as exc:
            messagebox.showerror("Online import failed", str(exc), parent=self)
        finally:
            if os.path.isfile(download_path):
                os.remove(download_path)
            if os.path.isfile(raw_path):
                os.remove(raw_path)

    def _download_online_result(self, item: OnlineResult) -> None:
        extension = self.online_download_format
        safe_title = (re.sub(r'[<>:"/\\|?*]+', "_", item.title).strip(" .") or "online-audio")[:100]
        target_path = filedialog.asksaveasfilename(
            title="Download online audio as",
            defaultextension=extension,
            initialfile=f"{safe_title}{extension}",
            filetypes=[(f"{extension.lstrip('.').upper()} audio", f"*{extension}"), ("All files", "*.*")],
            parent=self,
        )
        if not target_path:
            return
        if not os.path.splitext(target_path)[1]:
            target_path += extension
        handle, wav_path = tempfile.mkstemp(prefix="quickedit-download-", suffix=".wav")
        os.close(handle)
        raw_path = wav_path + ".download"
        try:
            self.announce(f"Downloading {item.title}. This may take a while.")
            if item.provider == "AudioVault":
                if not self.ensure_audiovault_login():
                    return
                self.online.audiovault_download(item.url, raw_path)
                self.media.decode(raw_path, wav_path)
            else:
                self.online.download_source(item.url, raw_path)
                self.media.decode(raw_path, wav_path)
            self.media.encode(
                wav_path, target_path,
                sample_rate=self.online_download_sample_rate,
                bitrate_kbps=self.online_download_bitrate,
            )
        except (MediaError, OSError) as exc:
            messagebox.showerror("Online download failed", str(exc), parent=self)
            return
        finally:
            for temporary in (wav_path, raw_path):
                if os.path.isfile(temporary):
                    os.remove(temporary)
        self._remember_recent(target_path)
        self.announce(f"Downloaded {os.path.basename(target_path)}.")

    def save(self) -> None:
        document = self.require_document()
        if not document:
            return
        if not document.save_path:
            self.save_as()
            return
        self._save_to(document.save_path)

    def save_as(self) -> None:
        document = self.require_document()
        if not document:
            return
        stem = os.path.splitext(os.path.basename(document.source_path))[0]
        path = filedialog.asksaveasfilename(
            title="Save edited audio as",
            defaultextension=".wav",
            initialfile=f"{stem}-edited.wav",
            filetypes=[
                ("WAV audio", "*.wav"),
                ("MP3 audio", "*.mp3"),
                ("FLAC audio", "*.flac"),
                ("Ogg Vorbis audio", "*.ogg"),
                ("Ogg audio", "*.oga"),
                ("Opus audio", "*.opus"),
                ("M4A AAC audio", "*.m4a"),
                ("Windows Media Audio", "*.wma"),
                ("MPEG Layer II audio", "*.mp2"),
                ("AIFF audio", "*.aiff"),
                ("Sun AU or SND", "*.au *.snd"),
                ("Apple CAF", "*.caf"),
                ("Creative Voice", "*.voc"),
                ("Sony Wave64", "*.w64"),
                ("RF64", "*.rf64"),
                ("Raw PCM", "*.pcm *.raw"),
                ("AC-3", "*.ac3"),
                ("Enhanced AC-3", "*.eac3"),
                ("AMR narrowband", "*.amr"),
                ("True Audio", "*.tta"),
                ("WavPack", "*.wv"),
                ("CRI ADX", "*.adx"),
                ("SoX native", "*.sox"),
                ("IRCAM audio", "*.ircam"),
                ("QuickTime MOV with ALAC", "*.mov"),
                ("MPEG-4 audio container", "*.mp4"),
                ("3GP mobile audio", "*.3gp"),
                ("3G2 mobile audio", "*.3g2"),
                ("Matroska audio", "*.mka *.mkv"),
                ("WebM Opus audio", "*.webm"),
                ("Other FFmpeg-supported format", "*.*"),
            ],
        )
        if not path:
            return
        self._save_to(path)

    def _save_to(self, path: str) -> None:
        document = self.document
        if not document:
            return
        try:
            extension = os.path.splitext(path)[1].lower()
            conversion_requested = any((
                self.export_sample_rate and self.export_sample_rate != document.frame_rate,
                self.export_channels and self.export_channels != document.channels,
                self.export_bit_depth and self.export_bit_depth != document.sample_width * 8,
            ))
            if extension == ".wav" and not conversion_requested:
                self._write_wav(path, document.frames)
            elif extension in {".raw", ".pcm"} and not conversion_requested:
                with open(path, "wb") as target:
                    target.write(document.frames)
            else:
                handle, wav_path = tempfile.mkstemp(prefix="quickedit-export-", suffix=".wav")
                os.close(handle)
                try:
                    self._write_wav(wav_path, document.frames)
                    self.media.encode(
                        wav_path, path,
                        sample_rate=self.export_sample_rate or document.frame_rate,
                        channels=self.export_channels or document.channels,
                        bit_depth=self.export_bit_depth or document.sample_width * 8,
                        bitrate_kbps=self.export_bitrate,
                    )
                finally:
                    if os.path.isfile(wav_path):
                        os.remove(wav_path)
        except (wave.Error, OSError, MediaError) as exc:
            messagebox.showerror("Could not save audio", str(exc), parent=self)
            return
        document.save_path = path
        self.title(f"QuickEdit - {os.path.basename(path)}")
        self.announce(f"Saved {os.path.basename(path)}.")

    def output_format_settings(self) -> None:
        document = self.require_document()
        if not document:
            return
        sample_rate = simpledialog.askinteger(
            "Output sample rate", "Sample rate in Hz:", parent=self,
            initialvalue=self.export_sample_rate or document.frame_rate, minvalue=1000, maxvalue=384000,
        )
        if sample_rate is None:
            return
        bit_depth = simpledialog.askinteger(
            "Output bit depth", "PCM bit depth: 8, 16, 24, or 32:", parent=self,
            initialvalue=self.export_bit_depth or document.sample_width * 8, minvalue=8, maxvalue=32,
        )
        if bit_depth is None:
            return
        if bit_depth not in (8, 16, 24, 32):
            messagebox.showerror("Invalid bit depth", "Choose 8, 16, 24, or 32 bits.", parent=self)
            return
        channels = simpledialog.askinteger(
            "Output channels", "Number of channels, usually 1 for mono or 2 for stereo:", parent=self,
            initialvalue=self.export_channels or document.channels, minvalue=1, maxvalue=8,
        )
        if channels is None:
            return
        bitrate = simpledialog.askinteger(
            "Compressed-audio bitrate", "Bitrate in kilobits per second:", parent=self,
            initialvalue=self.export_bitrate, minvalue=8, maxvalue=1536,
        )
        if bitrate is None:
            return
        self.export_sample_rate = sample_rate
        self.export_bit_depth = bit_depth
        self.export_channels = channels
        self.export_bitrate = bitrate
        self.announce(f"Output set to {sample_rate} Hz, {bit_depth}-bit, {channels} channels, {bitrate} kilobits per second for compressed formats.")

    def _write_wav(self, path: str, frames: bytes) -> None:
        document = self.document
        if not document:
            return
        with wave.open(path, "wb") as target:
            target.setnchannels(document.channels)
            target.setsampwidth(document.sample_width)
            target.setframerate(document.frame_rate)
            target.writeframes(frames)

    def refresh_details(self) -> None:
        document = self.document
        if not document:
            self.details_var.set("No audio is open.")
            return
        selection = document.selection()
        if selection:
            start, end = selection
            selection_text = (
                f"Selection: {format_time(document.seconds_at(start))} to "
                f"{format_time(document.seconds_at(end))}; "
                f"length {format_time(document.seconds_at(end - start))}"
            )
        else:
            selection_text = "Selection: none"
        channel_text = "mono" if document.channels == 1 else f"{document.channels} channels"
        midi_text = ""
        if document.midi_path:
            soundfont = os.path.basename(document.soundfont_path) if document.soundfont_path else "none"
            midi_text = f"MIDI source: {os.path.basename(document.midi_path)}\nSoundFont: {soundfont}\n"
        self.details_var.set(
            f"File: {os.path.basename(document.source_path)}\n"
            f"Duration: {format_time(document.duration)}\n"
            f"Format: {document.frame_rate} Hz, {document.sample_width * 8}-bit, {channel_text}\n"
            f"Cursor: {format_time(document.seconds_at(document.cursor_frame))}\n"
            f"Arrow movement: {self.navigation_step_text()}\n"
            f"{midi_text}"
            f"{selection_text}"
        )

    def announce_status(self) -> None:
        document = self.require_document()
        if not document:
            return
        selection = document.selection()
        message = (
            f"Cursor {format_time(document.seconds_at(document.cursor_frame))}. "
            f"Duration {format_time(document.duration)}. "
            f"Left and right move {self.navigation_step_text()}."
        )
        if selection:
            start, end = selection
            message += (
                f" Selection {format_time(document.seconds_at(start))} to "
                f"{format_time(document.seconds_at(end))}, "
                f"length {format_time(document.seconds_at(end - start))}."
            )
        else:
            message += " No selection."
        self.announce(message)

    def move_cursor(self, seconds: float) -> None:
        document = self.require_document()
        if not document:
            return
        was_playing = self.playing
        direction = self.play_direction
        document.cursor_frame = max(
            0,
            min(document.frame_count, document.cursor_frame + round(seconds * document.frame_rate)),
        )
        if was_playing:
            if direction > 0 and document.cursor_frame >= document.frame_count:
                self.stop(announce=False)
            elif direction < 0 and document.cursor_frame <= 0:
                self.stop(announce=False)
            elif not self._seek_active_playback(document.cursor_frame):
                if direction < 0:
                    self._play_reverse_from_cursor(announce=False)
                else:
                    self._play_forward_from_cursor(announce=False)
        self.refresh_details()
        self.set_status(f"Cursor {format_time(document.seconds_at(document.cursor_frame))}.")

    def set_cursor_frame(self, frame: int) -> None:
        document = self.require_document()
        if not document:
            return
        was_playing = self.playing
        direction = self.play_direction
        document.cursor_frame = max(0, min(document.frame_count, frame))
        if was_playing:
            if direction > 0 and document.cursor_frame >= document.frame_count:
                self.stop(announce=False)
            elif direction < 0 and document.cursor_frame <= 0:
                self.stop(announce=False)
            elif not self._seek_active_playback(document.cursor_frame):
                if direction < 0:
                    self._play_reverse_from_cursor(announce=False)
                else:
                    self._play_forward_from_cursor(announce=False)
        self.refresh_details()
        boundary = "beginning" if document.cursor_frame == 0 else "end" if document.cursor_frame == document.frame_count else "position"
        self.set_status(f"{boundary.capitalize()}. Cursor {format_time(document.seconds_at(document.cursor_frame))}.")

    def go_to_time(self) -> None:
        document = self.require_document()
        if not document:
            return
        value = simpledialog.askstring(
            "Go to time",
            "Enter seconds, minutes:seconds, or hours:minutes:seconds:",
            parent=self,
        )
        if value is None:
            return
        try:
            document.cursor_frame = document.frame_at(parse_time(value))
        except ValueError as exc:
            messagebox.showerror("Invalid time", str(exc), parent=self)
            return
        self.refresh_details()
        self.announce(f"Cursor {format_time(document.seconds_at(document.cursor_frame))}.")

    def set_selection_start(self) -> None:
        document = self.require_document()
        if not document:
            return
        document.selection_start = document.cursor_frame
        self.refresh_details()
        self.announce(f"Selection start {format_time(document.seconds_at(document.cursor_frame))}.")

    def set_selection_end(self) -> None:
        document = self.require_document()
        if not document:
            return
        document.selection_end = document.cursor_frame
        self.refresh_details()
        self.announce(f"Selection end {format_time(document.seconds_at(document.cursor_frame))}.")

    def select_all(self) -> None:
        document = self.require_document()
        if not document:
            return
        document.selection_start = 0
        document.selection_end = document.frame_count
        self.refresh_details()
        self.announce(f"Selected all audio. Length {format_time(document.duration)}.")

    def _checkpoint(self) -> None:
        if self.document:
            self.undo_stack.append(copy.deepcopy(self.document))
            self.redo_stack.clear()

    def delete_selection(self) -> None:
        document = self.require_document()
        if not document:
            return
        selection = document.selection()
        if not selection:
            self.announce("Nothing deleted. There is no selection.")
            return
        start, end = selection
        removed = document.seconds_at(end - start)
        self._checkpoint()
        document.frames = document.slice_bytes(0, start) + document.slice_bytes(end, document.frame_count)
        document.cursor_frame = start
        document.selection_start = None
        document.selection_end = None
        self.refresh_details()
        self.announce(f"Deleted {format_time(removed)}. Cursor {format_time(document.seconds_at(start))}.")

    def crop_selection(self) -> None:
        document = self.require_document()
        if not document:
            return
        selection = document.selection()
        if not selection:
            self.announce("Nothing cropped. There is no selection.")
            return
        start, end = selection
        self._checkpoint()
        document.frames = document.slice_bytes(start, end)
        document.cursor_frame = 0
        document.selection_start = None
        document.selection_end = None
        self.refresh_details()
        self.announce(f"Cropped to selection. New duration {format_time(document.duration)}.")

    def mix_audio_file(self) -> None:
        document = self.require_document()
        if not document:
            return
        path = filedialog.askopenfilename(title="Choose audio to mix", filetypes=[("Audio and media files", "*.*")])
        if not path:
            return
        handle, converted = tempfile.mkstemp(prefix="quickedit-mix-", suffix=".wav")
        os.close(handle)
        try:
            self.media.decode_to_format(path, converted, document.frame_rate, document.channels, document.sample_width)
            with wave.open(converted, "rb") as source:
                overlay = source.readframes(source.getnframes())
            start = document.cursor_frame
            existing = document.slice_bytes(start, min(document.frame_count, start + len(overlay) // document.frame_size))
            self.stop(announce=False)
            self._checkpoint()
            mixed = audio_effects.mix_pcm(existing, overlay, document.sample_width)
            end = start + len(existing) // document.frame_size
            document.frames = document.slice_bytes(0, start) + mixed + document.slice_bytes(end, document.frame_count)
            document.cursor_frame = start
            self.refresh_details()
            self.announce(f"Mixed {os.path.basename(path)} at {format_time(document.seconds_at(start))}.")
        except (OSError, wave.Error, MediaError) as exc:
            messagebox.showerror("Could not mix audio", str(exc), parent=self)
        finally:
            if os.path.isfile(converted):
                os.remove(converted)

    def crossfade_selection(self) -> None:
        document = self.require_document()
        if not document:
            return
        selection = document.selection()
        if not selection:
            self.announce("Set both brackets around the two adjoining sections to crossfade.")
            return
        start, end = selection
        try:
            blended = audio_effects.crossfade_halves(document.slice_bytes(start, end), document.sample_width, document.channels)
        except ValueError as exc:
            self.announce(str(exc))
            return
        self.stop(announce=False)
        self._checkpoint()
        document.frames = document.slice_bytes(0, start) + blended + document.slice_bytes(end, document.frame_count)
        document.cursor_frame = start
        document.selection_start = start
        document.selection_end = start + len(blended) // document.frame_size
        self.refresh_details()
        self.announce(f"Crossfade complete. New overlap length {format_time(document.seconds_at(len(blended) // document.frame_size))}.")

    def _effect_range(self) -> tuple[AudioDocument, int, int] | None:
        document = self.require_document()
        if not document:
            return None
        selection = document.selection()
        start, end = selection if selection else (0, document.frame_count)
        if start == end:
            self.announce("There is no audio to process.")
            return None
        return document, start, end

    def _apply_effect(self, name: str, transform) -> None:
        target = self._effect_range()
        if not target:
            return
        document, start, end = target
        self.stop(announce=False)
        source = document.slice_bytes(start, end)
        try:
            changed = transform(source, document)
        except ValueError as exc:
            self.announce(str(exc))
            return
        self._checkpoint()
        document.frames = document.slice_bytes(0, start) + changed + document.slice_bytes(end, document.frame_count)
        document.cursor_frame = start
        self.refresh_details()
        scope = "selection" if document.selection() else "whole file"
        self.announce(f"{name} applied to {scope}.")

    @property
    def effect_preset_path(self) -> str:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "QuickEdit", "effect-presets.json")

    def _load_effect_presets(self) -> dict:
        try:
            with open(self.effect_preset_path, "r", encoding="utf-8") as source:
                data = json.load(source)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_effect_presets(self, presets: dict) -> None:
        os.makedirs(os.path.dirname(self.effect_preset_path), exist_ok=True)
        with open(self.effect_preset_path, "w", encoding="utf-8") as target:
            json.dump(presets, target, indent=2, sort_keys=True)

    def _accessible_text_prompt(self, title: str, label: str) -> str | None:
        dialog = tk.Toplevel(self); dialog.title(title); dialog.transient(self); dialog.grab_set()
        value = tk.StringVar(); result: list[str] = []
        tk.Label(dialog, text=label).pack(anchor="w", padx=12, pady=(12, 4))
        entry = ttk.Entry(dialog, textvariable=value, width=45, takefocus=True); entry.pack(fill="x", padx=12)
        buttons = tk.Frame(dialog); buttons.pack(fill="x", padx=12, pady=12)
        def accept(event=None):
            name = value.get().strip()
            if name: result.append(name); dialog.destroy()
            else: self.screen_reader.speak(f"{label} cannot be blank.")
            return "break"
        entry.bind("<FocusIn>", lambda event: self.screen_reader.speak(f"{label}, edit.")); entry.bind("<Return>", accept)
        self.accessible_button(buttons, "Save Preset", accept).pack(side="left")
        self.accessible_button(buttons, "Cancel Preset", dialog.destroy).pack(side="right")
        entry.focus_set(); self.wait_window(dialog)
        return result[0] if result else None

    def _parse_effect_values(self, fields, values, entries) -> dict[str, float] | None:
        parsed = {}
        for key, label, default, minimum, maximum in fields:
            try: value = float(values[key].get().strip())
            except ValueError:
                self.screen_reader.speak(f"{label} must be a number."); entries[key].focus_set(); return None
            if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
                self.screen_reader.speak(f"{label} is outside its allowed range."); entries[key].focus_set(); return None
            parsed[key] = value
        return parsed

    def _effect_preview_source(self) -> tuple[AudioDocument, bytes] | None:
        """Return at most ten seconds, starting at the selection or cursor."""
        target = self._effect_range()
        if not target:
            return None
        doc, start, end = target
        if not doc.selection():
            start = min(doc.cursor_frame, end - 1)
        end = min(end, start + doc.frame_rate * 10)
        return doc, doc.slice_bytes(start, end)

    def stop_effect_preview(self) -> None:
        if self.preview_process and self.preview_process.poll() is None:
            self.preview_process.terminate()
            try:
                self.preview_process.wait(timeout=1)
            except Exception:
                pass
        self.preview_process = None
        for path in self.effect_preview_files:
            self._remove_preview_file(path)
        self.effect_preview_files.clear()

    def _play_effect_preview(self, title: str, data: bytes, doc: AudioDocument, affected: bool) -> None:
        self.stop_effect_preview()
        handle, path = tempfile.mkstemp(prefix="quickedit-effect-preview-", suffix=".wav")
        os.close(handle)
        self.effect_preview_files.add(path)
        self._write_wav(path, data)
        self.preview_process = self.media.start_playback(path, self.output_device)
        kind = "effect" if affected else "original"
        self.announce(f"Playing {kind} preview for {title}, up to 10 seconds.")

    def _preview_effect_original(self, title: str) -> None:
        source = self._effect_preview_source()
        if not source:
            return
        doc, data = source
        try:
            self._play_effect_preview(title, data, doc, affected=False)
        except (OSError, ValueError, MediaError) as exc:
            messagebox.showerror(f"{title} preview failed", str(exc), parent=self)

    def _preview_removed_noise(self, title: str, settings: dict[str, float]) -> None:
        source_data = self._effect_preview_source()
        if not source_data:
            return
        doc, data = source_data
        self.stop_effect_preview()
        source_handle, source = tempfile.mkstemp(prefix="quickedit-restoration-source-", suffix=".wav")
        result_handle, rendered = tempfile.mkstemp(prefix="quickedit-removed-noise-", suffix=".wav")
        os.close(source_handle); os.close(result_handle)
        self.effect_preview_files.update((source, rendered))
        try:
            self._write_wav(source, data)
            if title == "Tape Hiss Reduction":
                audio_filter = f"afftdn=nr={settings['reduction']:g}:nf={settings['floor']:g}:nt=white:tn=1:om=noise"
            else:
                repair = self._vinyl_repair_filter(settings)
                audio_filter = (
                    f"asplit=2[original][work];[work]{repair}[clean];"
                    "[original][clean]amix=inputs=2:weights='1 -1':normalize=0"
                )
            self.media.transform_wav(source, rendered, audio_filter, doc.sample_width)
            self.preview_process = self.media.start_playback(rendered, self.output_device)
            self.announce(f"Playing only the noise removed by {title}, up to 10 seconds.")
        except (OSError, ValueError, MediaError) as exc:
            self.stop_effect_preview()
            messagebox.showerror(f"{title} noise audition failed", str(exc), parent=self)

    def _preview_effect_settings(self, title: str, s: dict[str, float]) -> None:
        source_data = self._effect_preview_source()
        if not source_data:
            return
        doc, data = source_data
        pcm = {
            "Amplify or Reduce Volume": lambda: audio_effects.amplify_db(data, doc.sample_width, s["db"]),
            "Echo": lambda: audio_effects.echo(data, doc.sample_width, doc.channels, doc.frame_rate, s["delay"], s["feedback"] / 100, s["wet"] / 100),
            "Flanger": lambda: audio_effects.flanger(data, doc.sample_width, doc.channels, doc.frame_rate, s["rate"], s["depth"], s["wet"] / 100),
            "Chorus": lambda: audio_effects.chorus(data, doc.sample_width, doc.channels, doc.frame_rate, s["wet"] / 100),
            "Noise Gate": lambda: audio_effects.noise_gate(data, doc.sample_width, doc.channels, doc.frame_rate, s["threshold"], s["attack"], s["release"]),
            "Noise Reduction": lambda: audio_effects.noise_reduce(data, doc.sample_width, doc.channels, doc.frame_rate, s["strength"] / 100),
            "Low-Pass Filter": lambda: audio_effects.lowpass(data, doc.sample_width, doc.channels, doc.frame_rate, s["cutoff"]),
            "High-Pass Filter": lambda: audio_effects.highpass(data, doc.sample_width, doc.channels, doc.frame_rate, s["cutoff"]),
            "Compressor": lambda: audio_effects.compressor(data, doc.sample_width, doc.channels, doc.frame_rate, s["threshold"], s["ratio"], s["attack"], s["release"]),
        }
        filters = {
            "Room Reverb": lambda: self._reverb_filter(s),
            "Bass and Treble": lambda: f"bass=g={s['bass']:g},treble=g={s['treble']:g}",
            "Tremolo": lambda: f"tremolo=f={s['rate']:g}:d={s['depth']/100:g}",
            "Distortion": lambda: f"volume={1+s['amount']/8:g},alimiter=limit=0.95:level=false",
            "Vinyl Click and Crackle Removal": lambda: self._vinyl_repair_filter(s),
            "Tape Hiss Reduction": lambda: f"afftdn=nr={s['reduction']:g}:nf={s['floor']:g}:nt=white:tn=1",
            "Add Tape Hiss": lambda: self._tape_hiss_filter(s),
            "Add Vinyl Crackle": lambda: self._vinyl_crackle_filter(s),
            "Expander": lambda: self._expander_filter(s),
            "Limiter": lambda: self._limiter_filter(s),
            "Band-Pass Filter": lambda: f"bandpass=f={s['frequency']:g}:width_type=q:width={s['q']:g}",
            "Notch Filter": lambda: f"bandreject=f={s['frequency']:g}:width_type=q:width={s['q']:g}",
            "Graphic Equalizer": lambda: self._graphic_eq_filter(s),
            "Parametric Equalizer": lambda: f"equalizer=f={s['frequency']:g}:width_type=q:width={s['q']:g}:g={s['gain']:g}",
            "De-Esser": lambda: f"deesser=i={s['intensity']/100:g}:m={s['maximum']/100:g}:f={s['frequency']/100:g}",
            "Change Speed": lambda: self.media.tempo_filter(s["value"] / 100),
            "Change Pitch": lambda: f"asetrate={doc.frame_rate}*{2**(s['value']/12):.8g},aresample={doc.frame_rate},{self.media.tempo_filter(1/(2**(s['value']/12)))}",
            "Tape Pitch and Speed": lambda: f"asetrate={doc.frame_rate}*{2**(s['value']/12):.8g},aresample={doc.frame_rate}",
        }
        self.stop_effect_preview()
        self.announce(f"Preparing {title} effect preview, up to 10 seconds.")
        self.update_idletasks()
        handle, source = tempfile.mkstemp(prefix="quickedit-preview-source-", suffix=".wav"); os.close(handle)
        self.effect_preview_files.add(source)
        rendered = source
        try:
            if title in pcm:
                rendered_data = pcm[title]()
                self._play_effect_preview(title, rendered_data, doc, affected=True)
                return
            elif title in filters:
                self._write_wav(source, data)
                handle, rendered = tempfile.mkstemp(prefix="quickedit-preview-result-", suffix=".wav"); os.close(handle)
                self.effect_preview_files.add(rendered)
                self.media.transform_wav(source, rendered, filters[title](), doc.sample_width)
            else: return
            self.preview_process = self.media.start_playback(rendered, self.output_device)
            self.announce(f"Playing effect preview for {title}, up to 10 seconds.")
        except (OSError, ValueError, MediaError) as exc:
            self.stop_effect_preview()
            messagebox.showerror(f"{title} preview failed", str(exc), parent=self)

    @staticmethod
    def _remove_preview_file(path: str) -> None:
        try: os.remove(path)
        except OSError: pass

    def effect_parameters(
        self,
        title: str,
        fields: list[tuple[str, str, float, float | None, float | None]],
    ) -> dict[str, float] | None:
        """Show one NVDA-friendly window for all numeric effect parameters."""
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        dialog.grab_set()
        values: dict[str, tk.StringVar] = {}
        entries: dict[str, ttk.Entry] = {}
        result: list[dict[str, float]] = []
        tk.Label(dialog, text=f"{title} settings", font=("Segoe UI", 12, "bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 8)
        )
        defaults = {key: default for key, label, default, minimum, maximum in fields}
        custom_presets = self._load_effect_presets().get(title, {})
        named_presets = {"Default": defaults, **self.BUILTIN_EFFECT_PRESETS.get(title, {}), **custom_presets}
        tk.Label(dialog, text="Effect presets").grid(row=1, column=0, sticky="w", padx=12, pady=(2, 2))
        preset_list = tk.Listbox(dialog, exportselection=False, height=5, takefocus=True)
        for name in named_presets:
            preset_list.insert("end", name)
        preset_list.selection_set(0); preset_list.activate(0)
        preset_list.grid(row=2, column=0, sticky="ew", padx=12)
        for row, (key, label, default, minimum, maximum) in enumerate(fields, 2):
            tk.Label(dialog, text=label).grid(row=row * 2 - 1, column=0, sticky="w", padx=12, pady=(5, 2))
            variable = tk.StringVar(value=f"{default:g}")
            entry = ttk.Entry(dialog, textvariable=variable, width=28, takefocus=True)
            entry.grid(row=row * 2, column=0, sticky="ew", padx=12)
            entry.bind("<FocusIn>", lambda event, spoken=label: self.screen_reader.speak(f"{spoken}, edit."))
            values[key] = variable
            entries[key] = entry
        buttons = tk.Frame(dialog)
        buttons.grid(row=len(fields) * 2 + 3, column=0, sticky="ew", padx=12, pady=12)

        def apply(event=None) -> str:
            parsed: dict[str, float] = {}
            for key, label, default, minimum, maximum in fields:
                try:
                    value = float(values[key].get().strip())
                except ValueError:
                    self.screen_reader.speak(f"{label} must be a number.")
                    entries[key].focus_set()
                    return "break"
                if minimum is not None and value < minimum or maximum is not None and value > maximum:
                    range_text = (
                        f"from {minimum:g} through {maximum:g}" if minimum is not None and maximum is not None
                        else f"at least {minimum:g}" if minimum is not None else f"no more than {maximum:g}"
                    )
                    self.screen_reader.speak(f"{label} must be {range_text}.")
                    entries[key].focus_set()
                    return "break"
                parsed[key] = value
            self.stop_effect_preview()
            result.append(parsed)
            dialog.destroy()
            return "break"

        def choose_preset(event=None) -> None:
            selected = preset_list.curselection()
            if not selected: return
            name = preset_list.get(selected[0])
            for key, value in named_presets[name].items():
                if key in values: values[key].set(f"{value:g}")
            self.screen_reader.speak(f"{title} preset {name} loaded.")

        def preview(event=None) -> str:
            parsed = self._parse_effect_values(fields, values, entries)
            if parsed is not None: self._preview_effect_settings(title, parsed)
            return "break"

        def preview_original(event=None) -> str:
            self._preview_effect_original(title)
            return "break"

        def preview_removed(event=None) -> str:
            parsed = self._parse_effect_values(fields, values, entries)
            if parsed is not None: self._preview_removed_noise(title, parsed)
            return "break"

        def close_dialog(event=None) -> str:
            self.stop_effect_preview()
            dialog.destroy()
            return "break"

        def add_preset() -> None:
            parsed = self._parse_effect_values(fields, values, entries)
            if parsed is None: return
            name = self._accessible_text_prompt("Add Effect Preset", "Preset name")
            if not name: return
            all_custom = self._load_effect_presets(); all_custom.setdefault(title, {})[name] = parsed
            self._save_effect_presets(all_custom)
            named_presets[name] = parsed; preset_list.insert("end", name)
            preset_list.selection_clear(0, "end"); preset_list.selection_set("end"); preset_list.see("end")
            self.screen_reader.speak(f"Preset {name} added.")

        preset_list.bind("<FocusIn>", lambda event: self.screen_reader.speak(f"{title} effect presets list."))
        preset_list.bind("<<ListboxSelect>>", choose_preset)
        self.accessible_button(buttons, "Preview Original", preview_original).pack(side="left")
        self.accessible_button(buttons, f"Preview {title} Effect", preview).pack(side="left", padx=6)
        if title in {"Tape Hiss Reduction", "Vinyl Click and Crackle Removal"}:
            self.accessible_button(buttons, "Preview Removed Noise Only", preview_removed).pack(side="left")
        self.accessible_button(buttons, f"Apply {title}", apply).pack(side="left", padx=6)
        self.accessible_button(buttons, "Add Preset", add_preset).pack(side="left")
        self.accessible_button(buttons, f"Cancel {title}", close_dialog).pack(side="right")
        for entry in entries.values():
            entry.bind("<Return>", apply)
        dialog.columnconfigure(0, weight=1)
        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        dialog.bind("<Escape>", close_dialog)
        next(iter(entries.values())).focus_set()
        self.wait_window(dialog)
        return result[0] if result else None

    def amplify(self) -> None:
        settings = self.effect_parameters("Amplify or Reduce Volume", [("db", "Volume change in decibels, minus 96 through plus 24", 3, -96, 24)])
        if settings:
            value = settings["db"]
            self._apply_ffmpeg_effect(f"Volume change of {value:g} decibels", f"volume={value:g}dB")

    def _insert_generated_audio(self, frames: bytes, title: str, rate: int = 44100, width: int = 2, channels: int = 1) -> None:
        self.stop(announce=False)
        created_document = self.document is None
        if created_document:
            self.document = AudioDocument(channels, width, rate, frames, f"{title}.wav")
            self.document.cursor_frame = self.document.frame_count
        else:
            document = self.document
            if (rate, width, channels) != (document.frame_rate, document.sample_width, document.channels):
                raise ValueError("Generated audio format does not match the open document.")
            self._checkpoint()
            selection = document.selection()
            start, end = selection if selection else (document.cursor_frame, document.cursor_frame)
            document.frames = document.slice_bytes(0, start) + frames + document.slice_bytes(end, document.frame_count)
            document.cursor_frame = start + len(frames) // document.frame_size
            document.selection_start = document.selection_end = None
        if created_document:
            self.undo_stack.clear()
        self.redo_stack.clear()
        self.title(f"QuickEdit - {title}")
        self.refresh_details()
        self.announce(f"Generated {title}.")

    def _preview_generated_audio(
        self, frames: bytes, rate: int, width: int, channels: int, label: str
    ) -> None:
        self.stop_effect_preview()
        handle, path = tempfile.mkstemp(prefix="quickedit-generator-preview-", suffix=".wav")
        os.close(handle)
        self.effect_preview_files.add(path)
        with wave.open(path, "wb") as target:
            target.setnchannels(channels)
            target.setsampwidth(width)
            target.setframerate(rate)
            target.writeframes(frames)
        self.preview_process = self.media.start_playback(path, self.output_device)
        self.announce(f"Playing {label} preview, up to 10 seconds.")

    def generate_tone(self) -> None:
        dialog = tk.Toplevel(self); dialog.title("Tone or Noise Generator"); dialog.transient(self); dialog.grab_set()
        result: list[tuple[str, float, float, float]] = []
        waveforms = ("sine", "square", "triangle", "sawtooth", "white noise", "pink noise")
        tk.Label(dialog, text="Waveform").grid(row=0, column=0, sticky="w", padx=12, pady=(12, 2))
        waveform_list = tk.Listbox(dialog, exportselection=False, height=6, takefocus=True)
        for item in waveforms: waveform_list.insert("end", item)
        waveform_list.selection_set(0); waveform_list.activate(0); waveform_list.grid(row=1, column=0, sticky="ew", padx=12)
        field_specs = (
            ("Frequency in Hertz; ignored for noise", "440"),
            ("Duration in seconds", "1"),
            ("Level in dBFS; minus 60 through 0", "-12"),
        )
        variables: list[tk.StringVar] = []; entries: list[ttk.Entry] = []
        for offset, (label, default) in enumerate(field_specs, 2):
            tk.Label(dialog, text=label).grid(row=offset * 2 - 2, column=0, sticky="w", padx=12, pady=(6, 2))
            variable = tk.StringVar(value=default); entry = ttk.Entry(dialog, textvariable=variable, takefocus=True)
            entry.grid(row=offset * 2 - 1, column=0, sticky="ew", padx=12)
            entry.bind("<FocusIn>", lambda event, spoken=label: self.screen_reader.speak(f"{spoken}, edit."))
            variables.append(variable); entries.append(entry)
        buttons = tk.Frame(dialog); buttons.grid(row=8, column=0, sticky="ew", padx=12, pady=12)
        def settings() -> tuple[str, float, float, float] | None:
            try: frequency, duration, level = (float(item.get().strip()) for item in variables)
            except ValueError:
                self.screen_reader.speak("Frequency, duration, and level must be numbers."); return None
            if not 1 <= frequency <= 192000: self.screen_reader.speak("Frequency must be from 1 through 192000 Hertz."); entries[0].focus_set(); return None
            if not .01 <= duration <= 3600: self.screen_reader.speak("Duration must be from point 01 through 3600 seconds."); entries[1].focus_set(); return None
            if not -60 <= level <= 0: self.screen_reader.speak("Level must be from minus 60 through 0 dBFS."); entries[2].focus_set(); return None
            selected = waveform_list.curselection(); kind = waveforms[selected[0]] if selected else "sine"
            return kind, frequency, duration, level
        def preview(event=None) -> str:
            chosen = settings()
            if chosen:
                kind, frequency, duration, level = chosen
                preview_duration = min(duration, 10)
                document = self.document
                rate, width, channels = (document.frame_rate, document.sample_width, document.channels) if document else (44100, 2, 1)
                try:
                    frames = signal_generator.generate_waveform(kind, frequency, preview_duration, rate, width, channels, level)
                    self._preview_generated_audio(frames, rate, width, channels, f"{kind} tone")
                except (OSError, ValueError, MediaError) as exc:
                    messagebox.showerror("Could not preview tone", str(exc), parent=dialog)
            return "break"
        def accept(event=None) -> str:
            chosen = settings()
            if chosen:
                self.stop_effect_preview(); result.append(chosen); dialog.destroy()
            return "break"
        def cancel(event=None) -> str: self.stop_effect_preview(); dialog.destroy(); return "break"
        waveform_list.bind("<FocusIn>", lambda event: self.screen_reader.speak("Waveform list. Use up and down arrows."))
        waveform_list.bind("<<ListboxSelect>>", lambda event: self.screen_reader.speak(f"{waveform_list.get(waveform_list.curselection()[0])} waveform") if waveform_list.curselection() else None)
        for entry in entries: entry.bind("<Return>", accept)
        self.accessible_button(buttons, "Preview Tone", preview).pack(side="left")
        self.accessible_button(buttons, "Generate Tone", accept).pack(side="left", padx=8)
        self.accessible_button(buttons, "Cancel Tone Generator", cancel).pack(side="right")
        dialog.bind("<Escape>", cancel); dialog.protocol("WM_DELETE_WINDOW", cancel); dialog.columnconfigure(0, weight=1)
        waveform_list.focus_set(); self.wait_window(dialog)
        if not result: return
        kind, frequency, duration, level = result[0]
        document = self.document
        rate, width, channels = (document.frame_rate, document.sample_width, document.channels) if document else (44100, 2, 1)
        try:
            frames = signal_generator.generate_waveform(kind, frequency, duration, rate, width, channels, level)
            self._insert_generated_audio(frames, f"{kind.title()} {frequency:g} Hz", rate, width, channels)
        except ValueError as exc:
            messagebox.showerror("Could not generate tone", str(exc), parent=self)

    def generate_phone_keys(self, kind: str) -> None:
        dialog = tk.Toplevel(self); dialog.title(f"{kind} Telephone Tone Generator"); dialog.transient(self); dialog.grab_set()
        result: list[tuple[str, float]] = []; digits_var = tk.StringVar(); speed_var = tk.StringVar(value="8")
        tk.Label(dialog, text=f"{kind} key sequence").grid(row=0, column=0, sticky="w", padx=12, pady=(12, 2))
        digits_entry = ttk.Entry(dialog, textvariable=digits_var, takefocus=True); digits_entry.grid(row=1, column=0, sticky="ew", padx=12)
        tk.Label(dialog, text="Symbols per second; point 5 through 50").grid(row=2, column=0, sticky="w", padx=12, pady=(8, 2))
        speed_entry = ttk.Entry(dialog, textvariable=speed_var, takefocus=True); speed_entry.grid(row=3, column=0, sticky="ew", padx=12)
        buttons = tk.Frame(dialog); buttons.grid(row=4, column=0, sticky="ew", padx=12, pady=12)
        def settings() -> tuple[str, float] | None:
            digits = digits_var.get().strip()
            if not digits: self.screen_reader.speak("Key sequence cannot be blank."); digits_entry.focus_set(); return None
            try: speed = float(speed_var.get().strip())
            except ValueError: self.screen_reader.speak("Symbols per second must be a number."); speed_entry.focus_set(); return None
            if not .5 <= speed <= 50: self.screen_reader.speak("Symbols per second must be from point 5 through 50."); speed_entry.focus_set(); return None
            return digits, speed
        def preview(event=None) -> str:
            chosen = settings()
            if chosen:
                digits, speed = chosen
                document = self.document
                rate, width, channels = (document.frame_rate, document.sample_width, document.channels) if document else (44100, 2, 1)
                try:
                    frames = signal_generator.generate_phone_keys(kind, digits, speed, rate, width, channels)
                    max_bytes = rate * width * channels * 10
                    self._preview_generated_audio(frames[:max_bytes], rate, width, channels, f"{kind} telephone tones")
                except (OSError, ValueError, MediaError) as exc:
                    messagebox.showerror(f"Could not preview {kind}", str(exc), parent=dialog)
            return "break"
        def accept(event=None) -> str:
            chosen = settings()
            if chosen:
                self.stop_effect_preview(); result.append(chosen); dialog.destroy()
            return "break"
        def cancel(event=None) -> str: self.stop_effect_preview(); dialog.destroy(); return "break"
        digits_entry.bind("<FocusIn>", lambda event: self.screen_reader.speak(f"{kind} key sequence, edit."))
        speed_entry.bind("<FocusIn>", lambda event: self.screen_reader.speak("Symbols per second, edit."))
        digits_entry.bind("<Return>", accept); speed_entry.bind("<Return>", accept)
        self.accessible_button(buttons, f"Preview {kind} Tones", preview).pack(side="left")
        self.accessible_button(buttons, f"Generate {kind} Tones", accept).pack(side="left", padx=8)
        self.accessible_button(buttons, f"Cancel {kind} Generator", cancel).pack(side="right")
        dialog.bind("<Escape>", cancel); dialog.protocol("WM_DELETE_WINDOW", cancel); dialog.columnconfigure(0, weight=1)
        digits_entry.focus_set(); self.wait_window(dialog)
        if not result: return
        digits, speed = result[0]
        document = self.document
        rate, width, channels = (document.frame_rate, document.sample_width, document.channels) if document else (44100, 2, 1)
        try:
            frames = signal_generator.generate_phone_keys(kind, digits, speed, rate, width, channels)
            self._insert_generated_audio(frames, f"{kind} {digits}", rate, width, channels)
        except ValueError as exc:
            messagebox.showerror(f"Could not generate {kind}", str(exc), parent=self)

    def censor_selection(self) -> None:
        document = self.require_document()
        if not document or not document.selection():
            self.announce("Set both brackets around the word or audio to censor.")
            return
        dialog = tk.Toplevel(self); dialog.title("Censor Selection"); dialog.transient(self); dialog.grab_set()
        methods = ("beep", "buzz", "reverse", "silence", "remove"); result: list[str] = []
        tk.Label(dialog, text="Censor method").pack(anchor="w", padx=12, pady=(12, 2))
        choices = tk.Listbox(dialog, exportselection=False, height=5, takefocus=True)
        for item in methods: choices.insert("end", item)
        choices.selection_set(0); choices.activate(0); choices.pack(fill="x", padx=12)
        buttons = tk.Frame(dialog); buttons.pack(fill="x", padx=12, pady=12)
        def accept(event=None) -> str:
            selected = choices.curselection()
            if selected: result.append(methods[selected[0]])
            dialog.destroy(); return "break"
        def cancel(event=None) -> str: dialog.destroy(); return "break"
        choices.bind("<FocusIn>", lambda event: self.screen_reader.speak("Censor method list. Use up and down arrows."))
        choices.bind("<<ListboxSelect>>", lambda event: self.screen_reader.speak(f"{choices.get(choices.curselection()[0])} censor method") if choices.curselection() else None)
        choices.bind("<Return>", accept)
        self.accessible_button(buttons, "Apply Censor", accept).pack(side="left")
        self.accessible_button(buttons, "Cancel Censor", cancel).pack(side="right")
        dialog.bind("<Escape>", cancel); dialog.protocol("WM_DELETE_WINDOW", cancel); choices.focus_set(); self.wait_window(dialog)
        if not result: return
        method = result[0]
        start, end = document.selection()
        duration = document.seconds_at(end - start)
        if method in {"beep", "buzz"}:
            kind, frequency = ("sine", 1000) if method == "beep" else ("square", 180)
            replacement = signal_generator.generate_waveform(kind, frequency, duration, document.frame_rate, document.sample_width, document.channels, -9)
        elif method == "reverse":
            replacement = document.reversed_bytes(start, end)
        elif method == "silence":
            replacement = audio_effects.silence(document.slice_bytes(start, end), document.sample_width)
        elif method == "remove":
            replacement = b""
        else:
            messagebox.showerror("Unknown censor method", "Choose beep, buzz, reverse, silence, or remove.", parent=self)
            return
        self.stop(announce=False)
        self._checkpoint()
        document.frames = document.slice_bytes(0, start) + replacement + document.slice_bytes(end, document.frame_count)
        document.cursor_frame = start
        document.selection_start = document.selection_end = None
        self.refresh_details()
        self.announce(f"Selection censored with {method}.")

    def normalize_audio(self) -> None:
        self._apply_ffmpeg_effect("Normalize", "dynaudnorm=f=150:g=15:p=0.95")

    def echo_audio(self) -> None:
        settings = self.effect_parameters("Echo", [
            ("delay", "Delay in milliseconds, 1 through 5000", 250, 1, 5000),
            ("feedback", "Feedback percentage, 0 through 95", 40, 0, 95),
            ("wet", "Wet mix percentage, 0 through 100", 45, 0, 100),
        ])
        if not settings: return
        delay, feedback_percent, wet_percent = settings["delay"], settings["feedback"], settings["wet"]
        decay = min(.95, feedback_percent / 100)
        self._apply_ffmpeg_effect(
            f"Echo, {delay:g} milliseconds, {feedback_percent:g} percent feedback",
            f"aecho=0.8:{max(.01, wet_percent / 100):.4g}:{delay:g}:{decay:.4g}",
        )

    def reverb_audio(self) -> None:
        settings = self.effect_parameters("Room Reverb", [
            ("wet", "Wet mix percentage, 0 through 100", 35, 0, 100),
            ("size", "Room size percentage, 1 through 100", 45, 1, 100),
            ("decay", "Decay percentage, 1 through 99", 45, 1, 99),
        ])
        if settings:
            self._apply_ffmpeg_effect(
                f"Room reverb at {settings['wet']:g} percent",
                self._reverb_filter(settings),
            )

    @staticmethod
    def _reverb_filter(settings: dict[str, float]) -> str:
        size = settings.get("size", 45) / 100
        decay = settings.get("decay", 45) / 100
        wet = settings["wet"] / 100
        delays = [round((35 + size * 85) * factor) for factor in (1, 1.43, 1.91, 2.57)]
        decays = [min(.99, decay * factor) for factor in (1, .82, .66, .5)]
        return f"aecho=0.8:{max(.01, wet):.4g}:{'|'.join(map(str, delays))}:{'|'.join(f'{item:.4g}' for item in decays)}"

    def flanger_audio(self) -> None:
        settings = self.effect_parameters("Flanger", [
            ("rate", "Modulation rate in Hertz, 0.01 through 20", .25, .01, 20),
            ("depth", "Delay depth in milliseconds, 0.1 through 30", 3, .1, 30),
            ("wet", "Wet mix percentage, 0 through 100", 55, 0, 100),
        ])
        if settings:
            rate, depth, wet = settings["rate"], settings["depth"], settings["wet"]
            self._apply_ffmpeg_effect("Flanger", f"flanger=delay={depth:g}:depth={wet / 100 * 10:g}:regen=0:width=71:speed={rate:g}:shape=sinusoidal:phase=25:interp=linear")

    def chorus_audio(self) -> None:
        settings = self.effect_parameters("Chorus", [("wet", "Wet mix percentage, 0 through 100", 45, 0, 100)])
        if settings:
            wet = settings["wet"]
            gain = max(.01, wet / 100)
            self._apply_ffmpeg_effect(f"Chorus at {wet:g} percent", f"chorus=0.7:{gain:.4g}:55|63:0.4|0.32:0.25|0.4:2|2.3")

    def noise_gate_audio(self) -> None:
        settings = self.effect_parameters("Noise Gate", [
            ("threshold", "Threshold in decibels, minus 96 through 0", -40, -96, 0),
            ("attack", "Attack in milliseconds, 0 through 1000", 5, 0, 1000),
            ("release", "Release in milliseconds, 0 through 5000", 80, 0, 5000),
        ])
        if settings:
            threshold, attack, release = settings["threshold"], settings["attack"], settings["release"]
            linear_threshold = 10 ** (threshold / 20)
            self._apply_ffmpeg_effect(f"Noise gate at {threshold:g} dB", f"agate=threshold={linear_threshold:.8g}:ratio=9000:attack={max(.01, attack):g}:release={max(.01, release):g}")

    def noise_reduction_audio(self) -> None:
        settings = self.effect_parameters("Noise Reduction", [("strength", "Reduction strength percentage, 0 through 100", 65, 0, 100)])
        if settings:
            strength = settings["strength"]
            self._apply_ffmpeg_effect(f"Noise reduction at {strength:g} percent", f"afftdn=nr={1 + strength * .35:g}:nf=-50")

    @staticmethod
    def _vinyl_repair_filter(settings: dict[str, float]) -> str:
        sensitivity = settings["sensitivity"]
        threshold = max(1, 10.5 - sensitivity * .095)
        passes = max(1, min(5, round(settings["passes"])))
        stage = f"adeclick=w=55:o=75:a=2:t={threshold:.4g}:b={settings['burst']:g}:m=add"
        return ",".join(stage for _ in range(passes))

    @staticmethod
    def _tape_hiss_filter(settings: dict[str, float]) -> str:
        amplitude = 10 ** (settings["level"] / 20)
        cutoff = 18000 - settings["color"] * 120
        return (
            "asplit=2[original][noise];"
            f"[noise]aeval='(random(0)-0.5)*{amplitude * 2:.8g}',"
            f"lowpass=f={max(2500, cutoff):g}[hiss];"
            "[original][hiss]amix=inputs=2:normalize=0"
        )

    @staticmethod
    def _vinyl_crackle_filter(settings: dict[str, float]) -> str:
        amplitude = 10 ** (settings["level"] / 20)
        probability = .99998 - settings["density"] * .0000017
        return f"aeval='val(ch)+if(gt(random(1),{probability:.8g}),(random(2)-0.5)*{amplitude * 2:.8g},0)'"

    def vinyl_crackle_reduction(self) -> None:
        settings = self.effect_parameters("Vinyl Click and Crackle Removal", [
            ("sensitivity", "Detection sensitivity percentage, 1 through 100", 40, 1, 100),
            ("passes", "SuperScan passes, 1 through 5", 2, 1, 5),
            ("burst", "Maximum click burst width, 0 through 10", 2, 0, 10),
        ])
        if settings:
            self._apply_ffmpeg_effect("Vinyl click and crackle removal", self._vinyl_repair_filter(settings))

    def tape_hiss_reduction(self) -> None:
        settings = self.effect_parameters("Tape Hiss Reduction", [
            ("reduction", "Noise reduction in decibels, point 01 through 97", 12, .01, 97),
            ("floor", "Estimated hiss floor in dBFS, minus 80 through minus 20", -55, -80, -20),
        ])
        if settings:
            self._apply_ffmpeg_effect("Tape hiss reduction", f"afftdn=nr={settings['reduction']:g}:nf={settings['floor']:g}:nt=white:tn=1")

    def add_tape_hiss(self) -> None:
        settings = self.effect_parameters("Add Tape Hiss", [
            ("level", "Hiss level in dBFS, minus 60 through minus 6", -36, -60, -6),
            ("color", "Hiss darkness percentage, 0 through 100", 55, 0, 100),
        ])
        if settings:
            self._apply_ffmpeg_effect("Tape hiss added", self._tape_hiss_filter(settings))

    def add_vinyl_crackle(self) -> None:
        settings = self.effect_parameters("Add Vinyl Crackle", [
            ("density", "Crackle density percentage, 1 through 100", 20, 1, 100),
            ("level", "Crackle level in dBFS, minus 60 through minus 3", -24, -60, -3),
        ])
        if settings:
            self._apply_ffmpeg_effect("Vinyl crackle added", self._vinyl_crackle_filter(settings))

    def lowpass_audio(self) -> None:
        settings = self.effect_parameters("Low-Pass Filter", [("cutoff", "Cutoff frequency in Hertz, at least 1", 8000, 1, None)])
        if settings:
            cutoff = settings["cutoff"]
            self._apply_ffmpeg_effect(f"Low-pass filter at {cutoff:g} Hz", f"lowpass=f={cutoff:g}")

    def highpass_audio(self) -> None:
        settings = self.effect_parameters("High-Pass Filter", [("cutoff", "Cutoff frequency in Hertz, at least 1", 80, 1, None)])
        if settings:
            cutoff = settings["cutoff"]
            self._apply_ffmpeg_effect(f"High-pass filter at {cutoff:g} Hz", f"highpass=f={cutoff:g}")

    def compressor_audio(self) -> None:
        settings = self.effect_parameters("Compressor", [
            ("threshold", "Threshold in decibels, minus 60 through 0", -18, -60, 0),
            ("ratio", "Compression ratio, 1 through 100; for example 4 means 4 to 1", 4, 1, 100),
            ("attack", "Attack in milliseconds, 0.1 through 1000", 10, .1, 1000),
            ("release", "Release in milliseconds, 1 through 5000", 100, 1, 5000),
        ])
        if settings:
            threshold, ratio = settings["threshold"], settings["ratio"]
            attack, release = settings["attack"], settings["release"]
            linear_threshold = 10 ** (threshold / 20)
            self._apply_ffmpeg_effect(f"Compressor at {threshold:g} dB, {ratio:g} to 1", f"acompressor=threshold={linear_threshold:.8g}:ratio={min(20, ratio):g}:attack={attack:g}:release={release:g}")

    @staticmethod
    def _expander_filter(settings: dict[str, float]) -> str:
        threshold = 10 ** (settings["threshold"] / 20)
        return f"agate=threshold={threshold:.8g}:ratio={settings['ratio']:g}:attack={settings['attack']:g}:release={settings['release']:g}:range=0.06125"

    @staticmethod
    def _limiter_filter(settings: dict[str, float]) -> str:
        ceiling = 10 ** (settings["ceiling"] / 20)
        return f"alimiter=limit={ceiling:.8g}:attack={settings['attack']:g}:release={settings['release']:g}:level=false"

    @staticmethod
    def _graphic_eq_filter(settings: dict[str, float]) -> str:
        bands = ((60, "b60"), (250, "b250"), (1000, "b1000"), (4000, "b4000"), (12000, "b12000"))
        return ",".join(f"equalizer=f={frequency}:width_type=o:width=1:g={settings[key]:g}" for frequency, key in bands)

    def expander_audio(self) -> None:
        settings = self.effect_parameters("Expander", [
            ("threshold", "Threshold in decibels, minus 80 through 0", -40, -80, 0),
            ("ratio", "Expansion ratio, 1 through 20", 3, 1, 20),
            ("attack", "Attack in milliseconds, point 01 through 2000", 8, .01, 2000),
            ("release", "Release in milliseconds, point 01 through 9000", 180, .01, 9000),
        ])
        if settings: self._apply_ffmpeg_effect("Expander", self._expander_filter(settings))

    def limiter_audio(self) -> None:
        settings = self.effect_parameters("Limiter", [
            ("ceiling", "Output ceiling in decibels, minus 24 through 0", -1, -24, 0),
            ("attack", "Lookahead attack in milliseconds, point 1 through 80", 5, .1, 80),
            ("release", "Release in milliseconds, 1 through 8000", 80, 1, 8000),
        ])
        if settings: self._apply_ffmpeg_effect("Limiter", self._limiter_filter(settings))

    def bandpass_audio(self) -> None:
        settings = self.effect_parameters("Band-Pass Filter", [
            ("frequency", "Center frequency in Hertz, 1 through 20000", 1500, 1, 20000),
            ("q", "Bandwidth Q, point 1 through 100", 1, .1, 100),
        ])
        if settings: self._apply_ffmpeg_effect("Band-pass filter", f"bandpass=f={settings['frequency']:g}:width_type=q:width={settings['q']:g}")

    def notch_audio(self) -> None:
        settings = self.effect_parameters("Notch Filter", [
            ("frequency", "Notch frequency in Hertz, 1 through 20000", 60, 1, 20000),
            ("q", "Notch Q, point 1 through 100", 12, .1, 100),
        ])
        if settings: self._apply_ffmpeg_effect("Notch filter", f"bandreject=f={settings['frequency']:g}:width_type=q:width={settings['q']:g}")

    def graphic_equalizer_audio(self) -> None:
        settings = self.effect_parameters("Graphic Equalizer", [
            ("b60", "60 Hertz gain in decibels, minus 24 through plus 24", 0, -24, 24),
            ("b250", "250 Hertz gain in decibels, minus 24 through plus 24", 0, -24, 24),
            ("b1000", "1 kilohertz gain in decibels, minus 24 through plus 24", 0, -24, 24),
            ("b4000", "4 kilohertz gain in decibels, minus 24 through plus 24", 0, -24, 24),
            ("b12000", "12 kilohertz gain in decibels, minus 24 through plus 24", 0, -24, 24),
        ])
        if settings: self._apply_ffmpeg_effect("Graphic equalizer", self._graphic_eq_filter(settings))

    def parametric_equalizer_audio(self) -> None:
        settings = self.effect_parameters("Parametric Equalizer", [
            ("frequency", "Center frequency in Hertz, 1 through 20000", 1000, 1, 20000),
            ("gain", "Gain in decibels, minus 24 through plus 24", 0, -24, 24),
            ("q", "Bandwidth Q, point 1 through 100", 1, .1, 100),
        ])
        if settings: self._apply_ffmpeg_effect("Parametric equalizer", f"equalizer=f={settings['frequency']:g}:width_type=q:width={settings['q']:g}:g={settings['gain']:g}")

    def deesser_audio(self) -> None:
        settings = self.effect_parameters("De-Esser", [
            ("intensity", "Detection intensity percentage, 0 through 100", 50, 0, 100),
            ("maximum", "Maximum reduction percentage, 0 through 100", 60, 0, 100),
            ("frequency", "Target frequency position percentage, 0 through 100", 60, 0, 100),
        ])
        if settings: self._apply_ffmpeg_effect("De-esser", f"deesser=i={settings['intensity']/100:g}:m={settings['maximum']/100:g}:f={settings['frequency']/100:g}")

    def bass_treble_audio(self) -> None:
        settings = self.effect_parameters("Bass and Treble", [
            ("bass", "Bass gain in decibels, minus 24 through plus 24", 0, -24, 24),
            ("treble", "Treble gain in decibels, minus 24 through plus 24", 0, -24, 24),
        ])
        if settings:
            bass, treble = settings["bass"], settings["treble"]
            self._apply_ffmpeg_effect("Bass and treble", f"bass=g={bass:g},treble=g={treble:g}")

    def tremolo_audio(self) -> None:
        settings = self.effect_parameters("Tremolo", [
            ("rate", "Rate in Hertz, 0.1 through 100", 5, .1, 100),
            ("depth", "Depth percentage, 0 through 100", 50, 0, 100),
        ])
        if settings:
            rate, depth = settings["rate"], settings["depth"]
            self._apply_ffmpeg_effect("Tremolo", f"tremolo=f={rate:g}:d={depth / 100:g}")

    def distortion_audio(self) -> None:
        settings = self.effect_parameters("Distortion", [("amount", "Drive percentage, 1 through 100", 25, 1, 100)])
        if settings:
            amount = settings["amount"]
            drive = 1 + amount / 8
            self._apply_ffmpeg_effect("Distortion", f"volume={drive:g},alimiter=limit=0.95:level=false")

    def _apply_ffmpeg_effect(self, name: str, audio_filter: str) -> None:
        target = self._effect_range()
        if not target:
            return
        document, start, end = target
        h1, source_path = tempfile.mkstemp(prefix="quickedit-effect-", suffix=".wav")
        h2, target_path = tempfile.mkstemp(prefix="quickedit-effect-result-", suffix=".wav")
        os.close(h1); os.close(h2)
        try:
            self.announce(f"Applying {name}. Please wait.")
            self.update_idletasks()
            self._write_wav(source_path, document.slice_bytes(start, end))
            self.media.transform_wav(source_path, target_path, audio_filter, document.sample_width)
            with wave.open(target_path, "rb") as source:
                changed = source.readframes(source.getnframes())
            self.stop(announce=False); self._checkpoint()
            document.frames = document.slice_bytes(0, start) + changed + document.slice_bytes(end, document.frame_count)
            document.cursor_frame = start
            if document.selection():
                document.selection_start, document.selection_end = start, start + len(changed) // document.frame_size
            self.refresh_details(); self.announce(f"{name} complete.")
        except (OSError, ValueError, wave.Error, MediaError) as exc:
            messagebox.showerror(f"{name} failed", str(exc), parent=self)
        finally:
            for path in (source_path, target_path):
                try:
                    if os.path.isfile(path): os.remove(path)
                except OSError:
                    pass

    def change_speed(self) -> None:
        settings = self.effect_parameters("Change Speed", [("value", "New speed percentage, 10 through 800", 100, 10, 800)])
        if settings:
            value = settings["value"]
            self._apply_ffmpeg_effect(f"Speed changed to {value:g} percent with pitch preserved", self.media.tempo_filter(value / 100))

    def change_pitch(self) -> None:
        settings = self.effect_parameters("Change Pitch", [("value", "Pitch change in semitones, minus 24 through plus 24", 0, -24, 24)])
        if settings and self.document:
            value = settings["value"]
            factor = 2 ** (value / 12)
            filt = f"asetrate={self.document.frame_rate}*{factor:.8g},aresample={self.document.frame_rate},{self.media.tempo_filter(1/factor)}"
            self._apply_ffmpeg_effect(f"Pitch changed by {value:g} semitones with speed preserved", filt)

    def change_tape_speed(self) -> None:
        settings = self.effect_parameters("Tape Pitch and Speed", [("value", "Semitones; negative is lower and slower, minus 24 through plus 24", 0, -24, 24)])
        if settings and self.document:
            value = settings["value"]
            factor = 2 ** (value / 12)
            self._apply_ffmpeg_effect(f"Tape pitch and speed changed by {value:g} semitones", f"asetrate={self.document.frame_rate}*{factor:.8g},aresample={self.document.frame_rate}")

    def set_playback_speed(self) -> None:
        value = simpledialog.askfloat("Playback speed", "Playback speed percentage:", parent=self, initialvalue=self.playback_speed * 100, minvalue=10, maxvalue=800)
        if value is not None:
            self._apply_playback_speed(value / 100)
            self.set_status(f"Playback speed {value:g} percent.")

    def set_playback_pitch(self) -> None:
        value = simpledialog.askfloat("Playback pitch", "Playback pitch in semitones:", parent=self, initialvalue=self.playback_pitch_semitones, minvalue=-24, maxvalue=24)
        if value is not None:
            self.playback_pitch_semitones = value
            self._restart_for_playback_setting()
            self.set_status(f"Playback pitch {value:g} semitones.")

    def adjust_playback_speed(self, amount: float) -> None:
        self._apply_playback_speed(max(0.1, min(8.0, round(self.playback_speed + amount, 2))))
        self.set_status(f"Playback speed {self.playback_speed * 100:g} percent.")

    def adjust_playback_pitch(self, semitones: float) -> None:
        self.playback_pitch_semitones = max(-24.0, min(24.0, self.playback_pitch_semitones + semitones))
        self._restart_for_playback_setting()
        self.set_status(f"Playback pitch {self.playback_pitch_semitones:g} semitones.")

    def set_playback_speed_preset(self, speed: float) -> None:
        self._apply_playback_speed(speed)
        self.set_status(f"Playback speed {speed * 100:g} percent.")

    def _apply_playback_speed(self, speed: float) -> None:
        was_playing = self.playing and self.document is not None
        if was_playing:
            self._sync_transport_cursor()
        self.playback_speed = speed
        if was_playing and self.media.set_playback_speed(self.play_process, speed):
            self.play_origin_frame = self.document.cursor_frame
            self.play_started_at = time.monotonic()
            pitch_factor = 2 ** (self.playback_pitch_semitones / 12)
            self.playback_time_factor = speed * (
                pitch_factor if self.playback_pitch_semitones and not self.playback_pitch_preserves_speed else 1.0
            )
        elif was_playing:
            if self.play_direction < 0:
                self._play_reverse_from_cursor(announce=False)
            else:
                self._play_forward_from_cursor(announce=False)

    def reset_playback_speed_pitch(self) -> None:
        self.playback_speed = 1.0
        self.playback_pitch_semitones = 0.0
        self._restart_for_playback_setting()
        self.set_status("Playback speed and pitch reset.")

    def _restart_for_playback_setting(self) -> None:
        if not self.playing or not self.document:
            return
        direction = self.play_direction
        self._sync_transport_cursor()
        if direction < 0:
            self._play_reverse_from_cursor(announce=False)
        else:
            self._play_forward_from_cursor(announce=False)

    def toggle_playback_pitch_mode(self) -> None:
        self.playback_pitch_preserves_speed = self.playback_pitch_preserve_var.get()
        self._restart_for_playback_setting()
        self.announce("Playback pitch preserves speed." if self.playback_pitch_preserves_speed else "Playback pitch changes speed like tape.")

    def fade_audio(self, fade_in: bool) -> None:
        name = "Fade in" if fade_in else "Fade out"
        self._apply_effect(name, lambda data, doc: audio_effects.fade(data, doc.sample_width, doc.channels, fade_in))

    def reverse_audio(self) -> None:
        self._apply_effect("Reverse", lambda data, doc: audio_effects.reverse_frames(data, doc.frame_size))

    def silence_audio(self) -> None:
        self._apply_effect("Silence", lambda data, doc: audio_effects.silence(data, doc.sample_width))

    def swap_channels(self) -> None:
        self._apply_effect("Channel swap", lambda data, doc: audio_effects.swap_first_two_channels(data, doc.sample_width, doc.channels))

    def undo(self) -> None:
        if not self.document or not self.undo_stack:
            self.announce("Nothing to undo.")
            return
        self.stop()
        self.redo_stack.append(copy.deepcopy(self.document))
        self.document = self.undo_stack.pop()
        self.refresh_details()
        self.announce("Undo complete.")

    def redo(self) -> None:
        if not self.document or not self.redo_stack:
            self.announce("Nothing to redo.")
            return
        self.stop()
        self.undo_stack.append(copy.deepcopy(self.document))
        self.document = self.redo_stack.pop()
        self.refresh_details()
        self.announce("Redo complete.")

    def toggle_play(self) -> None:
        if self.playing:
            self.pause()
        else:
            document = self.require_document()
            if document:
                if self.paused and self.play_direction < 0:
                    self._play_reverse_from_cursor()
                else:
                    self._play_forward_from_cursor()

    def master_play(self) -> None:
        document = self.require_document()
        if not document:
            return
        document.cursor_frame = 0
        self._play_frames(document.frames, 0, 1, "Master play. Playing from the beginning.")
        self.refresh_details()

    def play_reverse(self) -> None:
        document = self.require_document()
        if not document:
            return
        end = document.cursor_frame
        if end <= 0:
            self.set_status("Cursor is at the beginning; there is no earlier audio to play backward.")
            return
        self._play_frames(
            document.slice_bytes(0, end),
            end,
            -1,
            f"Playing backward from {format_time(document.seconds_at(end))}.",
            reverse=True,
        )
        self.refresh_details()

    def play_whole_reverse(self) -> None:
        document = self.require_document()
        if not document:
            return
        document.cursor_frame = document.frame_count
        self._play_frames(
            document.frames,
            document.frame_count,
            -1,
            "Playing entire file backward.",
            reverse=True,
        )
        self.refresh_details()

    def _play_forward_from_cursor(self, announce: bool = True) -> None:
        document = self.document
        if not document:
            return
        if document.cursor_frame >= document.frame_count:
            document.cursor_frame = 0
        start = document.cursor_frame
        self._play_frames(
            document.slice_bytes(start, document.frame_count),
            start,
            1,
            f"Playing forward from {format_time(document.seconds_at(start))}." if announce else None,
        )

    def _play_reverse_from_cursor(self, announce: bool = True) -> None:
        document = self.document
        if not document:
            return
        end = document.cursor_frame
        if end <= 0:
            end = document.frame_count
            document.cursor_frame = end
        self._play_frames(
            document.slice_bytes(0, end),
            end,
            -1,
            f"Resuming reverse playback from {format_time(document.seconds_at(end))}." if announce else None,
            reverse=True,
        )

    def play_selection(self) -> None:
        document = self.require_document()
        if not document:
            return
        selection = document.selection()
        if not selection:
            self.announce("There is no selection to play.")
            return
        start, end = selection
        self._play_frames(
            document.slice_bytes(start, end),
            start,
            1,
            f"Playing selection, {format_time(document.seconds_at(end - start))}.",
        )

    def _choose_device(self, title: str, devices: list[AudioDevice]) -> AudioDevice | None:
        if not devices:
            messagebox.showinfo(title, "No compatible audio devices were found.", parent=self)
            return None
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        dialog.grab_set()
        tk.Label(dialog, text=title, padx=12, pady=8).pack(anchor="w")
        device_status = tk.StringVar(value="")
        choices = tk.Listbox(dialog, width=70, height=min(12, len(devices)), exportselection=False)
        for device in devices:
            choices.insert("end", device.name)
        choices.selection_set(0)
        choices.pack(fill="both", expand=True, padx=12, pady=6)
        result: list[AudioDevice] = []

        def speak_selection(event=None) -> None:
            selection = choices.curselection()
            if not selection:
                return
            index = selection[0]
            message = f"{devices[index].name}, {index + 1} of {len(devices)}."
            device_status.set(message)
            self.screen_reader.speak(message)

        def accept() -> None:
            selection = choices.curselection()
            if selection:
                result.append(devices[selection[0]])
                self.screen_reader.speak(f"Selected {devices[selection[0]].name}.")
            dialog.destroy()

        choices.bind("<<ListboxSelect>>", speak_selection)
        choices.bind("<Double-Button-1>", lambda event: accept())
        choices.bind("<Return>", lambda event: accept())
        tk.Label(dialog, textvariable=device_status, anchor="w", padx=12, pady=4).pack(fill="x")
        device_buttons = tk.Frame(dialog)
        device_buttons.pack(fill="x", padx=12, pady=10)
        self.accessible_button(device_buttons, "Use Selected Audio Device", accept).pack(side="left")
        self.accessible_button(device_buttons, "Cancel Device Selection", dialog.destroy).pack(side="right")
        choices.focus_set()
        dialog.after(150, speak_selection)
        self.wait_window(dialog)
        return result[0] if result else None

    def choose_input_device(self) -> None:
        try:
            device = self._choose_device("Choose recording input", self.media.input_devices())
        except MediaError as exc:
            messagebox.showerror("Input devices", str(exc), parent=self)
            return
        if device:
            self.input_device = device
            self.announce(f"Recording input set to {device.name}.")

    def choose_output_device(self) -> None:
        try:
            device = self._choose_device("Choose playback output", self.media.output_devices())
        except MediaError as exc:
            messagebox.showerror("Output devices", str(exc), parent=self)
            return
        if device:
            self.output_device = device.id
            self.announce(f"Playback output set to {device.name}.")

    @property
    def carla_executable(self) -> str:
        return os.path.join(self.app_dir, "runtime", "carla-host", "Carla.exe")

    def open_carla_host(self) -> None:
        executable = self.carla_executable
        if not os.path.isfile(executable):
            messagebox.showerror("VST host unavailable", "The bundled Carla VST host was not found.", parent=self)
            return
        try:
            subprocess.Popen([executable], cwd=os.path.dirname(executable))
            self.announce("Opened the isolated VST2 and VST3 rack.")
        except OSError as exc:
            messagebox.showerror("Could not open VST host", str(exc), parent=self)

    def locate_vst_plugin(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose a VST2 or VST3 plug-in",
            filetypes=[("VST plug-ins", "*.dll *.vst3"), ("All files", "*.*")],
            parent=self,
        )
        if not path:
            return
        self.open_carla_host()
        self.announce(f"VST host opened. In Carla, add {os.path.basename(path)} from {os.path.dirname(path)}.")

    def virtual_midi_keyboard(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Virtual MIDI and Sample Keyboard")
        dialog.geometry("760x640")
        dialog.transient(self)
        sample_path = [""]
        root_note = [60]
        soundfont_path = [self.soundfont_path or ""]
        soundfont_presets: list[Preset] = []
        instrument_mode = ["synth"]
        temporary_files: list[str] = []
        note_names = ("C", "C sharp", "D", "E flat", "E", "F", "F sharp", "G", "A flat", "A", "B flat", "B")
        notes = list(range(36, 85))
        waveforms = ("sine", "square", "triangle", "sawtooth", "white noise", "pink noise")
        status = tk.StringVar(value="Built-in sine synthesizer. Space previews; Enter inserts the note.")
        tk.Label(dialog, textvariable=status, anchor="w", wraplength=580).pack(fill="x", padx=12, pady=8)
        instrument_row = tk.Frame(dialog)
        instrument_row.pack(fill="x", padx=12, pady=(0, 8))
        waveform_column = tk.Frame(instrument_row)
        waveform_column.pack(side="left", fill="both", padx=(0, 12))
        tk.Label(waveform_column, text="Synth waveform list").pack(anchor="w")
        waveform_list = tk.Listbox(waveform_column, exportselection=False, height=6, width=18, takefocus=True)
        for name in waveforms:
            waveform_list.insert("end", name)
        waveform_list.selection_set(0)
        waveform_list.activate(0)
        waveform_list.pack(fill="both")
        preset_column = tk.Frame(instrument_row)
        preset_column.pack(side="left", fill="both", expand=True)
        tk.Label(preset_column, text="SoundFont preset list").pack(anchor="w")
        preset_list = tk.Listbox(preset_column, exportselection=False, height=6, width=55, takefocus=True)
        preset_list.insert("end", "Choose a SoundFont to load its presets")
        preset_list.selection_set(0)
        preset_list.activate(0)
        preset_list.pack(fill="both", expand=True)
        note_list = tk.Listbox(dialog, exportselection=False, height=20)
        for note in notes:
            note_list.insert("end", f"{note_names[note % 12]} {note // 12 - 1}; MIDI note {note}")
        note_list.selection_set(notes.index(60))
        note_list.activate(notes.index(60))
        note_list.pack(fill="both", expand=True, padx=12)
        buttons = tk.Frame(dialog)
        buttons.pack(fill="x", padx=12, pady=10)

        def selected_note() -> int:
            selected = note_list.curselection()
            return notes[selected[0]] if selected else 60

        def selected_waveform() -> str:
            selected = waveform_list.curselection()
            return waveforms[selected[0]] if selected else "sine"

        def selected_preset_index() -> int:
            selected = preset_list.curselection()
            return selected[0] if selected and selected[0] < len(soundfont_presets) else -1

        def choose_sample() -> None:
            path = filedialog.askopenfilename(title="Choose a sample for the keyboard", parent=dialog)
            if not path: return
            root = simpledialog.askinteger("Sample root note", "MIDI root note; 60 is middle C:", parent=dialog, initialvalue=60, minvalue=0, maxvalue=127)
            if root is None: return
            sample_path[0], root_note[0] = path, root
            instrument_mode[0] = "sample"
            status.set(f"Sample instrument: {os.path.basename(path)}. Root MIDI note {root}.")
            self.screen_reader.speak(status.get())

        def load_soundfont(path: str) -> None:
            try:
                presets = list_presets(path)
            except (OSError, ValueError) as exc:
                messagebox.showerror("Could not read SoundFont", str(exc), parent=dialog)
                return
            if not presets:
                messagebox.showerror("Empty SoundFont", "That SoundFont contains no presets.", parent=dialog)
                return
            soundfont_path[0] = path
            soundfont_presets[:] = presets
            labels = [f"Bank {item.bank}, program {item.program}: {item.name}" for item in presets]
            preset_list.delete(0, "end")
            for label in labels:
                preset_list.insert("end", label)
            preset_list.selection_set(0)
            preset_list.activate(0)
            preset_list.see(0)
            instrument_mode[0] = "soundfont"
            self.soundfont_path = path
            status.set(f"SoundFont {os.path.basename(path)}; {len(presets)} presets available.")
            self.screen_reader.speak(status.get())

        def choose_keyboard_soundfont() -> None:
            path = filedialog.askopenfilename(
                title="Choose keyboard SoundFont",
                filetypes=[("SoundFont banks", "*.sf2 *.sf3"), ("All files", "*.*")],
                parent=dialog,
            )
            if path:
                load_soundfont(path)

        def waveform_changed(event=None) -> None:
            instrument_mode[0] = "synth"
            status.set(f"Built-in {selected_waveform()} synthesizer.")
            self.screen_reader.speak(status.get())

        def preset_changed(event=None) -> None:
            index = selected_preset_index()
            if soundfont_path[0] and index >= 0:
                instrument_mode[0] = "soundfont"
                preset = soundfont_presets[index]
                status.set(f"SoundFont preset {preset.name}; bank {preset.bank}, program {preset.program}.")
                self.screen_reader.speak(status.get())

        def render_note(note: int) -> str:
            document = self.document
            rate, width, channels = (document.frame_rate, document.sample_width, document.channels) if document else (44100, 2, 1)
            handle, path = tempfile.mkstemp(prefix="quickedit-key-", suffix=".wav"); os.close(handle)
            temporary_files.append(path)
            if instrument_mode[0] == "sample" and sample_path[0]:
                handle, decoded = tempfile.mkstemp(prefix="quickedit-sample-", suffix=".wav"); os.close(handle)
                temporary_files.append(decoded)
                self.media.decode_to_format(sample_path[0], decoded, rate, channels, width)
                factor = 2 ** ((note - root_note[0]) / 12)
                self.media.transform_wav(decoded, path, f"asetrate={rate}*{factor:.10g},aresample={rate}", width)
            elif instrument_mode[0] == "soundfont" and soundfont_path[0] and selected_preset_index() >= 0:
                preset = soundfont_presets[selected_preset_index()]
                handle, midi_path = tempfile.mkstemp(prefix="quickedit-key-", suffix=".mid"); os.close(handle)
                temporary_files.append(midi_path)
                with open(midi_path, "wb") as midi_file:
                    midi_file.write(one_note_midi(note, preset))
                rendered = path + ".rendered.wav"
                temporary_files.append(rendered)
                self.media.render_midi(midi_path, soundfont_path[0], rendered, rate)
                self.media.decode_to_format(rendered, path, rate, channels, width)
            else:
                frames = signal_generator.generate_waveform(selected_waveform(), 440 * 2 ** ((note - 69) / 12), .6, rate, width, channels, -12)
                with wave.open(path, "wb") as target:
                    target.setnchannels(channels); target.setsampwidth(width); target.setframerate(rate); target.writeframes(frames)
            return path

        def preview(event=None) -> str:
            try:
                path = render_note(selected_note())
                if self.preview_process and self.preview_process.poll() is None: self.preview_process.terminate()
                self.preview_process = self.media.start_playback(path, self.output_device)
            except (OSError, wave.Error, MediaError, ValueError) as exc:
                messagebox.showerror("Keyboard note failed", str(exc), parent=dialog)
            return "break"

        def insert(event=None) -> str:
            try:
                path = render_note(selected_note())
                with wave.open(path, "rb") as source:
                    frames = source.readframes(source.getnframes())
                    self._insert_generated_audio(frames, f"MIDI note {selected_note()}", source.getframerate(), source.getsampwidth(), source.getnchannels())
            except (OSError, wave.Error, MediaError, ValueError) as exc:
                messagebox.showerror("Could not insert keyboard note", str(exc), parent=dialog)
            return "break"

        def play_key(event) -> str | None:
            mapping = {key: offset for offset, key in enumerate("awsedftgyhuj")}
            if event.char.lower() in mapping:
                index = notes.index(60 + mapping[event.char.lower()])
                note_list.selection_clear(0, "end"); note_list.selection_set(index); note_list.activate(index); note_list.see(index)
                return preview()
            return None

        def close() -> None:
            if self.preview_process and self.preview_process.poll() is None: self.preview_process.terminate()
            self.preview_process = None
            for path in temporary_files:
                try: os.remove(path)
                except OSError: pass
            dialog.destroy()

        note_list.bind("<space>", preview); note_list.bind("<Return>", insert); note_list.bind("<KeyPress>", play_key, add="+")
        waveform_list.bind("<FocusIn>", lambda event: self.screen_reader.speak(f"Synth waveform list. {selected_waveform()} selected."))
        waveform_list.bind("<<ListboxSelect>>", waveform_changed)
        preset_list.bind("<FocusIn>", lambda event: self.screen_reader.speak("SoundFont preset list. Choose SoundFont if no presets are loaded."))
        preset_list.bind("<<ListboxSelect>>", preset_changed)
        self.accessible_button(buttons, "Choose Sample Instrument", choose_sample).pack(side="left")
        self.accessible_button(buttons, "Choose SoundFont", choose_keyboard_soundfont).pack(side="left", padx=8)
        self.accessible_button(buttons, "Preview Note", preview).pack(side="left", padx=8)
        self.accessible_button(buttons, "Insert Note", insert).pack(side="left")
        self.accessible_button(buttons, "Close Keyboard", close).pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", close)
        if soundfont_path[0]:
            load_soundfont(soundfont_path[0])
        note_list.focus_set()

    def choose_soundfont(self, rerender: bool = True) -> None:
        path = filedialog.askopenfilename(
            title="Choose SoundFont",
            filetypes=[("SoundFont banks", "*.sf2 *.sf3"), ("All files", "*.*")],
        )
        if not path:
            return
        self.soundfont_path = path
        self.announce(f"SoundFont selected: {os.path.basename(path)}.")
        if rerender and self.document and self.document.midi_path:
            self.rerender_midi()

    def rerender_midi(self) -> None:
        document = self.document
        if not document or not document.midi_path:
            self.announce("The current document did not come from MIDI.")
            return
        if not self.soundfont_path:
            self.choose_soundfont(rerender=False)
        if not self.soundfont_path:
            return
        handle, path = tempfile.mkstemp(prefix="quickedit-midi-", suffix=".wav")
        os.close(handle)
        try:
            self.media.render_midi(document.midi_path, self.soundfont_path, path, document.frame_rate)
            with wave.open(path, "rb") as source:
                new_frames = source.readframes(source.getnframes())
                channels = source.getnchannels()
                sample_width = source.getsampwidth()
                frame_rate = source.getframerate()
        except (MediaError, wave.Error, OSError) as exc:
            messagebox.showerror("Could not render MIDI", str(exc), parent=self)
            return
        finally:
            if os.path.isfile(path):
                os.remove(path)
        self.stop(announce=False)
        self._checkpoint()
        document.channels = channels
        document.sample_width = sample_width
        document.frame_rate = frame_rate
        document.frames = new_frames
        document.cursor_frame = 0
        document.selection_start = None
        document.selection_end = None
        document.soundfont_path = self.soundfont_path
        document.save_path = None
        self.refresh_details()
        self.announce(
            f"MIDI rendered with {os.path.basename(self.soundfont_path)}. Duration {format_time(document.duration)}."
        )

    def toggle_recording(self) -> None:
        if self.record_process:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self) -> None:
        devices = self.media.input_devices()
        if not devices:
            messagebox.showinfo(
                "Recording unavailable",
                "No DirectShow audio input device was found. Connect or enable a microphone, then choose an input device.",
                parent=self,
            )
            return
        if not self.input_device or self.input_device not in devices:
            self.input_device = self._choose_device("Choose recording input", devices)
        if not self.input_device:
            return
        self.stop(announce=False)
        document = self.document
        self.record_append = document is not None and document.frame_count > 0
        rate = document.frame_rate if document else 44100
        channels = document.channels if document else 2
        sample_width = document.sample_width if document else 2
        handle, self.record_path = tempfile.mkstemp(prefix="quickedit-recording-", suffix=".wav")
        os.close(handle)
        try:
            self.record_process = self.media.start_recording(
                self.input_device, self.record_path, rate, channels, sample_width
            )
        except MediaError as exc:
            self.record_process = None
            messagebox.showerror("Could not record", str(exc), parent=self)
            return
        mode = "Recording to append. Press F9 to stop." if self.record_append else "Recording new audio. Press F9 to stop."
        self.announce(mode)

    def stop_recording(self) -> None:
        process = self.record_process
        path = self.record_path
        if not process or not path:
            return
        if process.stdin:
            try:
                process.stdin.write("q\n")
                process.stdin.flush()
            except OSError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=2)
        self.record_process = None
        self.record_path = None
        try:
            with wave.open(path, "rb") as source:
                recorded = source.readframes(source.getnframes())
                if self.document is None:
                    self.document = AudioDocument(
                        channels=source.getnchannels(),
                        sample_width=source.getsampwidth(),
                        frame_rate=source.getframerate(),
                        frames=recorded,
                        source_path="Untitled recording.wav",
                    )
                else:
                    self._checkpoint()
                    self.document.frames += recorded
                self.document.cursor_frame = self.document.frame_count
        except (wave.Error, OSError) as exc:
            messagebox.showerror("Could not finish recording", str(exc), parent=self)
            return
        finally:
            if os.path.isfile(path):
                os.remove(path)
        self.title("QuickEdit - Untitled recording")
        self.refresh_details()
        self.announce(f"Recording stopped. Duration {format_time(self.document.duration)}.")

    def _play_frames(
        self,
        frames: bytes,
        origin_frame: int,
        direction: int,
        announcement: str | None,
        reverse: bool = False,
    ) -> None:
        self.stop(announce=False)
        handle, path = tempfile.mkstemp(prefix="quickedit-preview-", suffix=".wav")
        os.close(handle)
        self.temp_play_path = path
        if reverse:
            self._write_reversed_wav(path, frames)
        else:
            self._write_wav(path, frames)
        pitch_factor = 2 ** (self.playback_pitch_semitones / 12)
        try:
            if self.playback_pitch_semitones:
                processed = path + ".pitched.wav"
                audio_filter = f"asetrate={self.document.frame_rate}*{pitch_factor:.8g},aresample={self.document.frame_rate}"
                if self.playback_pitch_preserves_speed:
                    audio_filter += "," + self.media.tempo_filter(1 / pitch_factor)
                self.media.transform_wav(path, processed, audio_filter, self.document.sample_width)
                os.remove(path); os.replace(processed, path)
        except MediaError as exc:
            self.stop(announce=False)
            messagebox.showerror("Playback pitch failed", str(exc), parent=self)
            return
        self.playback_time_factor = self.playback_speed * (pitch_factor if self.playback_pitch_semitones and not self.playback_pitch_preserves_speed else 1.0)
        self.play_process = self.media.start_playback(path, self.output_device, self.playback_speed)
        if self.play_process is None:
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        self.playing = True
        self.paused = False
        self.play_direction = direction
        self.play_origin_frame = origin_frame
        self.play_media_origin_frame = origin_frame
        frame_count = len(frames) // self.document.frame_size if self.document else 0
        self.play_target_frame = origin_frame + direction * frame_count
        self.play_started_at = time.monotonic()
        self._schedule_transport_tick()
        if announcement:
            self.announce(announcement)

    def _write_reversed_wav(self, path: str, frames: bytes) -> None:
        """Write reversed audio in small blocks to avoid whole-file memory spikes."""
        document = self.document
        if not document:
            return
        frame_size = document.frame_size
        frames_per_block = max(1, (4 * 1024 * 1024) // frame_size)
        total_frames = len(frames) // frame_size
        with wave.open(path, "wb") as target:
            target.setnchannels(document.channels)
            target.setsampwidth(document.sample_width)
            target.setframerate(document.frame_rate)
            position = total_frames
            while position > 0:
                block_start = max(0, position - frames_per_block)
                block = frames[block_start * frame_size : position * frame_size]
                reversed_block = bytearray(len(block))
                for byte_offset in range(frame_size):
                    reversed_block[byte_offset::frame_size] = block[byte_offset::frame_size][::-1]
                target.writeframesraw(reversed_block)
                position = block_start

    def _seek_active_playback(self, frame: int) -> bool:
        if not self.document or not self.play_process:
            return False
        if self.play_direction > 0:
            media_frames = frame - self.play_media_origin_frame
        else:
            media_frames = self.play_media_origin_frame - frame
        if media_frames < 0:
            return False
        pitch_factor = 2 ** (self.playback_pitch_semitones / 12)
        duration_factor = pitch_factor if self.playback_pitch_semitones and not self.playback_pitch_preserves_speed else 1.0
        media_seconds = media_frames / self.document.frame_rate / duration_factor
        if not self.media.seek_playback(self.play_process, media_seconds):
            return False
        self.play_origin_frame = frame
        self.play_started_at = time.monotonic()
        self.paused = False
        return True

    def _schedule_transport_tick(self) -> None:
        if self.transport_timer is not None:
            self.after_cancel(self.transport_timer)
        self.transport_timer = self.after(50, self._transport_tick)

    def _transport_tick(self) -> None:
        self.transport_timer = None
        if not self.playing or not self.document:
            return
        finished = self._sync_transport_cursor()
        self.refresh_details()
        if finished:
            endpoint = self.document.cursor_frame
            self.stop(announce=False)
            self.announce(
                f"Playback finished at {format_time(self.document.seconds_at(endpoint))}."
            )
        else:
            self._schedule_transport_tick()

    def _sync_transport_cursor(self) -> bool:
        document = self.document
        if not document:
            return True
        elapsed_frames = round((time.monotonic() - self.play_started_at) * document.frame_rate * self.playback_time_factor)
        position = self.play_origin_frame + self.play_direction * elapsed_frames
        if self.play_direction > 0:
            finished = position >= self.play_target_frame
            document.cursor_frame = min(position, self.play_target_frame)
        else:
            finished = position <= self.play_target_frame
            document.cursor_frame = max(position, self.play_target_frame)
        document.cursor_frame = max(0, min(document.frame_count, document.cursor_frame))
        return finished

    def pause(self) -> None:
        document = self.document
        if not document or not self.playing:
            return
        self._sync_transport_cursor()
        self.stop(announce=False, preserve_pause=True)
        self.refresh_details()
        self.announce(f"Paused at {format_time(document.seconds_at(document.cursor_frame))}.")

    def stop(self, announce: bool = True, preserve_pause: bool = False) -> None:
        winsound.PlaySound(None, 0)
        if self.play_process and self.play_process.poll() is None:
            self.play_process.terminate()
        self.play_process = None
        if self.transport_timer is not None:
            self.after_cancel(self.transport_timer)
            self.transport_timer = None
        was_playing = self.playing
        self.playing = False
        self.paused = preserve_pause
        if self.temp_play_path:
            try:
                os.remove(self.temp_play_path)
            except OSError:
                pass
            self.temp_play_path = None
        if announce and was_playing:
            self.announce("Playback stopped.")

    def destroy(self) -> None:
        self.stop_effect_preview()
        self.stop(announce=False)
        super().destroy()


if __name__ == "__main__":
    app = QuickEdit()
    if "--smoke-test" in sys.argv:
        required_tools = (
            app.media.ffmpeg,
            os.path.join(application_dir(), "ffprobe.exe"),
            app.media.mpv,
            app.media.fluidsynth,
            app.online.ytdlp,
            app.carla_executable,
        )
        if not all(path and os.path.isfile(path) for path in required_tools):
            raise RuntimeError("The portable package is missing one or more bundled audio tools.")
        app.update_idletasks()
        app.destroy()
        # A few bundled native runtimes keep Windows loader threads alive after
        # Tk closes. The smoke-test contract is process completion, not a GUI
        # main loop, so exit explicitly after every required component passes.
        os._exit(0)
    else:
        app.mainloop()
