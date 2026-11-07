"""只查询公开曲目信息及播放/试听链接，不保存音乐平台登录信息。"""

import json
import re
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

HEADERS = {"Referer": "https://y.qq.com/", "User-Agent": "Mozilla/5.0"}
MAX_BYTES = 25_000_000


class MusicUnavailable(ValueError):
    pass


def normalized(text):
    return re.sub(r"[^\w]", "", text).lower()


def search_song(query):
    response = requests.get(
        "https://c.y.qq.com/soso/fcgi-bin/client_search_cp",
        params={"p": 1, "n": 5, "w": query, "format": "json"},
        headers=HEADERS, timeout=20,
    )
    response.raise_for_status()
    songs = response.json().get("data", {}).get("song", {}).get("list", [])
    terms = [normalized(t) for t in query.split() if normalized(t)]
    for song in songs:
        title = song.get("songname", "")
        artist = " / ".join(s.get("name", "") for s in song.get("singer", []))
        combined = normalized(title + artist)
        if terms and all(term in combined for term in terms):
            return {
                "title": title, "artist": artist, "song_mid": song["songmid"],
                "media_mid": song.get("media_mid") or song.get("strMediaMid"),
                "source": "QQ音乐", "query": query,
            }
    raise MusicUnavailable("没找到匹配的歌名和歌手，请把歌名、歌手用空格分开再试。")


def playback_url(song, preview=False):
    param = {
        "guid": str(uuid.uuid4().int)[:10], "songmid": [song["song_mid"]],
        "songtype": [0], "uin": "0", "loginflag": 1, "platform": "20",
    }
    if preview:
        media = song.get("media_mid")
        if not media or not re.fullmatch(r"[A-Za-z0-9]+", media):
            return None
        param["filename"] = [f"RS02{media}.mp3"]
    request = {
        "comm": {"uin": 0, "format": "json", "ct": 24, "cv": 0},
        "req_0": {"module": "vkey.GetVkeyServer", "method": "CgiGetVkey", "param": param},
    }
    response = requests.get(
        "https://u.y.qq.com/cgi-bin/musicu.fcg",
        params={"format": "json", "data": json.dumps(request)},
        headers=HEADERS, timeout=20,
    )
    response.raise_for_status()
    data = response.json().get("req_0", {}).get("data", {})
    for entry in data.get("midurlinfo", []):
        if entry.get("purl") and data.get("sip"):
            return urljoin(data["sip"][0], entry["purl"])
    return None


def allowed_audio_url(url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme in ("http", "https") and parsed.port in (None, 80, 443)
        and not parsed.username and not parsed.password
        and any(host == domain or host.endswith("." + domain) for domain in ("qq.com", "qqmusic.com", "gtimg.com"))
    )


def download_audio(url, target: Path):
    for _ in range(5):
        if not allowed_audio_url(url):
            raise MusicUnavailable("音源地址不属于配置的音乐平台。")
        with requests.get(url, headers=HEADERS, stream=True, allow_redirects=False, timeout=(10, 40)) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers["Location"])
                continue
            response.raise_for_status()
            length = int(response.headers.get("Content-Length", 0))
            if length > MAX_BYTES:
                raise MusicUnavailable("歌曲文件超过25MB限制，请选择较短版本。")
            size = 0
            with target.open("wb") as output:
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise MusicUnavailable("歌曲文件超过25MB限制。")
                    output.write(chunk)
            if size < 10_000:
                raise MusicUnavailable("音乐平台暂未提供可用音频。")
            return
    raise MusicUnavailable("音乐链接跳转过多，请稍后再试。")


def find_and_download(query, target):
    song = search_song(query)
    for preview in (False, True):
        url = playback_url(song, preview)
        if not url:
            continue
        try:
            download_audio(url, target)
            return {**song, "preview_only": preview}
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code not in (403, 404):
                raise
    raise MusicUnavailable("这首歌暂未提供可用公开音源或试听，可能需要音乐账号授权；没有开始换声。")
