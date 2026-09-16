# QuickEdit product direction

## What ApricotPlayer contributes

The supplied ApricotPlayer build is a PyInstaller-packaged Python 3.10 program.
It uses wxPython for native Windows controls and mpv for playback. Its packaged
modules include dedicated layers for playback, volume, equalization, UI player
controls, and configurable shortcuts. Its English messages show particularly
good accessibility instincts: actions have human-readable names, shortcut
collisions are reported, time and playback changes are announced, and Tab and
Shift+Tab remain reserved for navigation while capturing a new shortcut.

Those interaction ideas are worth keeping. The compiled application itself is
not a practical editor codebase: source is not included, its Python bytecode is
bound to Python 3.10, and mpv is an excellent player but not an edit engine.
QuickEdit therefore starts as a separate project and treats ApricotPlayer as an
interaction reference.

## Non-negotiable principles

1. Every editing operation has a named command and can be assigned a shortcut.
2. Everything important is usable without a mouse or waveform view.
3. Cursor, selection, transport, meters, and long operations produce concise
   screen-reader announcements.
4. Editing is non-destructive. Source media is never silently overwritten.
5. Time values can be entered and spoken as hours, minutes, seconds, or samples.
6. Escape cancels the current mode or dialog; it does not unpredictably destroy
   work or abort an unrelated operation.
7. Long operations expose progress and support the Maple hands-off, progress,
   needs-help, and hands-on cue system when automation is controlling the UI.

## Build sequence

### Prototype: one-file editing

- PCM WAV open/save
- cursor and selection navigation
- selection playback
- delete, crop, undo, and redo
- native menus, dialogs, and status text

### Useful daily editor

- import through FFmpeg: MP3, FLAC, Ogg, M4A, WMA, and common video containers
- export presets and metadata
- cut, copy, paste, silence, trim, fades, normalize, amplify, reverse
- configurable shortcut editor and searchable action finder
- recording and input monitoring
- crash recovery and project files

### Workbench

- multitrack timeline with keyboard-addressable tracks and clips
- markers, regions, batch processing, chains, and loudness tools
- pitch/time tools with and without pitch preservation
- noise reduction and restoration tools
- plug-in hosting and scriptable commands
- sample and game-audio utilities where they fit naturally

## Shortcut philosophy

QuickEdit will distinguish transport, navigation, selection, and destructive
editing. Plain arrows move the cursor; Shift extends a selection; brackets set
precise boundaries; Space controls transport; destructive commands require an
existing selection and announce exactly what changed. Defaults should feel
fast, but every command will ultimately be remappable with conflict detection.

The primary Blazy selection workflow is intentionally simpler than the usual
mouse-centered editor: navigate to the beginning and press `[`, navigate to the
end and press `]`, then invoke an edit. `Shift+Up` zooms in by reducing how far
Left and Right move; `Shift+Down` zooms out by increasing that distance. The
movement amount is always spoken and is also included in the F6 status report.
