# QuickEdit 1.0.11 validation

Library metadata is stored in AppData/QuickEdit/library.sqlite3. A small catalog
snapshot supplies views without stat calls or audio probes. Unknown songs are
indexed by a single background worker; saved entries survive restarts. Filename
and parent-folder labels make an unindexed library immediately browsable.
Reopening a view picks up newly indexed tags. Refresh Library Information
explicitly rereads tags, and Library Index Status reports progress/errors.

Playback queues retain paths, not loaded audio. Next/Previous validate only the
target and lazily skip missing entries. Automatic advancement no longer checks
all queue files. Shuffle opens only the chosen song. Existing single-song audio
decoding is unchanged; this does not introduce streaming playback.

166 tests passed, including persistent catalog reopening with file access
forbidden, slow indexing with immediate Tk view callbacks, coalesced indexing,
explicit refresh, 10,000-entry queue access counts, missing-target traversal,
and shuffle opening only one song. The subsequent error-status adjustments
passed 21 targeted catalog, UI, and playback tests.

Catalog entries are intentionally not revalidated during browsing. External
tag changes require Refresh Library Information. Unavailable library entries
remain visible until Remove Missing Library Files is used or they are skipped
in playback. Music files and tags are never modified by indexing.
