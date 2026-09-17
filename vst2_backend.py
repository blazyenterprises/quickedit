from __future__ import annotations

import ctypes
import os

import numpy as np

from vst_backend import _pedalboard


VST_MAGIC = 0x56737450
EFF_OPEN = 0
EFF_CLOSE = 1
EFF_GET_PARAM_LABEL = 6
EFF_GET_PARAM_DISPLAY = 7
EFF_GET_PARAM_NAME = 8
EFF_SET_SAMPLE_RATE = 10
EFF_SET_BLOCK_SIZE = 11
EFF_MAINS_CHANGED = 12
EFF_GET_EFFECT_NAME = 45
AUDIO_MASTER_VERSION = 1
PROCESS_REPLACING = 1 << 4


class AEffect(ctypes.Structure):
    pass


AEffectPointer = ctypes.POINTER(AEffect)
Dispatcher = ctypes.CFUNCTYPE(ctypes.c_ssize_t, AEffectPointer, ctypes.c_int32, ctypes.c_int32, ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_float)
Process = ctypes.CFUNCTYPE(None, AEffectPointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_float)), ctypes.POINTER(ctypes.POINTER(ctypes.c_float)), ctypes.c_int32)
SetParameter = ctypes.CFUNCTYPE(None, AEffectPointer, ctypes.c_int32, ctypes.c_float)
GetParameter = ctypes.CFUNCTYPE(ctypes.c_float, AEffectPointer, ctypes.c_int32)
AudioMaster = ctypes.CFUNCTYPE(ctypes.c_ssize_t, AEffectPointer, ctypes.c_int32, ctypes.c_int32, ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_float)

AEffect._fields_ = [
    ("magic", ctypes.c_int32), ("dispatcher", Dispatcher), ("process", Process),
    ("setParameter", SetParameter), ("getParameter", GetParameter),
    ("numPrograms", ctypes.c_int32), ("numParams", ctypes.c_int32),
    ("numInputs", ctypes.c_int32), ("numOutputs", ctypes.c_int32),
    ("flags", ctypes.c_int32), ("resvd1", ctypes.c_void_p), ("resvd2", ctypes.c_void_p),
    ("initialDelay", ctypes.c_int32), ("realQualities", ctypes.c_int32),
    ("offQualities", ctypes.c_int32), ("ioRatio", ctypes.c_float),
    ("object", ctypes.c_void_p), ("user", ctypes.c_void_p),
    ("uniqueID", ctypes.c_int32), ("version", ctypes.c_int32),
    ("processReplacing", Process), ("processDoubleReplacing", ctypes.c_void_p),
    ("future", ctypes.c_char * 56),
]


