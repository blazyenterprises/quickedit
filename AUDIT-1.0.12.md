# QuickEdit 1.0.12 validation

Library settings retain the current file, position in seconds, and ordered
playback queue. Closing during playback synchronizes the cursor before saving.
Library startup reopens that one file, clamps position to its duration, restores
the queue, and stays paused. An explicit command-line file overrides restoration.
Unavailable files are announced without opening them. Editor startup is unchanged.
This remembers file-backed playback, not unsaved audio edits or live streams.

Artist/album navigation and song lists have first-letter cycling. Song matching
uses actual titles, independently of display fields. Native list selection events
announce the selected row. Arrows, Enter, Backspace, and modified keys retain their
existing bindings.

173 tests passed, including actual Tk keyboard events for lowercase/uppercase,
cycling/wrap, arrows, and modified keys; settings round trip with saved position
and nonsequential queue; no autoplay; missing files; invalid preferences; and
close-time cursor synchronization. A final numeric-overflow guard passed the
seven targeted resume/navigation tests.
