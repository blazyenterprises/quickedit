import json
import os
import tempfile
import unittest
from unittest.mock import patch

from quickedit import AudioDocument, QuickEdit, format_time, matching_path_index, next_prefix_index, parse_time


class TimeTests(unittest.TestCase):
    def test_format_time(self):
        self.assertEqual(format_time(0), "0:00.000")
        self.assertEqual(format_time(65.25), "1:05.250")
        self.assertEqual(format_time(3661.5), "1:01:01.500")

    def test_parse_time(self):
        self.assertEqual(parse_time("12.5"), 12.5)
        self.assertEqual(parse_time("1:02.5"), 62.5)
        self.assertEqual(parse_time("1:01:02"), 3662)

    def test_parse_time_rejects_bad_values(self):
        with self.assertRaises(ValueError):
            parse_time("one minute")
        with self.assertRaises(ValueError):
            parse_time("-1")


class BatchConversionTests(unittest.TestCase):
    def test_batch_output_never_overwrites_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "song.wav")
            with open(source, "wb"):
                pass
            target = QuickEdit._unused_output_path(folder, "song", ".wav", source)
            self.assertNotEqual(os.path.normcase(target), os.path.normcase(source))
            self.assertTrue(target.endswith("song converted 2.wav"))

    def test_batch_output_avoids_existing_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            existing = os.path.join(folder, "song.mp3")
            with open(existing, "wb"):
                pass
            target = QuickEdit._unused_output_path(folder, "song", ".mp3", os.path.join(folder, "source.wav"))
            self.assertTrue(target.endswith("song converted 2.mp3"))


class AccessibleEntryTests(unittest.TestCase):
    def test_left_and_right_announce_character_crossed(self):
        self.assertEqual(QuickEdit._entry_navigation_text("123", 3, "left"), "3")
        self.assertEqual(QuickEdit._entry_navigation_text("123", 0, "right"), "1")

    def test_entry_boundaries_and_space_are_named(self):
        self.assertEqual(QuickEdit._entry_navigation_text("4 0", 1, "right"), "space")
        self.assertEqual(QuickEdit._entry_navigation_text("440", 0, "left"), "beginning")
        self.assertEqual(QuickEdit._entry_navigation_text("440", 3, "right"), "end")

    def test_backspace_and_delete_announce_removed_character(self):
        self.assertEqual(QuickEdit._entry_deletion_text("123", 3, "backspace"), "deleted 3")
        self.assertEqual(QuickEdit._entry_deletion_text("123", 0, "delete"), "deleted 1")
        self.assertEqual(QuickEdit._entry_deletion_text("1 3", 1, "delete"), "deleted space")
        self.assertEqual(QuickEdit._entry_deletion_text("123", 0, "backspace"), "nothing to delete")


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.document = AudioDocument(
            channels=1,
            sample_width=2,
            frame_rate=10,
            frames=bytes(range(40)),
            source_path="test.wav",
        )

    def test_frame_math(self):
        self.assertEqual(self.document.frame_count, 20)
        self.assertEqual(self.document.duration, 2.0)
        self.assertEqual(self.document.frame_at(0.5), 5)

    def test_selection_is_order_independent(self):
        self.document.selection_start = 15
        self.document.selection_end = 5
        self.assertEqual(self.document.selection(), (5, 15))

    def test_slice_uses_whole_frames(self):
        self.assertEqual(self.document.slice_bytes(2, 4), bytes(range(4, 8)))

    def test_reverse_preserves_complete_frames(self):
        self.assertEqual(
            self.document.reversed_bytes(0, 3),
            bytes([4, 5, 2, 3, 0, 1]),
        )


