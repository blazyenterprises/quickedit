from __future__ import annotations

import json
import os
import re
import subprocess
import glob
import time
import uuid
from dataclasses import dataclass


CREATE_NO_WINDOW = 0x08000000


@dataclass(frozen=True)
class AudioDevice:
    id: str
    name: str
    backend: str = ""


class MediaError(RuntimeError):
    pass


class MediaBackend:
    def __init__(self, app_dir: str) -> None:
        internal = os.path.normpath(
            os.path.join(app_dir, "..", "work", "quickedit", "apricot-player", "ApricotPlayer", "_internal")
        )
        self.ffmpeg = self._first_existing(
            os.path.join(app_dir, "ffmpeg.exe"),
            os.path.join(internal, "ffmpeg", "ffmpeg.exe"),
        )
        self.mpv = self._first_existing(
            os.path.join(app_dir, "mpv.exe"),
            os.path.join(internal, "mpv", "mpv.exe"),
        )
        fluidsynth_matches = glob.glob(
            os.path.join(app_dir, "runtime", "fluidsynth", "*", "bin", "fluidsynth.exe")
        )
        self.fluidsynth = self._first_existing(
            os.path.join(app_dir, "fluidsynth.exe"),
            *fluidsynth_matches,
        )

    @staticmethod
    def _first_existing(*paths: str) -> str | None:
        return next((path for path in paths if os.path.isfile(path)), None)

    @property
    def formats_available(self) -> bool:
        return self.ffmpeg is not None

    def _run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode:
            detail = result.stderr.strip().splitlines()
            raise MediaError(detail[-1] if detail else "The media operation failed.")
        return result

    def decode(self, source: str, wav_target: str) -> None:
        if not self.ffmpeg:
            raise MediaError("FFmpeg was not found. Only PCM WAV files can be opened.")
        self._run([
            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", source,
            "-vn", "-c:a", "pcm_s16le", wav_target,
        ])

    def decode_to_format(self, source: str, wav_target: str, sample_rate: int, channels: int, sample_width: int) -> None:
        if not self.ffmpeg:
            raise MediaError("FFmpeg was not found, so this audio cannot be converted for mixing.")
        codec = {1: "pcm_u8", 2: "pcm_s16le", 3: "pcm_s24le", 4: "pcm_s32le"}.get(sample_width)
        if not codec:
            raise MediaError("That PCM bit depth cannot be mixed yet.")
        self._run([
            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", source,
            "-vn", "-ar", str(sample_rate), "-ac", str(channels), "-c:a", codec, wav_target,
        ])

    @staticmethod
    def tempo_filter(factor: float) -> str:
        parts = []
        while factor > 2:
            parts.append("atempo=2")
            factor /= 2
        while factor < 0.5:
            parts.append("atempo=0.5")
            factor /= 0.5
        parts.append(f"atempo={factor:.8g}")
        return ",".join(parts)

    def transform_wav(self, source: str, target: str, audio_filter: str, sample_width: int = 2) -> None:
        if not self.ffmpeg:
            raise MediaError("FFmpeg was not found, so pitch and speed processing are unavailable.")
        codec = {1: "pcm_u8", 2: "pcm_s16le", 3: "pcm_s24le", 4: "pcm_s32le"}.get(sample_width, "pcm_s16le")
        self._run([self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", source, "-af", audio_filter, "-c:a", codec, target])

    def encode(self, wav_source: str, target: str, sample_rate: int | None = None, channels: int | None = None, bit_depth: int = 16, bitrate_kbps: int = 192) -> None:
        if not self.ffmpeg:
            raise MediaError("FFmpeg was not found. Save as WAV instead.")
        extension = os.path.splitext(target)[1].lower()
        codecs = {
            ".wav": ["-f", "wav", "-c:a", {8: "pcm_u8", 16: "pcm_s16le", 24: "pcm_s24le", 32: "pcm_s32le"}.get(bit_depth, "pcm_s16le")],
            ".mp3": ["-c:a", "libmp3lame", "-b:a", f"{bitrate_kbps}k"],
            ".flac": ["-c:a", "flac"],
            ".ogg": ["-c:a", "libvorbis", "-b:a", f"{bitrate_kbps}k"],
            ".oga": ["-c:a", "libvorbis", "-b:a", f"{bitrate_kbps}k"],
            ".opus": ["-c:a", "libopus", "-b:a", f"{bitrate_kbps}k"],
            ".m4a": ["-c:a", "aac", "-b:a", f"{bitrate_kbps}k"],
            ".aac": ["-c:a", "aac", "-b:a", f"{bitrate_kbps}k"],
            ".wma": ["-c:a", "wmav2", "-b:a", f"{bitrate_kbps}k"],
            ".mp2": ["-c:a", "mp2", "-b:a", f"{bitrate_kbps}k"],
            ".raw": ["-f", {8: "u8", 16: "s16le", 24: "s24le", 32: "s32le"}.get(bit_depth, "s16le")],
            ".pcm": ["-f", {8: "u8", 16: "s16le", 24: "s24le", 32: "s32le"}.get(bit_depth, "s16le")],
            ".aiff": ["-c:a", {8: "pcm_s8", 16: "pcm_s16be", 24: "pcm_s24be", 32: "pcm_s32be"}.get(bit_depth, "pcm_s16be")],
            ".aif": ["-c:a", {8: "pcm_s8", 16: "pcm_s16be", 24: "pcm_s24be", 32: "pcm_s32be"}.get(bit_depth, "pcm_s16be")],
            ".au": ["-f", "au", "-c:a", {8: "pcm_s8", 16: "pcm_s16be", 24: "pcm_s24be", 32: "pcm_s32be"}.get(bit_depth, "pcm_s16be")],
            ".snd": ["-f", "au", "-c:a", "pcm_s16be"],
            ".caf": ["-f", "caf", "-c:a", "pcm_s16le"],
            ".voc": ["-f", "voc", "-c:a", "pcm_u8"],
            ".w64": ["-f", "w64", "-c:a", "pcm_s16le"],
            ".rf64": ["-f", "wav", "-rf64", "always", "-c:a", "pcm_s16le"],
            ".ac3": ["-f", "ac3", "-c:a", "ac3", "-b:a", f"{bitrate_kbps}k"],
            ".eac3": ["-f", "eac3", "-c:a", "eac3", "-b:a", f"{bitrate_kbps}k"],
            ".amr": ["-f", "amr", "-c:a", "libopencore_amrnb", "-ar", "8000", "-ac", "1", "-b:a", "12.2k"],
            ".tta": ["-f", "tta", "-c:a", "tta"],
            ".wv": ["-f", "wv", "-c:a", "wavpack"],
            ".adx": ["-f", "adx", "-c:a", "adpcm_adx"],
            ".sox": ["-f", "sox", "-c:a", "pcm_s32le"],
            ".ircam": ["-f", "ircam", "-c:a", "pcm_s16le"],
            ".mov": ["-f", "mov", "-c:a", "alac"],
            ".mp4": ["-f", "mp4", "-c:a", "aac", "-b:a", f"{bitrate_kbps}k"],
            ".3gp": ["-f", "3gp", "-c:a", "aac", "-b:a", f"{bitrate_kbps}k"],
            ".3g2": ["-f", "3g2", "-c:a", "aac", "-b:a", f"{bitrate_kbps}k"],
            ".mka": ["-f", "matroska", "-c:a", "flac"],
            ".mkv": ["-f", "matroska", "-c:a", "flac"],
            ".webm": ["-f", "webm", "-c:a", "libopus", "-b:a", f"{bitrate_kbps}k"],
        }
        options = codecs.get(extension)
        if options is None:
            options = []  # Let FFmpeg infer a suitable muxer and codec from the extension.
        conversion = []
        if sample_rate:
            conversion += ["-ar", str(sample_rate)]
        if channels:
            conversion += ["-ac", str(channels)]
        self._run([self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", wav_source, *conversion, *options, target])

    def render_midi(self, midi_source: str, soundfont: str, wav_target: str, sample_rate: int = 44100) -> None:
        if not self.fluidsynth:
            raise MediaError("The FluidSynth runtime was not found.")
        self._run([
            self.fluidsynth,
            "-n", "-i", "-F", wav_target, "-r", str(sample_rate),
            soundfont, midi_source,
        ])

    def output_devices(self) -> list[AudioDevice]:
        if not self.mpv:
            return [AudioDevice("auto", "Default Windows audio device")]
        result = self._run([self.mpv, "--no-config", "--audio-device=help"])
        devices = []
        for line in (result.stdout + result.stderr).splitlines():
            match = re.match(r"\s*'([^']+)'\s+\((.*)\)\s*$", line)
            if match:
                devices.append(AudioDevice(match.group(1), match.group(2)))
        return devices or [AudioDevice("auto", "Default Windows audio device")]

    def input_devices(self) -> list[AudioDevice]:
        if not self.ffmpeg:
            return []
        result = subprocess.run(
            [self.ffmpeg, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
        openal = subprocess.run(
            [self.ffmpeg, "-hide_banner", "-list_devices", "true", "-f", "openal", "-i", "dummy"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
        devices = []
        for line in openal.stderr.splitlines():
            match = re.match(r".*?\]\s{3}(.+)$", line)
            if match and "OpenAL capture devices" not in line:
                device_id = match.group(1).strip()
                if device_id.startswith("OpenAL Soft on "):
                    name = device_id.removeprefix("OpenAL Soft on ")
                    devices.append(AudioDevice(device_id, name, "openal"))
        if devices:
            return devices

        for line in result.stderr.splitlines():
            match = re.search(r'"([^"]+)"\s+\(audio\)', line)
            if match:
                devices.append(AudioDevice(match.group(1), match.group(1), "dshow"))
        return devices

    def start_recording(
        self,
        device: AudioDevice,
        target: str,
        sample_rate: int,
        channels: int,
        sample_width: int,
    ):
        if not self.ffmpeg:
            raise MediaError("FFmpeg was not found, so recording is unavailable.")
        codec = {1: "pcm_u8", 2: "pcm_s16le", 3: "pcm_s24le", 4: "pcm_s32le"}.get(sample_width, "pcm_s16le")
        input_args = (
            ["-f", "openal", "-i", device.id]
            if device.backend == "openal"
            else ["-f", "dshow", "-i", f"audio={device.id}"]
        )
        return subprocess.Popen(
            [
                self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                *input_args, "-ar", str(sample_rate), "-ac", str(channels), "-c:a", codec, target,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=CREATE_NO_WINDOW,
        )

    def start_playback(self, wav_path: str, output_device: str = "auto", speed: float = 1.0):
        if not self.mpv:
            return None
        ipc_path = rf"\\.\pipe\quickedit-mpv-{uuid.uuid4().hex}"
        process = subprocess.Popen(
            [
                self.mpv, "--no-config", "--no-video", "--really-quiet",
                f"--audio-device={output_device}", f"--speed={speed:.8g}",
                "--audio-pitch-correction=yes", f"--input-ipc-server={ipc_path}", wav_path,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        process.quickedit_ipc_path = ipc_path
        return process

    def seek_playback(self, process, seconds: float) -> bool:
        return self._send_mpv_command(process, ["seek", max(0.0, seconds), "absolute+exact"])

    def set_playback_speed(self, process, speed: float) -> bool:
        return self._send_mpv_command(process, ["set_property", "speed", speed])

    @staticmethod
    def _send_mpv_command(process, command: list) -> bool:
        ipc_path = getattr(process, "quickedit_ipc_path", "")
        if not ipc_path or process.poll() is not None:
            return False
        payload = json.dumps({"command": command}) + "\n"
        for _ in range(20):
            try:
                with open(ipc_path, "w", encoding="utf-8", buffering=1) as pipe:
                    pipe.write(payload)
                return True
            except OSError:
                time.sleep(0.01)
        return False
