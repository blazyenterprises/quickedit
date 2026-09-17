# QuickEdit

QuickEdit is a keyboard-first, screen-reader-friendly audio editor and audio
workbench for Windows.

This prototype can open PCM WAV directly and uses ApricotPlayer's bundled
FFmpeg for common compressed audio and media formats. It can move the cursor by
time, mark a selection, play the selection or whole file, delete or crop, undo
and redo, record, and export to several audio formats.
Edits remain in memory until Save As is used, so the source file is never
overwritten accidentally.

Cursor movement, selection boundaries, and transport changes are spoken
directly through NVDA when the controller client supplied with ApricotPlayer is
available. The visible status line remains as a fallback.

## Run

Python 3.10 or newer is required. No third-party packages are needed yet.

```powershell
python quickedit.py
```

For friends who do not have Python, use the portable Windows package. Unzip the
entire folder and run `QuickEdit.exe`; its Python runtime, FFmpeg/FFprobe, mpv, yt-dlp,
FluidSynth, Carla plug-in host, and NVDA controller support are included. The `_internal` folder
must remain beside `QuickEdit.exe`.

The **File > Recent Files** menu remembers the 20 most recently opened local
files. **File > Favorites** can add or remove the current local file and keeps
favorite files available between sessions. Missing files are removed when
selected. Both lists are stored with QuickEdit's settings for the current
Windows user.

## Current keyboard commands

- `Ctrl+N`: Create a new empty 44.1 kHz, 16-bit stereo document
- `Ctrl+O`: Open audio or extract the audio stream from common media files
- `Ctrl+S`: Save to the current destination, or open Save As for a new document
- `Ctrl+Shift+S`: Save As
- `Space`: Play, pause, or resume from the current position
- `F2`: Master play; restart from the beginning even if audio is already playing
- `F3`: Play backward from the current cursor position
- `Shift+F3`: Play the entire file backward from its end
- `F4`: Set playback speed to double speed
- `Shift+F4`: Set playback speed to half speed
- `Shift+Space`: Play the current selection
- `Left` / `Right`: Move by the current zoom amount (initially 0.1 seconds)
- `Home` / `End`: Jump to the beginning or end of the audio; active playback follows
- `Shift+Up`: Zoom in, making Left/Right movement finer
- `Shift+Down`: Zoom out, making Left/Right movement wider
- `Ctrl+Left` / `Ctrl+Right`: Move by 1 second
- `Alt+Left` / `Alt+Right`: Move by 5 seconds
- `[` / `]`: Set selection start / end
- `Ctrl+A`: Select all audio
- `Delete`: Delete selection
- `Ctrl+T`: Crop to selection
- `Ctrl+Z` / `Ctrl+Y`: Undo / redo
- `Ctrl+G`: Go to a time
- `F6`: Announce document, cursor, and selection status
- `F9`: Start recording; press again to stop and append it to the document
- `Ctrl+Up` / `Ctrl+Down`: Raise or lower nondestructive playback speed by 10 percent
- `Alt+Up` / `Alt+Down`: Raise or lower nondestructive playback pitch by one semitone
- `Ctrl+Alt+0`: Reset playback speed and pitch

**Edit > Mix Audio File at Cursor** overlays another audio or media file at the
current cursor and extends the document when the incoming sound runs past its
end. The incoming file is automatically converted to the document's PCM format.
For mixing between open files, bracket a region, choose **Copy Selected Audio
for Mixing**, open the destination file, place its cursor, and choose **Mix
Copied Audio at Cursor**. This separate audio clipboard survives opening the
destination and converts sample rate, channel count, and bit depth when needed.
**Crossfade Selected Halves** treats the first half of the bracketed selection
as outgoing audio and the second half as incoming audio, overlaps them with
equal-power fades, and shortens the selection to the new overlap. Both edits
support Undo and Redo.

The **Effects** menu provides volume adjustment in decibels, normalization to
-1 dB, adjustable echo, room reverb, flanger, chorus, noise gate, smooth noise
reduction, low-pass and high-pass filters, compressor, bass and treble,
tremolo, distortion, fade in, fade out,
permanent reversal, replacement with silence, and left/right channel swapping.
Each effect processes the bracketed selection, or the entire file when there is
no selection, and can be reversed with Undo. Echo asks for its delay and
feedback; the room and modulation effects start with useful musical defaults.

The Record and Devices menu lists available recording inputs and playback
outputs. Playback uses ApricotPlayer's bundled mpv when available, allowing a
specific output device to be selected. Recording uses FFmpeg's Windows capture
support, preferring OpenAL enumeration when DirectShow fails to report devices.
If Windows exposes no compatible recording input, QuickEdit reports that
directly.

