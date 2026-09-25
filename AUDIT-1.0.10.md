# QuickEdit 1.0.10

Album navigation now explicitly requests disc/track ordering, rather than
inheriting title/artist/added order from the general library. The same list
becomes the playback queue. Missing track tags fall back to leading filename
numbers. Explicit Shuffle remains supported. Key repeat is unchanged.

161 tests passed, including album-to-track navigation, title-sorted library
with an album opened, mixed artists, multiple discs, missing track tags,
and forward/backward playback through the resulting queue.

The reported Ray Stevens album's local tags were inspected and are correct.
The previous saved setting was track order, so this does not establish the
exact state of the user's earlier live queue; user verification is still
needed. No audio files or tags were modified.
