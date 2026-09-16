import os
import tempfile
import unittest
from io import BytesIO
from types import SimpleNamespace

from online_backend import OnlineBackend
from media_backend import MediaError


class FakeResponse(BytesIO):
    def __init__(self, body: str, url: str):
        super().__init__(body.encode())
        self.url = url

    def geturl(self):
        return self.url


class OnlineDownloadTests(unittest.TestCase):
    def test_source_download_bypasses_ytdlp_postprocessing(self):
        backend = object.__new__(OnlineBackend)
        backend.resolve_playlist = lambda url: (url, False)
        captured = []

        with tempfile.TemporaryDirectory() as folder:
            target = os.path.join(folder, "download.source")

            def fake_ytdlp(*arguments):
                captured.extend(arguments)
                with open(target, "wb") as output:
                    output.write(b"media")

            backend._yt = fake_ytdlp
            backend.download_source("https://example.test/audio", target)

        self.assertIn("bestaudio/best", captured)
        self.assertNotIn("-x", captured)
        self.assertNotIn("--audio-format", captured)

    def test_audiovault_login_accepts_redirect_and_member_page(self):
        backend = object.__new__(OnlineBackend)
        backend._new_vault_session = lambda: None
        backend._vault_request = lambda url: b'<input name="_token" value="token123">'
        replies = iter((FakeResponse("Welcome", "https://www.audiovault.net/"), FakeResponse("Movies", "https://www.audiovault.net/movies")))
        backend._vault_response = lambda url, data=None: next(replies)
        backend.audiovault_login("member@example.test", "correct")

    def test_audiovault_login_reports_server_error_text(self):
        backend = object.__new__(OnlineBackend)
        backend._new_vault_session = lambda: None
        backend._vault_request = lambda url: b'<input name="_token" value="token123">'
        backend._vault_response = lambda url, data=None: FakeResponse(
            '<strong>These credentials do not match our records.</strong><input name="password">',
            "https://www.audiovault.net/login",
        )
        with self.assertRaisesRegex(MediaError, "These credentials"):
            backend.audiovault_login("member@example.test", "wrong")

    def test_youtube_playlist_search_uses_filtered_search_url(self):
        backend = object.__new__(OnlineBackend)
        captured = []
        backend._yt = lambda *args: (captured.extend(args) or SimpleNamespace(stdout='{"entries": [{"title": "Mix", "url": "https://www.youtube.com/playlist?list=123"}]}'))
        results = backend.search("YouTube", "test mix", kind="playlists")
        self.assertIn("sp=EgIQAw%253D%253D", captured[-1])
        self.assertEqual(results[0].kind, "playlist")

    def test_collection_entries_turns_ids_into_watch_urls(self):
        backend = object.__new__(OnlineBackend)
        backend._yt = lambda *args: SimpleNamespace(stdout='{"entries": [{"id": "abc123", "title": "Track"}]}')
        results = backend.collection_entries("https://example.test/playlist", 5)
        self.assertEqual(results[0].url, "https://www.youtube.com/watch?v=abc123")
        self.assertEqual(results[0].kind, "video")


if __name__ == "__main__":
    unittest.main()
