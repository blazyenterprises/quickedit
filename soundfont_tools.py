from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    name: str
    bank: int
    program: int


def list_presets(path: str) -> list[Preset]:
    """Read preset headers from an SF2/SF3 RIFF file without extra packages."""
    with open(path, "rb") as source:
        data = source.read()
    if data[:4] != b"RIFF" or data[8:12] != b"sfbk":
        raise ValueError("That file is not a valid SF2 or SF3 SoundFont.")
    def find_chunk(start: int, end: int) -> bytes | None:
        position = start
        while position + 8 <= end:
            chunk_id = data[position:position + 4]
            size = struct.unpack_from("<I", data, position + 4)[0]
            payload_start = position + 8
            payload_end = min(payload_start + size, end)
            if chunk_id == b"phdr":
                return data[payload_start:payload_end]
            if chunk_id in {b"LIST", b"RIFF"} and payload_start + 4 <= payload_end:
                found = find_chunk(payload_start + 4, payload_end)
                if found is not None:
                    return found
            position = payload_start + size + (size & 1)
        return None

    payload = find_chunk(12, len(data))
    if payload is None:
        raise ValueError("The SoundFont has no preset directory.")
    if len(payload) < 38 or len(payload) % 38:
        raise ValueError("The SoundFont preset directory is damaged.")
    presets: list[Preset] = []
    for offset in range(0, len(payload) - 38, 38):  # final record is EOP
        raw_name, program, bank = struct.unpack_from("<20sHH", payload, offset)
        name = raw_name.split(b"\0", 1)[0].decode("latin-1", "replace").strip() or "Unnamed preset"
        presets.append(Preset(name, bank, program))
    return presets


def _variable_length(value: int) -> bytes:
    result = [value & 0x7F]
    while value := value >> 7:
        result.append((value & 0x7F) | 0x80)
    return bytes(reversed(result))


def one_note_midi(note: int, preset: Preset, duration_seconds: float = 0.75, velocity: int = 100) -> bytes:
    if not 0 <= note <= 127 or not 0 <= preset.program <= 127:
        raise ValueError("MIDI note and program must be from 0 through 127.")
    channel = 9 if preset.bank == 128 else 0
    status = channel
    ticks = max(1, round(duration_seconds * 960))  # 480 PPQ, 120 BPM
    events = bytearray()
    events.extend(b"\x00\xFF\x51\x03\x07\xA1\x20")
    if channel != 9:
        events.extend(bytes((0, 0xB0 | status, 0, preset.bank & 0x7F)))
        events.extend(bytes((0, 0xB0 | status, 32, (preset.bank >> 7) & 0x7F)))
    events.extend(bytes((0, 0xC0 | status, preset.program)))
    events.extend(bytes((0, 0x90 | status, note, max(1, min(127, velocity)))))
    events.extend(_variable_length(ticks))
    events.extend(bytes((0x80 | status, note, 0, 0, 0xFF, 0x2F, 0)))
    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480)
    return header + b"MTrk" + struct.pack(">I", len(events)) + events
