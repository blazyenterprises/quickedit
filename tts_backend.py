from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from html import escape


class TTSError(RuntimeError):
    pass


def _run(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=0x08000000)
    if result.returncode:
        raise TTSError(result.stderr.strip() or result.stdout.strip() or "The speech engine failed.")
    return result.stdout


def sapi5_voices() -> list[str]:
    script = "$v=New-Object -ComObject SAPI.SpVoice; @($v.GetVoices()) | ForEach-Object { try { $_.GetDescription() } catch {} }"
    return [line.strip() for line in _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script]).splitlines() if line.strip()]


def balcon_path() -> str | None:
    bundled = os.path.join(os.path.dirname(__file__), "runtime", "tts", "balcon.exe")
    return bundled if os.path.isfile(bundled) else shutil.which("balcon")


def windows_voices() -> list[str]:
    executable = balcon_path()
    if not executable: return sapi5_voices()
    section = "Windows speech"
    voices = []
    for line in _run([executable, "-l"]).splitlines():
        stripped = line.strip()
        if stripped.endswith(":") and stripped.upper().startswith("SAPI"):
            section = stripped[:-1]
        elif " :: " in stripped:
            voices.append(f"{section}: {stripped}")
    return voices


def windows_synthesize(text: str, display_voice: str, target: str, rate: int = 0, pitch: int = 0, volume: int = 100) -> None:
    executable = balcon_path()
    if not executable:
        return sapi5_synthesize(text, display_voice, target, rate, volume)
    voice = display_voice.split(": ", 1)[-1].split(" :: ", 1)[0]
    handle, text_path = tempfile.mkstemp(prefix="quickedit-tts-", suffix=".txt"); os.close(handle)
    with open(text_path, "w", encoding="utf-8-sig") as output: output.write(text)
    try: _run([executable, "-f", text_path, "-enc", "unicode", "-n", voice, "-s", str(max(-10, min(10, rate))), "-p", str(max(-10, min(10, pitch))), "-v", str(max(0, min(100, volume))), "-w", target])
    finally:
        try: os.remove(text_path)
        except OSError: pass


def sapi5_synthesize(text: str, voice: str, target: str, rate: int = 0, volume: int = 100) -> None:
    handle, text_path = tempfile.mkstemp(prefix="quickedit-tts-", suffix=".txt"); os.close(handle)
    with open(text_path, "w", encoding="utf-8") as output: output.write(text)
    q = lambda value: value.replace("'", "''")
    script = f"""
$speaker=New-Object -ComObject SAPI.SpVoice
$match=@($speaker.GetVoices()) | Where-Object {{ try {{ $_.GetDescription() -eq '{q(voice)}' }} catch {{ $false }} }} | Select-Object -First 1
if ($null -eq $match) {{ throw 'The selected SAPI 5 voice is no longer installed.' }}
$speaker.Voice=$match; $speaker.Rate={max(-10, min(10, rate))}; $speaker.Volume={max(0, min(100, volume))}
$stream=New-Object -ComObject SAPI.SpFileStream; $stream.Open('{q(target)}',3,$false)
$speaker.AudioOutputStream=$stream; [void]$speaker.Speak([IO.File]::ReadAllText('{q(text_path)}',[Text.Encoding]::UTF8)); $stream.Close()
"""
    try: _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])
    finally:
        try: os.remove(text_path)
        except OSError: pass


def espeak_path() -> str | None:
    return shutil.which("espeak-ng") or shutil.which("espeak") or next((path for path in (
        r"C:\Program Files\eSpeak NG\espeak-ng.exe", r"C:\Program Files (x86)\eSpeak\command_line\espeak.exe"
    ) if os.path.isfile(path)), None)


def espeak_voices() -> list[str]:
    executable = espeak_path()
    if not executable: return []
    lines = _run([executable, "--voices"]).splitlines()[1:]
    return sorted({parts[3] for line in lines if len(parts := line.split()) >= 4}, key=str.casefold)


def espeak_synthesize(text: str, voice: str, target: str, rate: int = 175, pitch: int = 50, volume: int = 100) -> None:
    executable = espeak_path()
    if not executable: raise TTSError("eSpeak is not installed.")
    _run([executable, "-v", voice, "-s", str(rate), "-p", str(pitch), "-a", str(min(200, volume * 2)), "-w", target, text])


def festival_available() -> bool:
    return bool(shutil.which("text2wave"))


