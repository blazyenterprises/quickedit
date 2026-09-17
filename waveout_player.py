from __future__ import annotations

import ctypes
import os
import time
import wave
from ctypes import wintypes


WAVE_MAPPER = 0xFFFFFFFF
WAVE_FORMAT_PCM = 1
WHDR_BEGINLOOP = 0x00000004
WHDR_ENDLOOP = 0x00000008


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


class WAVEHDR(ctypes.Structure):
    pass


WAVEHDR._fields_ = [
    ("lpData", ctypes.c_void_p),
    ("dwBufferLength", wintypes.DWORD),
    ("dwBytesRecorded", wintypes.DWORD),
    ("dwUser", ctypes.c_size_t),
    ("dwFlags", wintypes.DWORD),
    ("dwLoops", wintypes.DWORD),
    ("lpNext", ctypes.POINTER(WAVEHDR)),
    ("reserved", ctypes.c_size_t),
]


class WaveOutPlayback:
    """Small polyphonic PCM player using Windows' built-in audio mixer."""

    def __init__(self, path: str, loop: bool = False) -> None:
        if os.name != "nt":
            raise OSError("WaveOut playback is available only on Windows.")
        with wave.open(path, "rb") as source:
            if source.getcomptype() != "NONE":
                raise wave.Error("WaveOut requires an uncompressed PCM WAV file.")
            channels = source.getnchannels()
            width = source.getsampwidth()
            rate = source.getframerate()
            frames = source.readframes(source.getnframes())
        if not frames:
            raise wave.Error("The note contains no audio.")
        self._winmm = ctypes.WinDLL("winmm")
        self._handle = ctypes.c_void_p()
        self._buffer = ctypes.create_string_buffer(frames)
        self._format = WAVEFORMATEX(
            WAVE_FORMAT_PCM, channels, rate, rate * channels * width,
            channels * width, width * 8, 0,
        )
        flags = WHDR_BEGINLOOP | WHDR_ENDLOOP if loop else 0
        self._header = WAVEHDR(
            ctypes.cast(self._buffer, ctypes.c_void_p), len(frames), 0, 0,
            flags, 0xFFFFFFFF if loop else 0, None, 0,
        )
        self._loop = loop
        self._stopped = False
        self._ends_at = float("inf") if loop else time.monotonic() + len(frames) / (rate * channels * width)
        result = self._winmm.waveOutOpen(ctypes.byref(self._handle), WAVE_MAPPER, ctypes.byref(self._format), 0, 0, 0)
        if result:
            raise OSError(f"Windows could not open the audio output device; WaveOut error {result}.")
        result = self._winmm.waveOutPrepareHeader(self._handle, ctypes.byref(self._header), ctypes.sizeof(self._header))
        if result:
            self._winmm.waveOutClose(self._handle)
            raise OSError(f"Windows could not prepare the note; WaveOut error {result}.")
        result = self._winmm.waveOutWrite(self._handle, ctypes.byref(self._header), ctypes.sizeof(self._header))
        if result:
            self.terminate()
            raise OSError(f"Windows could not play the note; WaveOut error {result}.")

    def poll(self):
        if self._stopped:
            return 0
        return None if self._loop or time.monotonic() < self._ends_at else 0

    def terminate(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._winmm.waveOutReset(self._handle)
        self._winmm.waveOutUnprepareHeader(self._handle, ctypes.byref(self._header), ctypes.sizeof(self._header))
        self._winmm.waveOutClose(self._handle)

    def __del__(self) -> None:
        try:
            self.terminate()
        except Exception:
            pass


def play_wave(path: str, loop: bool = False) -> WaveOutPlayback:
    return WaveOutPlayback(path, loop=loop)