class VST2Plugin:
    def __init__(self, path: str, sample_rate: float = 44100, block_size: int = 1024) -> None:
        if os.name != "nt":
            raise OSError("VST2 hosting is currently available only on Windows.")
        self.path = path
        self.sample_rate = sample_rate
        self.block_size = block_size

        @AudioMaster
        def audio_master(_effect, opcode, _index, _value, _pointer, _opt):
            if opcode == AUDIO_MASTER_VERSION:
                return 2400
            if opcode == 16:
                return round(self.sample_rate)
            if opcode == 17:
                return self.block_size
            return 0

        self._audio_master = audio_master
        self._library = ctypes.WinDLL(path)
        entry = getattr(self._library, "VSTPluginMain", None) or getattr(self._library, "main", None)
        if entry is None:
            raise ValueError("That DLL does not export a VST2 entry point.")
        entry.argtypes = [AudioMaster]
        entry.restype = AEffectPointer
        self.effect = entry(self._audio_master)
        if not self.effect or self.effect.contents.magic != VST_MAGIC:
            raise ValueError("That DLL did not return a valid VST2 plug-in.")
        self._dispatch(EFF_OPEN)
        self._dispatch(EFF_SET_SAMPLE_RATE, opt=float(sample_rate))
        self._dispatch(EFF_SET_BLOCK_SIZE, value=block_size)

    def _dispatch(self, opcode: int, index: int = 0, value: int = 0, pointer=None, opt: float = 0.0) -> int:
        return int(self.effect.contents.dispatcher(self.effect, opcode, index, value, pointer, opt))

    def _text(self, opcode: int, index: int = 0) -> str:
        buffer = ctypes.create_string_buffer(256)
        self._dispatch(opcode, index=index, pointer=ctypes.cast(buffer, ctypes.c_void_p))
        return buffer.value.decode(errors="replace").strip()

    @property
    def name(self) -> str:
        return self._text(EFF_GET_EFFECT_NAME) or os.path.splitext(os.path.basename(self.path))[0]

    def parameters(self) -> list[dict[str, object]]:
        result = []
        for index in range(self.effect.contents.numParams):
            result.append({
                "key": str(index),
                "name": self._text(EFF_GET_PARAM_NAME, index) or f"Parameter {index + 1}",
                "raw": float(self.effect.contents.getParameter(self.effect, index)),
                "label": self._text(EFF_GET_PARAM_LABEL, index) or "normalized",
                "display": self._text(EFF_GET_PARAM_DISPLAY, index),
            })
        return result

    def set_parameters(self, values: dict[str, float]) -> None:
        for key, value in values.items():
            index = int(key)
            if 0 <= index < self.effect.contents.numParams:
                self.effect.contents.setParameter(self.effect, index, max(0.0, min(1.0, float(value))))

    def process(self, audio: np.ndarray) -> np.ndarray:
        if not self.effect.contents.flags & PROCESS_REPLACING:
            raise ValueError("This VST2 plug-in does not support replacing-process audio.")
        inputs = max(0, self.effect.contents.numInputs)
        outputs = max(1, self.effect.contents.numOutputs)
        if inputs == 0:
            raise ValueError("This VST2 plug-in is an instrument; audio-effect processing requires an effect plug-in.")
        self._dispatch(EFF_MAINS_CHANGED, value=1)
        rendered = np.zeros((outputs, audio.shape[1]), dtype=np.float32)
        try:
            for start in range(0, audio.shape[1], self.block_size):
                count = min(self.block_size, audio.shape[1] - start)
                input_blocks = []
                for channel in range(inputs):
                    source_channel = min(channel, audio.shape[0] - 1)
                    input_blocks.append(np.ascontiguousarray(audio[source_channel, start:start + count], dtype=np.float32))
                output_blocks = [np.zeros(count, dtype=np.float32) for _ in range(outputs)]
                input_ptrs = (ctypes.POINTER(ctypes.c_float) * inputs)(*(block.ctypes.data_as(ctypes.POINTER(ctypes.c_float)) for block in input_blocks))
                output_ptrs = (ctypes.POINTER(ctypes.c_float) * outputs)(*(block.ctypes.data_as(ctypes.POINTER(ctypes.c_float)) for block in output_blocks))
                self.effect.contents.processReplacing(self.effect, input_ptrs, output_ptrs, count)
                for channel, block in enumerate(output_blocks):
                    rendered[channel, start:start + count] = block
        finally:
            self._dispatch(EFF_MAINS_CHANGED, value=0)
        return rendered

    def close(self) -> None:
        if getattr(self, "effect", None):
            self._dispatch(EFF_CLOSE)
            self.effect = None


def plugin_parameters(path: str) -> tuple[str, list[dict[str, object]]]:
    plugin = VST2Plugin(path)
    try:
        return plugin.name, plugin.parameters()
    finally:
        plugin.close()


def render_plugin(path: str, source_wav: str, target_wav: str, values: dict[str, float] | None = None) -> None:
    board = _pedalboard()
    with board.io.AudioFile(source_wav) as source:
        rate = source.samplerate
        audio = source.read(source.frames)
    plugin = VST2Plugin(path, rate)
    try:
        plugin.set_parameters(values or {})
        rendered = plugin.process(audio)
    finally:
        plugin.close()
    with board.io.AudioFile(target_wav, "w", rate, rendered.shape[0]) as target:
        target.write(rendered)