Current export choices are WAV, MP3, FLAC, Ogg Vorbis, Opus, M4A/AAC, WMA, and
AIFF, Sun AU/SND, Apple CAF, Creative VOC, Sony Wave64, RF64, raw PCM, AC-3,
E-AC-3, AMR-NB, TTA, WavPack, CRI ADX, SoX native, and IRCAM. FFmpeg can import
substantially more formats than this list, including audio tracks from common
video containers.

Use **File > Output Format Settings** before saving to choose an output sample
rate from 1 kHz through 384 kHz, PCM bit depth of 8, 16, 24, or 32 bits, one to
eight channels, and the bitrate used by compressed formats. These settings only
affect the saved copy; the open editing document is not resampled. Save As also
offers an Other FFmpeg-supported format entry: type an extension and QuickEdit
will ask the bundled FFmpeg build to select its normal encoder and container.

Audio-only MOV/ALAC, MP4/AAC, 3GP, 3G2, MKA/MKV, and WebM/Opus exports are also
available. Ordinary **Open Audio** and Save commands use the native Windows file
dialogs and remember the last folder visited. **Open Audio with Preview** opens
QuickEdit's separate sound browser when auditioning files before opening is more
important than Windows Explorer integration. Its Preview checkbox controls
auditioning. With Preview enabled,
moving through files with Up and Down plays the
highlighted file. Enter opens a file or enters a folder, and Backspace moves to
the parent folder. Typing a letter jumps to the next filename or folder
beginning with that letter, with repeated presses cycling matches. Home and End
jump to the first and last items. Filenames and folder positions are announced
directly.

MIDI files can be opened through the bundled official FluidSynth 2.6 runtime.
QuickEdit asks for an SF2 or SF3 SoundFont, renders the MIDI into an editable
audio document, and remembers both source files. Use **MIDI and SoundFonts >
Choose SoundFont** to switch banks and immediately re-render the original MIDI.
This changes the rendered audio but keeps the MIDI source available for another
SoundFont switch. The accessible **Virtual MIDI and Sample Keyboard** previews
and inserts notes from a built-in synthesizer, every preset in a selected
SF2/SF3 SoundFont, or a user-selected sample. The synthesizer offers sine,
square, triangle, sawtooth, white-noise, and pink-noise voices. SoundFont
presets use their real names, banks, and program numbers, including percussion
banks. **Render MIDI with One Sample** turns a selected audio sample into a
polyphonic instrument for the entire open MIDI file. It preserves tempo,
velocity, chords, and note lengths while intentionally using that one sample
for every audible MIDI channel. **Mute or Unmute MIDI Channels** provides an
accessible checklist for all 16 channels, including an explicit percussion
label for channel 10. Those settings are remembered and apply to both
SoundFont and one-sample rendering. Up and Down choose MIDI notes, Space previews, Enter inserts, and the
letter row can be played as a chromatic keyboard. Raw PCM import asks for its sample rate, channel
count, and bit depth because headerless PCM cannot contain that information
itself.

Library View can order songs by album/disc/track number, title, artist, album,
or newest-added order. Shuffle mode randomizes the active queue, and the chosen
ordering is remembered after QuickEdit closes.
Repeat Off stops at the queue boundary, Repeat All advances through and wraps
the active queue, and Repeat One Track restarts the current file automatically.
The repeat choice is available in every workspace and is remembered.

The **Generate and Censor** menu creates sine, square, triangle, sawtooth,
white-noise, and pink-noise signals. It also generates adjustable DTMF and MF
telephone key strings. Censor Selection can replace a bracketed selection with
a beep, buzz, silence, reversed audio, or remove it. Censoring is deliberately
selection based; QuickEdit does not send speech to an online transcription
service or guess which words the editor intended to censor.

**Text to Speech Generator** can preview, insert, or save speech. Local engines
include installed SAPI 4 and SAPI 5 voices (through the bundled Balabolka command
line engine), eSpeak, and Festival when available. Configurable online engines
include OpenAI, ElevenLabs, Microsoft Azure, Fish Audio, Amazon Polly, and a
user-supplied STAR WebSocket server. Service keys and STAR addresses are
encrypted by Windows for the current account. QuickEdit never supplies or
silently selects a shared STAR server. VDSoft 3000 is currently an NVDA-only
32-bit synthesizer rather than an audio-export engine; it cannot yet be inserted
or saved without a standalone renderer from that public project.