class FileNavigationTests(unittest.TestCase):
    def test_first_letter_wraps_and_cycles(self):
        names = ["Abbey Road", "Grateful Dead", "Genesis", "ZZ Top"]
        self.assertEqual(next_prefix_index(names, 0, "g"), 1)
        self.assertEqual(next_prefix_index(names, 1, "g"), 2)
        self.assertEqual(next_prefix_index(names, 2, "g"), 1)

    def test_first_letter_is_case_insensitive(self):
        self.assertEqual(next_prefix_index(["grateful dead"], -1, "G"), 0)

    def test_missing_prefix_returns_none(self):
        self.assertIsNone(next_prefix_index(["Grateful Dead"], 0, "x"))

    def test_backing_out_restores_the_folder_just_exited(self):
        entries = [(r"C:\Music\Alpha", True), (r"C:\Music\Grateful Dead", True), (r"C:\Music\song.wav", False)]
        self.assertEqual(matching_path_index(entries, r"C:\Music\Grateful Dead"), 1)

    def test_missing_previous_folder_falls_back_to_first_item(self):
        entries = [(r"C:\Music\Alpha", True), (r"C:\Music\song.wav", False)]
        self.assertEqual(matching_path_index(entries, r"C:\Music\Missing"), 0)


class PlaybackSettingTests(unittest.TestCase):
    def editor_stub(self):
        editor = object.__new__(QuickEdit)
        editor.playback_speed = 1.0
        editor.playback_pitch_semitones = 0.0
        editor.playing = False
        editor.playback_preset_one_shot = False
        editor.document = None
        editor._restart_for_playback_setting = lambda: None
        editor.spoken_messages = []
        editor.status_messages = []
        editor.announce = editor.spoken_messages.append
        editor.set_status = editor.status_messages.append
        return editor

    def test_speed_shortcut_step_and_limits(self):
        editor = self.editor_stub()
        editor.adjust_playback_speed(0.1)
        self.assertEqual(editor.playback_speed, 1.1)
        editor.playback_speed = 8.0
        editor.adjust_playback_speed(0.1)
        self.assertEqual(editor.playback_speed, 8.0)

    def test_pitch_shortcut_step_and_reset(self):
        editor = self.editor_stub()
        editor.adjust_playback_pitch(1)
        self.assertEqual(editor.playback_pitch_semitones, 1)
        editor.reset_playback_speed_pitch()
        self.assertEqual((editor.playback_speed, editor.playback_pitch_semitones), (1.0, 0.0))
        self.assertEqual(editor.spoken_messages, [])
        self.assertEqual(editor.status_messages[-1], "Playback speed and pitch reset.")

    def test_double_speed_preset_is_marked_one_shot(self):
        editor = self.editor_stub()
        editor.set_playback_speed_preset(2.0)
        self.assertEqual(editor.playback_speed, 2.0)
        self.assertTrue(editor.playback_preset_one_shot)


class ReversePlaybackTests(unittest.TestCase):
    def editor_stub(self, cursor_frame):
        editor = object.__new__(QuickEdit)
        editor.document = AudioDocument(1, 2, 10, bytes(range(40)), "test.wav", cursor_frame=cursor_frame)
        editor.require_document = lambda: editor.document
        editor.refresh_details = lambda: None
        editor.status_messages = []
        editor.set_status = editor.status_messages.append
        editor.play_calls = []
        editor._play_frames = lambda *arguments, **keywords: editor.play_calls.append((arguments, keywords))
        return editor

    def test_f3_reverses_only_audio_before_cursor(self):
        editor = self.editor_stub(5)
        editor.play_reverse()
        (frames, origin, direction, _), keywords = editor.play_calls[0]
        self.assertEqual(origin, 5)
        self.assertEqual(direction, -1)
        self.assertEqual(frames, editor.document.slice_bytes(0, 5))
        self.assertTrue(keywords["reverse"])

    def test_shift_f3_action_reverses_whole_file(self):
        editor = self.editor_stub(5)
        editor.play_whole_reverse()
        (frames, origin, direction, _), keywords = editor.play_calls[0]
        self.assertEqual(origin, editor.document.frame_count)
        self.assertEqual(direction, -1)
        self.assertEqual(frames, editor.document.frames)
        self.assertTrue(keywords["reverse"])

    def test_chunked_reverse_writer_preserves_frames(self):
        editor = self.editor_stub(5)
        with tempfile.TemporaryDirectory() as folder:
            output_path = os.path.join(folder, "reverse.wav")
            editor._write_reversed_wav(output_path, editor.document.frames)
            import wave
            with wave.open(output_path, "rb") as source:
                rendered = source.readframes(source.getnframes())
        self.assertEqual(rendered, editor.document.reversed_bytes())


