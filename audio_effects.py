from __future__ import annotations

import math

def _limits(width: int) -> tuple[int, int]:
    bits = width * 8
    return -(1 << (bits - 1)), (1 << (bits - 1)) - 1


def _decode(sample: bytes, width: int) -> int:
    if width == 1:
        return sample[0] - 128
    return int.from_bytes(sample, "little", signed=True)


def _encode(value: float, width: int) -> bytes:
    low, high = _limits(width)
    number = max(low, min(high, round(value)))
    if width == 1:
        return bytes((number + 128,))
    return number.to_bytes(width, "little", signed=True)


def scale_pcm(data: bytes, width: int, factor: float) -> bytes:
    return b"".join(_encode(_decode(data[i:i + width], width) * factor, width) for i in range(0, len(data), width))


def amplify_db(data: bytes, width: int, decibels: float) -> bytes:
    return scale_pcm(data, width, 10 ** (decibels / 20))


def normalize(data: bytes, width: int, target_db: float = -1.0) -> bytes:
    samples = [_decode(data[i:i + width], width) for i in range(0, len(data), width)]
    peak = max((abs(value) for value in samples), default=0)
    if peak == 0:
        return data
    _, high = _limits(width)
    target = high * 10 ** (target_db / 20)
    return scale_pcm(data, width, target / peak)


def fade(data: bytes, width: int, channels: int, fade_in: bool) -> bytes:
    frame_size = width * channels
    frame_count = len(data) // frame_size
    if frame_count <= 1:
        return data
    result = bytearray()
    for frame in range(frame_count):
        amount = frame / (frame_count - 1)
        factor = amount if fade_in else 1.0 - amount
        offset = frame * frame_size
        result.extend(scale_pcm(data[offset:offset + frame_size], width, factor))
    return bytes(result)


def silence(data: bytes, width: int) -> bytes:
    return bytes((128,)) * len(data) if width == 1 else bytes(len(data))


def reverse_frames(data: bytes, frame_size: int) -> bytes:
    return b"".join(data[i:i + frame_size] for i in range(len(data) - frame_size, -1, -frame_size))


def swap_first_two_channels(data: bytes, width: int, channels: int) -> bytes:
    if channels < 2:
        raise ValueError("Channel swapping requires stereo or multichannel audio.")
    frame_size = width * channels
    result = bytearray()
    for offset in range(0, len(data), frame_size):
        frame = data[offset:offset + frame_size]
        result.extend(frame[width:2 * width])
        result.extend(frame[:width])
        result.extend(frame[2 * width:])
    return bytes(result)


def _samples(data: bytes, width: int) -> list[int]:
    return [_decode(data[i:i + width], width) for i in range(0, len(data), width)]


def _pack(samples: list[float], width: int) -> bytes:
    return b"".join(_encode(value, width) for value in samples)


def echo(data: bytes, width: int, channels: int, frame_rate: int, delay_ms: float = 250, feedback: float = 0.4, wet: float = 0.45) -> bytes:
    delay_frames = max(1, round(frame_rate * delay_ms / 1000))
    delay_samples = delay_frames * channels
    source = _samples(data, width)
    output = [float(value) for value in source]
    for index in range(delay_samples, len(output)):
        output[index] += output[index - delay_samples] * feedback * wet
    return _pack(output, width)


def reverb(data: bytes, width: int, channels: int, frame_rate: int, wet: float = 0.35) -> bytes:
    """A compact Schroeder-style room made from several non-aligned echoes."""
    source = _samples(data, width)
    output = [float(value) for value in source]
    taps = ((0.0297, 0.48), (0.0371, 0.40), (0.0411, 0.34), (0.0437, 0.29), (0.067, 0.18))
    for seconds, gain in taps:
        offset = max(channels, round(frame_rate * seconds) * channels)
        for index in range(offset, len(output)):
            output[index] += source[index - offset] * gain * wet
    return _pack(output, width)


