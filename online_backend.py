from __future__ import annotations

import html
import http.cookiejar
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass

from media_backend import CREATE_NO_WINDOW, MediaError


@dataclass(frozen=True)
class OnlineResult:
    title: str
    url: str
    provider: str
    detail: str = ""
    kind: str = "video"


class OnlineBackend:
    def __init__(self, app_dir: str) -> None:
        self.ytdlp = os.path.join(app_dir, "runtime", "yt-dlp.exe")
        self.ffmpeg_location = os.path.normpath(
            os.path.join(
                app_dir, "..", "work", "quickedit", "apricot-player",
                "ApricotPlayer", "_internal", "ffmpeg",
            )
        )
        local_ffmpeg = os.path.join(app_dir, "ffmpeg.exe")
        if os.path.isfile(local_ffmpeg):
            self.ffmpeg_location = app_dir
        self.cookies = http.cookiejar.CookieJar()
        self.vault = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 QuickEdit/0.1"

    def _yt(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        if not os.path.isfile(self.ytdlp):
            raise MediaError("The yt-dlp runtime was not found.")
        ffmpeg_args = ["--ffmpeg-location", self.ffmpeg_location] if os.path.isdir(self.ffmpeg_location) else []
        result = subprocess.run(
            [self.ytdlp, "--no-warnings", "--remote-components", "ejs:github", *ffmpeg_args, *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode:
            lines = result.stderr.strip().splitlines()
            raise MediaError(lines[-1] if lines else "The online media operation failed.")
        return result

    def search(self, provider: str, query: str, limit: int = 20, kind: str = "videos") -> list[OnlineResult]:
        result_kind = "video"
        if provider == "YouTube" and kind in {"playlists", "channels"}:
            filters = {"playlists": "EgIQAw%253D%253D", "channels": "EgIQAg%253D%253D"}
            search_url = "https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": query}) + f"&sp={filters[kind]}"
            result = self._yt("--flat-playlist", "--dump-single-json", "--playlist-end", str(limit), search_url)
            result_kind = kind[:-1]
        elif provider == "YouTube":
            search_url = "https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": query}) + "&sp=EgIQAQ%253D%253D"
            result = self._yt("--flat-playlist", "--dump-single-json", "--playlist-end", str(limit), search_url)
        else:
            result = self._yt("--flat-playlist", "--dump-single-json", f"scsearch{limit}:{query}")
        payload = json.loads(result.stdout)
        items = []
        for entry in payload.get("entries") or []:
            if not entry:
                continue
            url = entry.get("webpage_url") or entry.get("url")
            if not url:
                continue
            duration = entry.get("duration")
            duration_text = f", {round(duration)} seconds" if isinstance(duration, (int, float)) else ""
            uploader = entry.get("uploader") or entry.get("channel") or "unknown uploader"
            detail = result_kind if result_kind != "video" else f"{uploader}{duration_text}"
            items.append(OnlineResult(entry.get("title") or "Untitled", url, provider, detail, result_kind))
        return items

    def collection_entries(self, url: str, limit: int = 0) -> list[OnlineResult]:
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc.endswith("youtube.com") and "/channel/" in parsed.path and parsed.path.rstrip("/").count("/") == 2:
            url = url.rstrip("/") + "/videos"
        arguments = ["--flat-playlist", "--dump-single-json"]
        if limit:
            arguments.extend(("--playlist-end", str(limit)))
        payload = json.loads(self._yt(*arguments, url).stdout)
        entries = []
        for entry in payload.get("entries") or []:
            if not entry:
                continue
            item_url = entry.get("webpage_url") or entry.get("url")
            if (not item_url or not item_url.startswith("http")) and entry.get("id"):
                item_url = f"https://www.youtube.com/watch?v={entry['id']}"
            if not item_url:
                continue
            duration = entry.get("duration")
            detail = f"{round(duration)} seconds" if isinstance(duration, (int, float)) else "video"
            entries.append(OnlineResult(entry.get("title") or "Untitled", item_url, "YouTube", detail, "video"))
        return entries

    def preview_url(self, url: str) -> str:
        url, _ = self.resolve_playlist(url)
        result = self._yt("-f", "bestaudio/best", "-g", url)
        urls = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not urls:
            raise MediaError("No playable audio stream was found.")
        return urls[0]

    def import_url(self, url: str, wav_target: str) -> None:
        url, was_playlist = self.resolve_playlist(url)
        if was_playlist:
            raise MediaError("That address is a live radio playlist. Use Preview Direct URL; live streams do not have a natural end to download.")
        self._yt("-f", "bestaudio/best", "-x", "--audio-format", "wav", "-o", wav_target, url)
        if not os.path.isfile(wav_target):
            raise MediaError("The online audio download did not produce a WAV file.")

    def download_source(self, url: str, target: str) -> None:
        """Download the selected stream without yt-dlp postprocessing.

        QuickEdit converts the result with its own FFmpeg stage. This avoids
        yt-dlp relying on ffprobe to identify unusual or newly introduced
        streaming codecs before extraction.
        """
        url, was_playlist = self.resolve_playlist(url)
        if was_playlist:
            raise MediaError("That address is a live radio playlist. Use Preview Direct URL; live streams do not have a natural end to download.")
        self._yt("-f", "bestaudio/best", "--no-part", "-o", target, url)
        if not os.path.isfile(target):
            raise MediaError("The online audio download did not produce a media file.")

    def resolve_playlist(self, url: str) -> tuple[str, bool]:
        path = urllib.parse.urlparse(url).path.lower()
        if not path.endswith((".pls", ".m3u", ".m3u8")):
            return url, False
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        text = urllib.request.urlopen(request, timeout=20).read().decode("utf-8", "replace")
        candidates = []
        if path.endswith(".pls"):
            candidates = re.findall(r"(?im)^File\d+\s*=\s*(https?://\S+)", text)
        else:
            candidates = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
        if not candidates:
            raise MediaError("The radio playlist did not contain a playable stream address.")
        return urllib.parse.urljoin(url, candidates[0]), True

    def _new_vault_session(self) -> None:
        self.cookies = http.cookiejar.CookieJar()
        self.vault = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def _vault_response(self, url: str, data: dict[str, str] | None = None):
        encoded = urllib.parse.urlencode(data).encode() if data is not None else None
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if data is not None:
            headers.update({"Origin": "https://www.audiovault.net", "Referer": "https://www.audiovault.net/login"})
        request = urllib.request.Request(url, data=encoded, headers=headers)
        return self.vault.open(request, timeout=45)

    def _vault_request(self, url: str, data: dict[str, str] | None = None) -> bytes:
        return self._vault_response(url, data).read()

    def audiovault_login(self, email: str, password: str) -> None:
        # A rejected or expired Laravel CSRF session can survive between login
        # attempts. Always begin a deliberate login with a clean cookie jar.
        self._new_vault_session()
        page = self._vault_request("https://www.audiovault.net/login").decode("utf-8", "replace")
        token = re.search(r'name="_token"\s+value="([^"]+)"', page)
        if not token:
            raise MediaError("AudioVault did not provide a valid login form.")
        login_response = self._vault_response(
            "https://www.audiovault.net/login",
            {"_token": token.group(1), "email": email, "password": password, "remember": "on"},
        )
        final_url = login_response.geturl()
        response = login_response.read().decode("utf-8", "replace")
        if urllib.parse.urlparse(final_url).path.rstrip("/") == "/login" or 'name="password"' in response:
            error = re.search(r"<strong[^>]*>(.*?)</strong>", response, flags=re.I | re.S)
            detail = html.unescape(re.sub(r"<[^>]+>", "", error.group(1))).strip() if error else ""
            if detail:
                raise MediaError(f"AudioVault rejected the login: {detail}")
            raise MediaError("AudioVault returned its login form again. The session may have expired or the account may require attention on the AudioVault website.")

        # Confirm the new cookies reach a member-only page. This distinguishes
        # a real login from a server or protection page that merely lacks the
        # password field.
        check = self._vault_response("https://www.audiovault.net/movies")
        check_url = urllib.parse.urlparse(check.geturl()).path.rstrip("/")
        check_page = check.read().decode("utf-8", "replace")
        if check_url == "/login" or 'name="password"' in check_page:
            raise MediaError("AudioVault did not keep the login session. Try signing in on the AudioVault website once, then try QuickEdit again.")

    def audiovault_logout(self) -> None:
        self.cookies.clear()

    def audiovault_search(self, query: str, section: str = "movies") -> list[OnlineResult]:
        url = f"https://www.audiovault.net/{section}?{urllib.parse.urlencode({'search': query})}"
        page = self._vault_request(url).decode("utf-8", "replace")
        results = []
        for row in re.findall(r"<tr>(.*?)</tr>", page, flags=re.I | re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.I | re.S)
            link = re.search(r'href="(https://www\.audiovault\.net/download/\d+)"', row, flags=re.I)
            if len(cells) >= 2 and link:
                title = html.unescape(re.sub(r"<[^>]+>", "", cells[1])).strip()
                if title:
                    results.append(OnlineResult(title, link.group(1), "AudioVault", section[:-1]))
        return results

    def audiovault_download(self, url: str, target: str) -> None:
        data = self._vault_request(url)
        if data.lstrip().startswith(b"<"):
            raise MediaError("AudioVault requires a valid login, or the session has expired.")
        with open(target, "wb") as output:
            output.write(data)
