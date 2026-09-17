from __future__ import annotations

import array
import bisect
import struct
import wave
from dataclasses import dataclass


@dataclass(frozen=True)
class MidiNote:
    channel: int
    note: int
    velocity: int
    start_tick: int
    end_tick: int


def _variable(data: bytes, position: int) -> tuple[int, int]:
    value = 0
    for _ in range(4):
        byte = data[position]
        position += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, position
    raise ValueError("Invalid MIDI variable-length number.")


def read_midi_notes(path: str) -> tuple[int, list[tuple[int, int]], list[MidiNote]]:
    with open(path, "rb") as source:
        data = source.read()
    if data[:4] != b"MThd" or len(data) < 14:
        raise ValueError("That file is not a standard MIDI file.")
    header_size, _format, track_count, division = struct.unpack_from(">IHHH", data, 4)
    if division & 0x8000:
        raise ValueError("SMPTE-timed MIDI files are not supported yet.")
    position = 8 + header_size
    tempos: list[tuple[int, int]] = [(0, 500_000)]
    notes: list[MidiNote] = []
    for _ in range(track_count):
        if data[position:position + 4] != b"MTrk":
            raise ValueError("The MIDI track directory is damaged.")
        size = struct.unpack_from(">I", data, position + 4)[0]
        position += 8
        track, position = data[position:position + size], position + size
        cursor = tick = 0
        running = None
        active: dict[tuple[int, int], list[tuple[int, int]]] = {}
        while cursor < len(track):
            delta, cursor = _variable(track, cursor)
            tick += delta
            status = track[cursor]
            if status & 0x80:
                cursor += 1
                if status < 0xF0:
                    running = status
            elif running is not None:
                status = running
            else:
                raise ValueError("MIDI running status appeared before a status byte.")
            if status == 0xFF:
                kind = track[cursor]; cursor += 1
                length, cursor = _variable(track, cursor)
                payload = track[cursor:cursor + length]; cursor += length
                if kind == 0x51 and len(payload) == 3:
                    tempos.append((tick, int.from_bytes(payload, "big")))
                continue
            if status in (0xF0, 0xF7):
                length, cursor = _variable(track, cursor)
                cursor += length
                continue
            kind, channel = status & 0xF0, status & 0x0F
            length = 1 if kind in (0xC0, 0xD0) else 2
            payload = track[cursor:cursor + length]; cursor += length
            if kind == 0x90 and payload[1]:
                active.setdefault((channel, payload[0]), []).append((tick, payload[1]))
            elif kind == 0x80 or (kind == 0x90 and not payload[1]):
                pending = active.get((channel, payload[0]), [])
                if pending:
                    start, velocity = pending.pop(0)
                    notes.append(MidiNote(channel, payload[0], velocity, start, max(start + 1, tick)))
        for (_channel, note), pending in active.items():
            notes.extend(MidiNote(_channel, note, velocity, start, max(start + 1, tick)) for start, velocity in pending)
    return division, sorted(set(tempos)), notes


def _tempo_map(division: int, tempos: list[tuple[int, int]]) -> tuple[list[int], list[float], list[int]]:
    collapsed: dict[int, int] = {}
    for tick, tempo in tempos:
        collapsed[tick] = tempo
    ticks = sorted(collapsed)
    seconds = [0.0]
    values = [collapsed[ticks[0]]]
    for index in range(1, len(ticks)):
        seconds.append(seconds[-1] + (ticks[index] - ticks[index - 1]) * values[-1] / division / 1_000_000)
        values.append(collapsed[ticks[index]])
    return ticks, seconds, values