The **VST Plug-ins** menu opens the bundled Carla rack in its own process for
live VST2 and VST3 plug-in use. QuickEdit can also preview a VST3 plug-in on up
to ten seconds of the bracketed selection, then apply it destructively to the
selection or whole file through the bundled offline VST3 engine.

**File > Burn Audio CD** accepts up to 99 audio files in track order, converts
them to standard 44.1 kHz, 16-bit stereo CD audio, checks the disc duration,
and burns and finalizes a CD-R or CD-RW through Windows IMAPI. Multiple optical
recorders can be selected without relying on an inaccessible third-party burner.

## Online audio

The **Online Audio** menu supports direct links, YouTube search, SoundCloud
search, and AudioVault movie/show search. Search results are keyboard navigable
and explicitly announced through NVDA. In YouTube and SoundCloud results, Space
previews the highlighted result, Enter imports it as an editable QuickEdit
document, and Shift+Enter downloads it to a file. **Download Format Settings**
chooses WAV, MP3, FLAC, Ogg Vorbis, Opus, M4A, or WMA along with the desired
sample rate and compressed-audio bitrate. The settings are remembered. A
separate Download button is also available in every results window, and
**Download Direct Link** provides the same choices for a pasted address. The
bundled yt-dlp runtime performs stream discovery and audio import.

YouTube search can be filtered to videos, playlists, or channels. Enter on a
playlist or channel opens its videos as another accessible results list.
Shift+Enter downloads the whole collection into a chosen folder using numbered,
safe filenames and the selected download format, sample rate, and bitrate. A
collection-size prompt accepts zero for everything; channels default to 20 so a
single keystroke does not accidentally download years of uploads.

AudioVault credentials are requested only by its login dialog and remain in
memory for the current QuickEdit session unless **Remember me on this computer**
is checked. Remembered credentials are encrypted by Windows for the current
Windows account rather than stored as readable text. **Log out and Forget
AudioVault Login** clears both the session and saved credential. QuickEdit now
establishes and verifies a fresh AudioVault session before catalog searches as
well as downloads. Enter on an AudioVault result downloads it through that
authenticated session and imports the audio. TV-season packages may
still require a later episode-package workflow rather than opening as a single
audio document.

**Preview Direct URL or Radio Playlist** accepts ordinary media links and PLS,
M3U, or M3U8 radio playlists. QuickEdit resolves playlist files to their first
stream entry. Live radio is previewed rather than imported because it has no
natural endpoint. The bundled yt-dlp and FFmpeg runtimes handle downloadable
YouTube and SoundCloud results when Enter is pressed.

Playback speed and pitch are nondestructive Transport settings. Playback pitch
can preserve duration or behave like tape and change duration with pitch. The
Effects menu separately provides permanent speed change with pitch preserved,
pitch change with speed preserved, and linked tape-style pitch and speed.

These are prototype defaults, not permanent decisions. A later build will make
the full command map editable, following ApricotPlayer's useful model of
assigning shortcuts by action rather than hard-wiring them throughout the UI.

The brackets and adaptive arrow movement are permanent parts of the Blazy
editing model: press `[` at the beginning of the audio you want to affect, `]`
at its end, and use `Shift+Up` or `Shift+Down` to choose how precisely the plain
arrow keys travel. Available steps range from one millisecond to one minute.
When playback is active, moving the cursor also seeks the audible transport to
the new position immediately. When paused, movement chooses where Space resumes.
The cursor follows playback continuously and remains at the actual pause or
completion position for forward, selected, and reverse playback.

Routine cursor, zoom, playback-speed, and playback-pitch adjustments update the
visible status silently so speech does not cover the audio being auditioned.
Press `F6` whenever you want QuickEdit to speak the current cursor, duration,
movement size, and selection. Selection brackets and important file or
recording events remain spoken.

All menus support first-letter navigation. Typing a letter moves to the next
enabled item beginning with that letter, and repeated presses cycle matches.
Home and End move to the first and last enabled menu items. Menu labels also
expose keyboard mnemonics for standard Alt-key navigation.

The **Appearance** menu offers Follow Windows, Light, Dark, Dark Dim, and Dark
High Contrast themes. The choice is remembered between sessions. Follow
Windows updates when the Windows app theme changes. If Windows High Contrast is
active, QuickEdit stands down and uses the system colors regardless of the
chosen theme. Themes restyle the existing controls without replacing them, so
their names, roles, keyboard behavior, and NVDA exposure remain intact. Native
Windows file and message dialogs continue to follow Windows itself.

## Direction

See [DESIGN.md](DESIGN.md) for the product direction and the ApricotPlayer
assessment that informed it.