class FileHistoryTests(unittest.TestCase):
    def test_recent_and_favorites_are_saved_and_loaded(self):
        with tempfile.TemporaryDirectory() as temp_folder, patch.dict(os.environ, {"APPDATA": temp_folder}):
            editor = object.__new__(QuickEdit)
            editor.recent_files = [os.path.join(temp_folder, "recent.wav")]
            editor.favorite_files = [os.path.join(temp_folder, "favorite.flac")]
            editor.online_download_format = ".opus"
            editor.online_download_sample_rate = 48000
            editor.online_download_bitrate = 128
            editor.last_open_directory = temp_folder
            editor.workspace_mode = "library"
            editor.library_files = [os.path.join(temp_folder, "library.flac")]
            editor.library_playlists = {"Road Trip": [os.path.join(temp_folder, "favorite.flac")]}
            editor.library_sort_mode = "shuffle"
            editor.repeat_mode = "one"
            editor.muted_midi_channels = {1, 9, 15}
            editor.saved_streams = [{"name": "Example Radio", "url": "https://radio.example/stream", "provider": "Direct"}]
            editor.soundfont_path = os.path.join(temp_folder, "remembered.sf2")
            with open(editor.soundfont_path, "wb") as soundfont:
                soundfont.write(b"test")
            editor._save_file_history()

            restored = object.__new__(QuickEdit)
            restored.recent_files = []
            restored.favorite_files = []
            restored._load_file_history()
            self.assertEqual(restored.recent_files, editor.recent_files)
            self.assertEqual(restored.favorite_files, editor.favorite_files)
            self.assertEqual(restored.online_download_format, ".opus")
            self.assertEqual(restored.online_download_sample_rate, 48000)
            self.assertEqual(restored.online_download_bitrate, 128)
            self.assertEqual(restored.last_open_directory, temp_folder)
            self.assertEqual(restored.workspace_mode, "library")
            self.assertEqual(restored.library_files, editor.library_files)
            self.assertEqual(restored.library_playlists, editor.library_playlists)
            self.assertEqual(restored.library_sort_mode, "shuffle")
            self.assertEqual(restored.repeat_mode, "one")
            self.assertEqual(restored.muted_midi_channels, {1, 9, 15})
            self.assertEqual(restored.saved_streams, editor.saved_streams)
            self.assertEqual(restored.soundfont_path, editor.soundfont_path)

            with open(restored._history_path, "r", encoding="utf-8") as source:
                self.assertIn("favorite_files", json.load(source))

    def test_recent_files_are_deduplicated_and_limited(self):
        with tempfile.TemporaryDirectory() as temp_folder, patch.dict(os.environ, {"APPDATA": temp_folder}):
            editor = object.__new__(QuickEdit)
            editor.recent_files = [os.path.join(temp_folder, f"file-{number}.wav") for number in range(25)]
            editor.favorite_files = []
            selected = os.path.join(temp_folder, "file-10.wav")
            editor._remember_recent(selected)
            self.assertEqual(editor.recent_files[0], os.path.abspath(selected))
            self.assertEqual(len(editor.recent_files), 20)
            self.assertEqual(sum(os.path.normcase(item) == os.path.normcase(selected) for item in editor.recent_files), 1)


