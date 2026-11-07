"""联网挑选轻松日常配图，将审核用的同一份图片留存到云端。"""

import hashlib
import html
import io
import itertools
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from PIL import Image, UnidentifiedImageError

STOCK_WORDS = (
    "Doja",
    "Cat Stevens",
    "专辑",
    "巡演",
    "演唱会",
    "正版",
    "摄图",
    "图片下载",
    "素材下载",
    "包图",
    "千图",
    "千库",
    "水印",
    "昵图",
)
STOCK_DOMAINS = (
    "699pic.com",
    "ibaotu.com",
    "58pic.com",
    "588ku.com",
    "nipic.com",
    "pngtree.com",
)


ANIMALS = (
    (("猫", "cat", "kitten"), r"猫|\bcats?\b|\bkitten"),
    (("水豚", "capybara"), r"水豚|capybara"),
    (("狗", "dog"), r"狗|犬|\bdogs?\b|puppy|puppies"),
    (("仓鼠", "hamster"), r"仓鼠|hamster"),
    (("鸟", "bird"), r"鸟|雀|\bbirds?\b|sparrow"),
    (("海豹", "seal"), r"海豹|\bseals?\b"),
)


def parse_pictures(page: str, query: str) -> list[dict]:
    """只解析搜索结果的数据属性，不执行页面脚本或访问素材站。"""
    result = []
    for raw in re.findall(r'\bm="([^"]+)"', page):
        try:
            item = json.loads(html.unescape(raw))
            title = str(item.get("t") or "").strip()[:150]
            source = str(item.get("purl") or "").strip()
            thumbnail = urlparse(str(item.get("turl") or ""))
            original = urlparse(source)
            image_id = parse_qs(thumbnail.query).get("id", [""])[0]
            expected = next(
                (
                    pattern
                    for keywords, pattern in ANIMALS
                    if any(key in query.lower() for key in keywords)
                ),
                "",
            )
            if expected and not re.search(expected, title, flags=re.IGNORECASE):
                continue
            if (
                not title
                or any(word in title for word in STOCK_WORDS)
                or original.scheme not in ("https", "http")
                or not original.hostname
                or any(
                    original.hostname == domain
                    or original.hostname.endswith("." + domain)
                    for domain in STOCK_DOMAINS
                )
                or not re.fullmatch(
                    r"(?:tse|ts)[1-4]\.mm\.bing\.net", thumbnail.hostname or ""
                )
                or thumbnail.path != "/th"
                or not re.fullmatch(r"OIP\.[A-Za-z0-9_-]+", image_id)
            ):
                continue
            url = f"https://{thumbnail.hostname}/th?" + urlencode(
                {"id": image_id, "pid": "Api"}
            )
            result.append(
                {
                    "title": title,
                    "summary": "日常趣图，围绕主题写心情，不虚构画面细节。",
                    "url": source,
                    "query": query,
                    "thumbnail": url,
                }
            )
        except (ValueError, TypeError, AttributeError):
            continue
    return result


async def find_pictures(queries: list[str], folder: Path) -> list[dict]:
    """最多搜索三组、尝试十二张图片，最终保存三张不同配图。"""
    groups = []
    async with httpx.AsyncClient(timeout=12, trust_env=False) as client:
        for query in queries[:3]:
            try:
                async with client.stream(
                    "GET",
                    "https://www.bing.com/images/search",
                    params={"q": query[:100], "adlt": "strict"},
                    follow_redirects=True,
                ) as response:
                    response.raise_for_status()
                    chunks = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 2_000_000:
                            raise ValueError("搜索页过大")
                        chunks.append(chunk)
                groups.append(
                    parse_pictures(
                        b"".join(chunks).decode("utf-8", errors="replace"), query
                    )[:8]
                )
            except (httpx.HTTPError, ValueError):
                continue
        selected = []
        seen = set()
        # 交错挑选不同主题，避免三条草稿全部围绕同一种图片。
        candidates = (
            item for row in itertools.zip_longest(*groups) for item in row if item
        )
        for item in itertools.islice(candidates, 12):
            try:
                chunks = []
                size = 0
                async with client.stream(
                    "GET", item["thumbnail"], follow_redirects=False
                ) as response:
                    response.raise_for_status()
                    if not response.headers.get("content-type", "").startswith(
                        "image/"
                    ):
                        continue
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 3_000_000:
                            raise ValueError("图片过大")
                        chunks.append(chunk)
                content = b"".join(chunks)
                digest = hashlib.sha256(content).hexdigest()
                if digest in seen:
                    continue
                with Image.open(io.BytesIO(content)) as picture:
                    if (
                        picture.format not in ("JPEG", "PNG", "WEBP", "GIF")
                        or not 64 <= min(picture.size)
                        or max(picture.size) > 4096
                    ):
                        continue
                    extension = {
                        "JPEG": "jpg",
                        "PNG": "png",
                        "WEBP": "webp",
                        "GIF": "gif",
                    }[picture.format]
                    picture.verify()
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / f"{digest}.{extension}"
                if not path.exists():
                    temporary = path.with_suffix(".tmp")
                    temporary.write_bytes(content)
                    temporary.replace(path)
                selected.append(
                    dict(
                        item,
                        image_path=str(path.resolve()),
                        image_sha256=digest,
                        image_size=len(content),
                    )
                )
                seen.add(digest)
                if len(selected) == 3:
                    break
            except (
                httpx.HTTPError,
                OSError,
                ValueError,
                UnidentifiedImageError,
                Image.DecompressionBombError,
            ):
                continue
        return selected
