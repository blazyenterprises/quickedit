from __future__ import annotations

import math
import random


DTMF = {
    "1": (697, 1209), "2": (697, 1336), "3": (697, 1477), "A": (697, 1633),
    "4": (770, 1209), "5": (770, 1336), "6": (770, 1477), "B": (770, 1633),
    "7": (852, 1209), "8": (852, 1336), "9": (852, 1477), "C": (852, 1633),
    "*": (941, 1209), "0": (941, 1336), "#": (941, 1477), "D": (941, 1633),
}
MF = {
    "1": (700, 900), "2": (700, 1100), "3": (900, 1100), "4": (700, 1300),
    "5": (900, 1300), "6": (1100, 1300), "7": (700, 1500), "8": (900, 1500),
    "9": (1100, 1500), "0": (1300, 1500),
}


def _encode(value: float, width: int) -> bytes:
    bits = width * 8
    low, high = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    value = max(low, min(high, round(value * high)))
    return bytes((value + 128,)) if width == 1 else value.to_bytes(width, "little", signed=True)


def generate_waveform(kind: str, frequency: float, duration: float, rate: int, width: int, channels: int, level_db: float = -12) -> bytes:
    kind = kind.lower()
    if kind not in {"sine", "square", "triangle", "sawtooth", "white noise", "pink noise"}:
        raise ValueError("Waveform must be sine, square, triangle, sawtooth, white noise, or pink noise.")
    if not 0.01 <= duration <= 3600 or not 1 <= frequency <= rate / 2:
        raise ValueError("Frequency or duration is outside the supported range.")
    gain = 10 ** (level_db / 20)
    output = bytearray()
    rng = random.Random()
    pink = 0.0
    for index in range(round(duration * rate)):
        phase = (index * frequency / rate) % 1.0
        if kind == "sine": value = math.sin(2 * math.pi * phase)
        elif kind == "square": value = 1.0 if phase < 0.5 else -1.0
        elif kind == "triangle": value = 1.0 - 4.0 * abs(phase - 0.5)
        elif kind == "sawtooth": value = 2.0 * phase - 1.0
        elif kind == "white noise": value = rng.uniform(-1, 1)
        else:
            pink = 0.98 * pink + 0.02 * rng.uniform(-1, 1)
            value = max(-1, min(1, pink * 5))
        sample = _encode(value * gain, width)
        output.extend(sample * channels)
    return bytes(output)


def generate_phone_keys(kind: str, digits: str, symbols_per_second: float, rate: int, width: int, channels: int, level_db: float = -12) -> bytes:
    table = DTMF if kind.lower() == "dtmf" else MF
    digits = digits.upper().replace(" ", "")
    if not digits or any(digit not in table for digit in digits):
        raise ValueError(f"Invalid {kind.upper()} sequence characters.")
    if not 0.5 <= symbols_per_second <= 50:
        raise ValueError("Dialing rate must be from 0.5 to 50 symbols per second.")
    period = 1 / symbols_per_second
    tone_time = period * 0.7
    gain = (10 ** (level_db / 20)) / 2
    output = bytearray()
    total = len(digits) * period + 0.08
    for index in range(round(total * rate)):
        time = index / rate
        digit_index, local = int(time / period), time % period
        value = 0.0
        if digit_index < len(digits) and local < tone_time:
            value = sum(math.sin(2 * math.pi * frequency * local) for frequency in table[digits[digit_index]]) * gain
        sample = _encode(value, width)
        output.extend(sample * channels)
    return bytes(output)