def render_midi_with_sample(
    midi_path: str,
    sample_path: str,
    target_path: str,
    root_note: int = 60,
    sample_rate: int = 44100,
    muted_channels: set[int] | None = None,
) -> None:
    division, tempos, notes = read_midi_notes(midi_path)
    notes = [note for note in notes if note.channel not in (muted_channels or set())]
    if not notes:
        raise ValueError("The MIDI file contains no notes.")
    with wave.open(sample_path, "rb") as source:
        if source.getsampwidth() != 2 or source.getframerate() != sample_rate:
            raise ValueError("The sampler source must be a 16-bit WAV at the project sample rate.")
        channels = source.getnchannels()
        sample = array.array("h", source.readframes(source.getnframes()))
    if channels not in (1, 2) or not sample:
        raise ValueError("The sampler source must be a non-empty mono or stereo WAV.")
    tempo_ticks, tempo_seconds, tempo_values = _tempo_map(division, tempos)

    def seconds_at(tick: int) -> float:
        index = bisect.bisect_right(tempo_ticks, tick) - 1
        return tempo_seconds[index] + (tick - tempo_ticks[index]) * tempo_values[index] / division / 1_000_000

    scheduled = [(note, seconds_at(note.start_tick), seconds_at(note.end_tick)) for note in notes]
    total_frames = max(round(end * sample_rate) for _, _, end in scheduled) + 1
    output = array.array("f", [0.0]) * (total_frames * channels)
    source_frames = len(sample) // channels
    for note, start, end in scheduled:
        start_frame = round(start * sample_rate)
        frame_count = max(1, round((end - start) * sample_rate))
        pitch = 2 ** ((note.note - root_note) / 12)
        gain = note.velocity / 127.0
        for frame in range(frame_count):
            source_frame = int(frame * pitch) % source_frames
            output_frame = start_frame + frame
            for channel in range(channels):
                output[output_frame * channels + channel] += sample[source_frame * channels + channel] * gain
    peak = max((abs(value) for value in output), default=1.0)
    scale = min(1.0, 32700.0 / peak) if peak else 1.0
    encoded = array.array("h", (max(-32768, min(32767, round(value * scale))) for value in output))
    with wave.open(target_path, "wb") as target:
        target.setnchannels(channels)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(encoded.tobytes())


def _encode_variable(value: int) -> bytes:
    encoded = [value & 0x7F]
    while value := value >> 7:
        encoded.append((value & 0x7F) | 0x80)
    return bytes(reversed(encoded))


def filter_midi_channels(source_path: str, target_path: str, muted_channels: set[int]) -> None:
    """Copy a standard MIDI file while removing voice events on muted channels."""
    with open(source_path, "rb") as source:
        data = source.read()
    if data[:4] != b"MThd" or len(data) < 14:
        raise ValueError("That file is not a standard MIDI file.")
    header_size = struct.unpack_from(">I", data, 4)[0]
    track_count = struct.unpack_from(">H", data, 10)[0]
    position = 8 + header_size
    output = bytearray(data[:position])
    for _ in range(track_count):
        if data[position:position + 4] != b"MTrk":
            raise ValueError("The MIDI track directory is damaged.")
        size = struct.unpack_from(">I", data, position + 4)[0]
        position += 8
        track, position = data[position:position + size], position + size
        cursor = pending_delta = 0
        running = None
        rebuilt = bytearray()
        while cursor < len(track):
            delta, cursor = _variable(track, cursor)
            status = track[cursor]
            explicit_status = bool(status & 0x80)
            if explicit_status:
                cursor += 1
                if status < 0xF0:
                    running = status
            elif running is not None:
                status = running
            else:
                raise ValueError("MIDI running status appeared before a status byte.")
            if status == 0xFF:
                kind = track[cursor]; cursor += 1
                length, after_length = _variable(track, cursor)
                payload = track[after_length:after_length + length]
                cursor = after_length + length
                event = bytes((0xFF, kind)) + _encode_variable(length) + payload
                keep = True
            elif status in (0xF0, 0xF7):
                length, after_length = _variable(track, cursor)
                payload = track[after_length:after_length + length]
                cursor = after_length + length
                event = bytes((status,)) + _encode_variable(length) + payload
                keep = True
            else:
                kind = status & 0xF0
                length = 1 if kind in (0xC0, 0xD0) else 2
                payload = track[cursor:cursor + length]; cursor += length
                event = bytes((status,)) + payload
                keep = (status & 0x0F) not in muted_channels
            if keep:
                rebuilt.extend(_encode_variable(pending_delta + delta))
                rebuilt.extend(event)
                pending_delta = 0
            else:
                pending_delta += delta
        output.extend(b"MTrk" + struct.pack(">I", len(rebuilt)) + rebuilt)
    with open(target_path, "wb") as target:
        target.write(output)