class EffectPresetTests(unittest.TestCase):
    def test_adjustable_effects_offer_at_least_ten_presets(self):
        for effect, presets in QuickEdit.BUILTIN_EFFECT_PRESETS.items():
            self.assertGreaterEqual(len(presets), 10, effect)

    def test_reverb_includes_extreme_spaces(self):
        presets = QuickEdit.BUILTIN_EFFECT_PRESETS["Room Reverb"]
        self.assertIn("Concert Hall", presets)
        self.assertIn("Cathedral", presets)
        self.assertIn("Bottomless Cathedral", presets)
        filter_text = QuickEdit._reverb_filter(presets["Cathedral"])
        self.assertTrue(filter_text.startswith("aecho="))
        self.assertEqual(filter_text.count("|"), 6)

    def test_restoration_and_aging_filters_are_available(self):
        for effect in (
            "Vinyl Click and Crackle Removal", "Tape Hiss Reduction",
            "Add Tape Hiss", "Add Vinyl Crackle",
        ):
            self.assertIn(effect, QuickEdit.BUILTIN_EFFECT_PRESETS)
        repair = QuickEdit._vinyl_repair_filter({"sensitivity": 60, "passes": 3, "burst": 4})
        self.assertEqual(repair.count("adeclick="), 3)
        hiss = QuickEdit._tape_hiss_filter({"level": -36, "color": 55})
        self.assertIn("asplit=2", hiss)
        self.assertIn("amix=inputs=2", hiss)
        crackle = QuickEdit._vinyl_crackle_filter({"density": 50, "level": -20})
        self.assertIn("random", crackle)

    def test_advanced_filter_recipes(self):
        expander = QuickEdit._expander_filter({"threshold": -40, "ratio": 3, "attack": 8, "release": 180})
        self.assertIn("agate=", expander)
        limiter = QuickEdit._limiter_filter({"ceiling": -1, "attack": 5, "release": 80})
        self.assertIn("alimiter=", limiter)
        graphic = QuickEdit._graphic_eq_filter({"b60": 1, "b250": 2, "b1000": 3, "b4000": 4, "b12000": 5})
        self.assertEqual(graphic.count("equalizer="), 5)
        for effect in (
            "Expander", "Limiter", "Band-Pass Filter", "Notch Filter",
            "Graphic Equalizer", "Parametric Equalizer", "De-Esser",
        ):
            self.assertIn(effect, QuickEdit.BUILTIN_EFFECT_PRESETS)


class MetadataTests(unittest.TestCase):
    def test_alphabetical_library_sort_modes(self):
        editor = object.__new__(QuickEdit)
        editor.library_sort_mode = "title"
        alpha = editor._selected_library_sort_key({}, "Alpha", "Zed", "Second", 0)
        beta = editor._selected_library_sort_key({}, "Beta", "Able", "First", 1)
        self.assertLess(alpha, beta)
        editor.library_sort_mode = "artist"
        self.assertGreater(
            editor._selected_library_sort_key({}, "Alpha", "Zed", "Second", 0),
            editor._selected_library_sort_key({}, "Beta", "Able", "First", 1),
        )

    def test_library_track_sort_is_numeric(self):
        track_two = QuickEdit._library_sort_key(
            "album", {"disc": "1/1", "track": "2/12"}, "Second", "Artist", "Album"
        )
        track_ten = QuickEdit._library_sort_key(
            "album", {"disc": "1/1", "track": "10/12"}, "Tenth", "Artist", "Album"
        )
        self.assertLess(track_two, track_ten)

    def test_library_sort_uses_disc_before_track(self):
        disc_one = QuickEdit._library_sort_key(
            "album", {"disc": "1", "track": "12"}, "Last on disc one", "Artist", "Album"
        )
        disc_two = QuickEdit._library_sort_key(
            "album", {"disc": "2", "track": "1"}, "First on disc two", "Artist", "Album"
        )
        self.assertLess(disc_one, disc_two)

    def test_normalizes_common_tag_aliases(self):
        tags = QuickEdit._normalized_metadata({
            "TRACKNUMBER": "03", "YEAR": "1999", "publisher": "Example Records",
            "albumartist": "Various Artists",
        })
        self.assertEqual(tags["track"], "03")
        self.assertEqual(tags["date"], "1999")
        self.assertEqual(tags["label"], "Example Records")
        self.assertEqual(tags["album_artist"], "Various Artists")

    def test_filename_tag_filler_understands_track_artist_title(self):
        tags = QuickEdit._infer_tags_from_path(os.path.join("Album Name", "07 - Artist Name - Song Name.flac"))
        self.assertEqual(tags["track"], "7")
        self.assertEqual(tags["artist"], "Artist Name")
        self.assertEqual(tags["title"], "Song Name")
        self.assertEqual(tags["album"], "Album Name")


if __name__ == "__main__":
    unittest.main()
