from __future__ import annotations

import json
import os
import subprocess


def list_recorders() -> list[dict[str, str]]:
    script = r'''
$master = New-Object -ComObject IMAPI2.MsftDiscMaster2
$result = @()
for ($index = 0; $index -lt $master.Count; $index++) {
  $id = $master.Item($index)
  $recorder = New-Object -ComObject IMAPI2.MsftDiscRecorder2
  $recorder.InitializeDiscRecorder($id)
  $result += [pscustomobject]@{ id = $id; name = (($recorder.VendorId + " " + $recorder.ProductId).Trim()) }
}
$result | ConvertTo-Json -Compress
'''
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Windows could not enumerate optical disc recorders.")
    if not result.stdout.strip():
        return []
    parsed = json.loads(result.stdout)
    return parsed if isinstance(parsed, list) else [parsed]


def burn_command(recorder_id: str, raw_tracks: list[str], close_disc: bool = True) -> list[str]:
    tracks = ",".join("'" + path.replace("'", "''") + "'" for path in raw_tracks)
    escaped_id = recorder_id.replace("'", "''")
    script = f'''
$ErrorActionPreference = 'Stop'
$recorder = New-Object -ComObject IMAPI2.MsftDiscRecorder2
$recorder.InitializeDiscRecorder('{escaped_id}')
$writer = New-Object -ComObject IMAPI2.MsftDiscFormat2TrackAtOnce
$writer.Recorder = $recorder
$writer.ClientName = 'QuickEdit'
$writer.DoNotFinalizeMedia = ${str(not close_disc).lower()}
$writer.PrepareMedia()
try {{
  foreach ($path in @({tracks})) {{
    $stream = New-Object -ComObject ADODB.Stream
    $stream.Type = 1
    $stream.Open()
    $stream.LoadFromFile($path)
    $writer.AddAudioTrack($stream)
    $stream.Close()
  }}
}} finally {{
  $writer.ReleaseMedia()
}}
'''
    return ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
