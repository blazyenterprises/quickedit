from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
import os


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
crypt32.CryptProtectData.argtypes = [
    ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(DATA_BLOB),
    ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB),
]
crypt32.CryptProtectData.restype = wintypes.BOOL
crypt32.CryptUnprotectData.argtypes = [
    ctypes.POINTER(DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(DATA_BLOB),
    ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB),
]
crypt32.CryptUnprotectData.restype = wintypes.BOOL
kernel32.LocalFree.argtypes = [ctypes.c_void_p]
kernel32.LocalFree.restype = ctypes.c_void_p


class CredentialStore:
    """Store optional credentials encrypted for the current Windows user."""

    def __init__(self, name: str = "audiovault-credentials") -> None:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        safe_name = "".join(char for char in name if char.isalnum() or char in "-_")
        self.path = os.path.join(base, "QuickEdit", f"{safe_name}.dat")
        self.description = f"QuickEdit {safe_name}"

    @staticmethod
    def _blob(data: bytes) -> tuple[DATA_BLOB, object]:
        buffer = ctypes.create_string_buffer(data)
        blob = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
        return blob, buffer

    def save(self, email: str, password: str) -> None:
        plaintext = json.dumps({"email": email, "password": password}).encode("utf-8")
        source, source_buffer = self._blob(plaintext)
        output = DATA_BLOB()
        if not crypt32.CryptProtectData(
            ctypes.byref(source), self.description, None, None, None, 0,
            ctypes.byref(output),
        ):
            raise OSError("Windows could not protect the saved AudioVault login.")
        try:
            protected = ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(output.pbData)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "wb") as target:
            target.write(base64.b64encode(protected))

    def load(self) -> tuple[str, str] | None:
        try:
            with open(self.path, "rb") as source:
                protected = base64.b64decode(source.read(), validate=True)
        except (OSError, ValueError):
            return None
        source, source_buffer = self._blob(protected)
        output = DATA_BLOB()
        description = wintypes.LPWSTR()
        if not crypt32.CryptUnprotectData(
            ctypes.byref(source), ctypes.byref(description), None, None, None, 0, ctypes.byref(output)
        ):
            return None
        try:
            plaintext = ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(output.pbData)
            if description:
                kernel32.LocalFree(description)
        try:
            payload = json.loads(plaintext.decode("utf-8"))
            return payload["email"], payload["password"]
        except (ValueError, KeyError, TypeError):
            return None

    def clear(self) -> None:
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass

    def save_dict(self, values: dict[str, str]) -> None:
        plaintext = json.dumps(values).encode("utf-8")
        source, source_buffer = self._blob(plaintext); output = DATA_BLOB()
        if not crypt32.CryptProtectData(ctypes.byref(source), self.description, None, None, None, 0, ctypes.byref(output)):
            raise OSError("Windows could not protect the saved credentials.")
        try: protected = ctypes.string_at(output.pbData, output.cbData)
        finally: kernel32.LocalFree(output.pbData)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "wb") as target: target.write(base64.b64encode(protected))

    def load_dict(self) -> dict[str, str]:
        try:
            with open(self.path, "rb") as source: protected = base64.b64decode(source.read(), validate=True)
        except (OSError, ValueError): return {}
        source, source_buffer = self._blob(protected); output = DATA_BLOB(); description = wintypes.LPWSTR()
        if not crypt32.CryptUnprotectData(ctypes.byref(source), ctypes.byref(description), None, None, None, 0, ctypes.byref(output)): return {}
        try: plaintext = ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(output.pbData)
            if description: kernel32.LocalFree(description)
        try:
            values = json.loads(plaintext.decode("utf-8")); return {str(k): str(v) for k, v in values.items()}
        except (ValueError, TypeError): return {}