def flanger(data: bytes, width: int, channels: int, frame_rate: int, rate_hz: float = 0.25, depth_ms: float = 3.0, wet: float = 0.55) -> bytes:
    source = _samples(data, width)
    output = [0.0] * len(source)
    for index, dry in enumerate(source):
        frame = index // channels
        channel = index % channels
        sweep = (math.sin(2 * math.pi * rate_hz * frame / frame_rate) + 1) / 2
        delay_frames = max(1, round(frame_rate * depth_ms * sweep / 1000))
        delayed = index - delay_frames * channels
        echo_value = source[delayed] if delayed >= channel else 0
        output[index] = dry * (1 - wet * 0.5) + echo_value * wet * 0.5
    return _pack(output, width)


def chorus(data: bytes, width: int, channels: int, frame_rate: int, wet: float = 0.45) -> bytes:
    source = _samples(data, width)
    output = [0.0] * len(source)
    voices = ((0.31, 14.0, 4.0), (0.47, 19.0, 5.0))
    for index, dry in enumerate(source):
        frame = index // channels
        channel = index % channels
        mixed = 0.0
        for rate, base_ms, depth_ms in voices:
            delay_ms = base_ms + depth_ms * math.sin(2 * math.pi * rate * frame / frame_rate)
            delayed = index - max(1, round(frame_rate * delay_ms / 1000)) * channels
            if delayed >= channel:
                mixed += source[delayed]
        output[index] = dry * (1 - wet) + mixed * wet / len(voices)
    return _pack(output, width)


