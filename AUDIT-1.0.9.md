# QuickEdit 1.0.9 bug audit

Three independent reviewers examined accessibility/keyboard behavior,
library/playback, and saving/settings. Confirmed findings were reproduced or
covered by regression tests, fixed, and reviewed again. Additional real encoder
checks verified output properties and preservation of audio samples.

## Confirmed problems fixed

### Saving and settings

- Failed encoding could truncate an existing destination. Exports now use a
  temporary file beside the destination and replace it only after success.
  Direct WAV/raw writes have the same protection.
- Undo after Save As restored the original save path. Undo/Redo now retains the
  current destination while restoring audio content.
- New/Open/Close could silently discard edits. These actions now offer Save,
  Discard, or Cancel. Canceling or failing a save prevents replacement/closing.
  Cursor and selection movement do not count as edits.
- Invalid settings structures could crash startup or prevent valid preferences
  from loading. Fields are validated independently. Settings writes are atomic;
  failures preserve the previous file and report the problem.
- Saved streams without names could crash the browser. Missing labels receive
  safe defaults.
- Several lossless/PCM encoders ignored requested bit depth. Supported depths
  now reach the encoder correctly, including stereo planar formats. Unsupported
  choices are rejected explicitly rather than silently reducing precision.
- Opus could fail with the usual 44,100-Hertz default. Save As offers a supported
  48,000-Hertz default for Opus/WebM and validates manually entered rates.
- Brief Windows sharing locks during replacement receive bounded retries.

### Accessibility and keyboard behavior

- Native dropdown focus was not recognized by the global shortcut dispatcher.
  Delete could delete editor audio while a Save As dropdown was open. Native
  popup and editable dropdown keystrokes are now isolated from editor commands.
- Batch-conversion and online-download dropdowns bypassed the value-announcement
  helper. They now announce highlighted/selected values consistently.
- Canceling nested Save As could leave the underlying library window without
  keyboard focus or its modal grab. Both are restored when that window survives.

### Library and playback

- Repeat Off stopped after every track. Whole-track library playback now advances
  to the next song and stops at the queue boundary; only Repeat All wraps.
  Editor selections cannot accidentally advance the library queue.
- Optional tag-reading failures prevented opening playable audio. Audio opening
  now tolerates tag failures.
- A failed tag read was cached as permanently empty metadata for the session.
  Subsequent browsing now retries failed reads.
- Player launch failures escaped callbacks and left temporary files. Failures
  now reset playback and clean up temporary audio.
- A player that exited unsuccessfully could appear to keep playing silently.
  Failed exits now stop without repeating or advancing; successful completion
  follows the normal end-of-track path.
- Highlighted folders were ignored when folders had already been queued for
  import. Import now combines both groups and deduplicates paths.

## Validation

- **159 automated tests passed** after integration.
- Real Tk keyboard tests open native dropdowns and exercise arrow navigation,
  Delete isolation, Escape/Tab handling, focus announcements, and nested-dialog
  cancellation. These check messages sent to the speech announcer.
- Failed-save tests preserve existing bytes, including an actual FFmpeg encoding
  failure; canceled saves do not write or discard the document.
- A 104-case lossless-depth matrix covered 13 formats at four requested bit
  depths, in mono and stereo. Ninety supported combinations matched the requested
  depth; fourteen unsupported combinations were explicitly rejected.
- Seven lossless/container formats were exported and decoded from nonzero 24-bit
  samples. Their decoded samples matched the source byte for byte.
- Settings corruption, failed replacement, queue boundaries, failed playback,
  metadata retries, and background-load cancellation have regression coverage.
- Release packaging also runs the bundled-runtime smoke check, extracts the
  installer and compares every packaged file, and integrity-checks the portable ZIP.

## Coverage limits

This is a code and local integration audit, not proof that every workflow is
bug-free. Audible behavior with a running NVDA installation, physical input and
output devices, third-party plug-ins, and live online-service failures still
need real-world testing. The dropdown tests exercise real Tk events and verify
speech requests; they do not substitute for listening with the user's NVDA setup.