def festival_synthesize(text: str, voice: str, target: str) -> None:
    executable = shutil.which("text2wave")
    if not executable: raise TTSError("Festival text2wave is not installed.")
    command = [executable, "-o", target]
    if voice: command += ["-eval", f"({voice})"]
    result = subprocess.run(command, input=text, text=True, capture_output=True, creationflags=0x08000000)
    if result.returncode: raise TTSError(result.stderr.strip() or "Festival synthesis failed.")


def _post(url: str, payload: bytes, headers: dict[str, str]) -> bytes:
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=120) as response: return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1000]
        raise TTSError(f"Speech service returned HTTP {exc.code}. {detail}") from exc
    except urllib.error.URLError as exc:
        raise TTSError(f"Could not reach the speech service. {exc.reason}") from exc


def web_synthesize(provider: str, text: str, voice: str, target: str, credentials: dict[str, str], rate: float = 1.0) -> None:
    if provider == "OpenAI":
        data = _post("https://api.openai.com/v1/audio/speech", json.dumps({"model": credentials.get("model", "gpt-4o-mini-tts"), "voice": voice or "alloy", "input": text, "response_format": "wav", "speed": rate}).encode(), {"Authorization": f"Bearer {credentials['api_key']}", "Content-Type": "application/json"})
    elif provider == "ElevenLabs":
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{urllib.parse.quote(voice)}?output_format=mp3_44100_128"
        data = _post(url, json.dumps({"text": text, "model_id": credentials.get("model", "eleven_multilingual_v2")}).encode(), {"xi-api-key": credentials["api_key"], "Content-Type": "application/json"})
    elif provider == "Azure":
        region = credentials["region"]
        ssml = f"<speak version='1.0' xml:lang='en-US'><voice name='{escape(voice)}'><prosody rate='{rate:.2f}'>{escape(text)}</prosody></voice></speak>"
        data = _post(f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1", ssml.encode(), {"Ocp-Apim-Subscription-Key": credentials["api_key"], "Content-Type": "application/ssml+xml", "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm"})
    elif provider == "Fish Audio":
        data = _post("https://api.fish.audio/v1/tts", json.dumps({"text": text, "reference_id": voice, "format": "wav", "sample_rate": 44100, "prosody": {"speed": rate, "volume": 0}}).encode(), {"Authorization": f"Bearer {credentials['api_key']}", "Content-Type": "application/json", "model": credentials.get("model", "s2-pro")})
    elif provider == "Amazon Polly":
        import boto3
        client = boto3.client("polly", region_name=credentials["region"], aws_access_key_id=credentials["access_key"], aws_secret_access_key=credentials["secret_key"])
        response = client.synthesize_speech(Text=text, VoiceId=voice, OutputFormat="mp3", Engine=credentials.get("engine", "neural"))
        data = response["AudioStream"].read()
    else: raise TTSError(f"Unknown web speech provider {provider}.")
    with open(target, "wb") as output: output.write(data)


def star_voices(server: str) -> list[str]:
    from websockets.sync.client import connect
    with connect(server, max_size=10 * 1024 * 1024) as websocket:
        websocket.send(json.dumps({"user": 4}))
        while True:
            message = websocket.recv(timeout=30)
            if isinstance(message, str):
                payload = json.loads(message)
                if "voices" in payload:
                    return [item["name"] if isinstance(item, dict) else str(item) for item in payload["voices"]]


def star_synthesize(server: str, voice: str, text: str, target: str, rate: int = 0, pitch: int = 0) -> None:
    from websockets.sync.client import connect
    params = "".join((f" r={rate}" if rate else "", f" p={pitch}" if pitch else "")).strip()
    line = f"{voice}<{params}>: {text}" if params else f"{voice}: {text}"
    with connect(server, max_size=10 * 1024 * 1024) as websocket:
        websocket.send(json.dumps({"user": 4, "request": [line], "id": 1}))
        while True:
            message = websocket.recv(timeout=120)
            if isinstance(message, bytes):
                length = struct.unpack_from("<H", message)[0]
                metadata = message[2:2 + length]
                extension = "wav"
                try: extension = json.loads(metadata)["extension"]
                except (ValueError, KeyError, TypeError): pass
                actual = os.path.splitext(target)[0] + "." + extension
                with open(actual, "wb") as output: output.write(message[2 + length:])
                if actual != target: os.replace(actual, target)
                return
            payload = json.loads(message)
            if payload.get("abort"): raise TTSError(payload.get("status", "STAR synthesis failed."))