def noise_gate(data: bytes, width: int, channels: int, frame_rate: int, threshold_db: float = -40.0, attack_ms: float = 5.0, release_ms: float = 80.0) -> bytes:
    source = _samples(data, width)
    _, peak = _limits(width)
    threshold = peak * 10 ** (threshold_db / 20)
    attack = math.exp(-1 / max(1, frame_rate * attack_ms / 1000))
    release = math.exp(-1 / max(1, frame_rate * release_ms / 1000))
    gain = 0.0
    output = [0.0] * len(source)
    for frame in range(len(source) // channels):
        offset = frame * channels
        level = max(abs(source[offset + channel]) for channel in range(channels))
        target = 1.0 if level >= threshold else 0.0
        coefficient = attack if target > gain else release
        gain = target + coefficient * (gain - target)
        for channel in range(channels):
            output[offset + channel] = source[offset + channel] * gain
    return _pack(output, width)


def noise_reduce(data: bytes, width: int, channels: int, frame_rate: int, strength: float = 0.65) -> bytes:
    """Smooth downward expansion for steady low-level background noise."""
    source = _samples(data, width)
    if not source:
        return data
    _, peak = _limits(width)
    window_frames = max(1, round(frame_rate * 0.01))
    levels = []
    for start in range(0, len(source), window_frames * channels):
        block = source[start:start + window_frames * channels]
        levels.append(math.sqrt(sum(value * value for value in block) / max(1, len(block))))
    ordered = sorted(levels)
    floor = ordered[min(len(ordered) - 1, round((len(ordered) - 1) * 0.2))]
    threshold = max(peak * 10 ** (-60 / 20), floor * 1.8)
    output = [0.0] * len(source)
    previous_gain = 1.0
    for block_index, start in enumerate(range(0, len(source), window_frames * channels)):
        level = levels[block_index]
        if level >= threshold or threshold == 0:
            target_gain = 1.0
        else:
            target_gain = max(1.0 - strength, (level / threshold) ** 2)
        gain = previous_gain * 0.65 + target_gain * 0.35
        end = min(len(source), start + window_frames * channels)
        for index in range(start, end):
            output[index] = source[index] * gain
        previous_gain = gain
    return _pack(output, width)


def _one_pole(data: bytes, width: int, channels: int, frame_rate: int, cutoff_hz: float, highpass: bool) -> bytes:
    if cutoff_hz <= 0 or cutoff_hz >= frame_rate / 2:
        raise ValueError(f"Cutoff must be between 1 Hz and {frame_rate / 2:g} Hz.")
    source = _samples(data, width)
    output = [0.0] * len(source)
    dt = 1.0 / frame_rate
    rc = 1.0 / (2 * math.pi * cutoff_hz)
    alpha = rc / (rc + dt) if highpass else dt / (rc + dt)
    previous_input = [0.0] * channels
    previous_output = [0.0] * channels
    for index, value in enumerate(source):
        channel = index % channels
        if highpass:
            filtered = alpha * (previous_output[channel] + value - previous_input[channel])
            previous_input[channel] = value
        else:
            filtered = previous_output[channel] + alpha * (value - previous_output[channel])
        previous_output[channel] = filtered
        output[index] = filtered
    return _pack(output, width)


def lowpass(data: bytes, width: int, channels: int, frame_rate: int, cutoff_hz: float) -> bytes:
    return _one_pole(data, width, channels, frame_rate, cutoff_hz, False)


def highpass(data: bytes, width: int, channels: int, frame_rate: int, cutoff_hz: float) -> bytes:
    return _one_pole(data, width, channels, frame_rate, cutoff_hz, True)


def compressor(data: bytes, width: int, channels: int, frame_rate: int, threshold_db: float = -18.0, ratio: float = 4.0, attack_ms: float = 10.0, release_ms: float = 100.0) -> bytes:
    if ratio < 1:
        raise ValueError("Compression ratio must be at least 1.")
    source = _samples(data, width)
    _, peak = _limits(width)
    threshold = peak * 10 ** (threshold_db / 20)
    attack = math.exp(-1 / max(1, frame_rate * attack_ms / 1000))
    release = math.exp(-1 / max(1, frame_rate * release_ms / 1000))
    gain = 1.0
    output = [0.0] * len(source)
    for frame in range(len(source) // channels):
        offset = frame * channels
        level = max(abs(source[offset + channel]) for channel in range(channels))
        if level > threshold:
            compressed_level = threshold * (level / threshold) ** (1 / ratio)
            target_gain = compressed_level / level
        else:
            target_gain = 1.0
        coefficient = attack if target_gain < gain else release
        gain = target_gain + coefficient * (gain - target_gain)
        for channel in range(channels):
            output[offset + channel] = source[offset + channel] * gain
    return _pack(output, width)


def mix_pcm(base: bytes, overlay: bytes, width: int, base_gain: float = 1.0, overlay_gain: float = 1.0) -> bytes:
    base_samples = _samples(base, width)
    overlay_samples = _samples(overlay, width)
    length = max(len(base_samples), len(overlay_samples))
    output = []
    for index in range(length):
        first = base_samples[index] if index < len(base_samples) else 0
        second = overlay_samples[index] if index < len(overlay_samples) else 0
        output.append(first * base_gain + second * overlay_gain)
    return _pack(output, width)


def crossfade_halves(data: bytes, width: int, channels: int) -> bytes:
    frame_size = width * channels
    frame_count = len(data) // frame_size
    if frame_count < 2:
        raise ValueError("The selection is too short to crossfade.")
    split = frame_count // 2
    first = data[:split * frame_size]
    second = data[split * frame_size:]
    overlap_frames = max(split, frame_count - split)
    first_samples = _samples(first, width)
    second_samples = _samples(second, width)
    output = []
    for frame in range(overlap_frames):
        progress = frame / max(1, overlap_frames - 1)
        out_gain = math.cos(progress * math.pi / 2)
        in_gain = math.sin(progress * math.pi / 2)
        for channel in range(channels):
            index = frame * channels + channel
            outgoing = first_samples[index] if index < len(first_samples) else 0
            incoming = second_samples[index] if index < len(second_samples) else 0
            output.append(outgoing * out_gain + incoming * in_gain)
    return _pack(output, width)
