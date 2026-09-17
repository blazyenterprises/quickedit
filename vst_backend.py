from __future__ import annotations

import os
import sys


def _pedalboard():
    try:
        import pedalboard
    except ImportError:
        dependency_dir = os.path.join(os.path.dirname(__file__), ".builddeps")
        if dependency_dir not in sys.path:
            sys.path.insert(0, dependency_dir)
        import pedalboard
    return pedalboard


def plugin_name(path: str) -> str:
    plugin = _pedalboard().load_plugin(path)
    return str(plugin.name or os.path.basename(path))


def render_plugin(plugin_path: str, source_wav: str, target_wav: str) -> None:
    board = _pedalboard()
    plugin = board.load_plugin(plugin_path)
    with board.io.AudioFile(source_wav) as source:
        sample_rate = source.samplerate
        audio = source.read(source.frames)
    rendered = plugin(audio, sample_rate, reset=True)
    with board.io.AudioFile(target_wav, "w", sample_rate, rendered.shape[0]) as target:
        target.write(rendered)
