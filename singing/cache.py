"""只复用同曲、同参考声音、同处理版本且文件完整的成功成品。"""

import hashlib
import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = "mdxhq3-seed44-f030-mix12-065-v1"
TTL = 7 * 86400


def cache_key(query, reference):
    reference = Path(reference)
    if not reference.is_file():
        return None
    version = VERSION
    weights = ROOT / "seed-vc/checkpoints"
    if weights.exists():
        info = [(p.relative_to(weights).as_posix(), p.stat().st_size, p.stat().st_mtime_ns) for p in weights.rglob("*") if p.is_file() and p.suffix in (".pth", ".pt", ".safetensors")]
        version += json.dumps(sorted(info))
    payload = {"query": " ".join(query.split()).casefold(), "reference": hashlib.sha256(reference.read_bytes()).hexdigest(), "version": version}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def store_result(job, reference):
    status = json.loads((job / "status.json").read_text(encoding="utf-8"))
    query = json.loads((job / "request.json").read_text(encoding="utf-8"))["query"]
    key = cache_key(query, reference)
    if not key or status.get("state") != "done" or not re.fullmatch(r"[a-f0-9]{32}", job.name):
        return
    parts = int(status.get("parts", 0))
    if not 1 <= parts <= 6:
        return
    files = []
    for i in range(parts):
        path = job / f"part-{i}.mp3"
        if not path.is_file() or not 10_000 <= path.stat().st_size <= 2_000_000:
            return
        files.append(hashlib.sha256(path.read_bytes()).hexdigest())
    folder = job.parent.parent / "cache-index"
    folder.mkdir(exist_ok=True)
    temporary = folder / f"{key}.tmp"
    temporary.write_text(json.dumps({"job_id": job.name, "hashes": files, "created_at": time.time()}), encoding="utf-8")
    temporary.replace(folder / f"{key}.json")


def find_result(query, reference, jobs):
    key = cache_key(query, reference)
    if not key:
        return None
    try:
        record = json.loads((jobs.parent / "cache-index" / f"{key}.json").read_text(encoding="utf-8"))
        if time.time() - record["created_at"] > TTL or not re.fullmatch(r"[a-f0-9]{32}", record["job_id"]):
            return None
        job = jobs / record["job_id"]
        status = json.loads((job / "status.json").read_text(encoding="utf-8"))
        if status["state"] != "done" or status["parts"] != len(record["hashes"]):
            return None
        for index, expected in enumerate(record["hashes"]):
            path = job / f"part-{index}.mp3"
            if not 10_000 <= path.stat().st_size <= 2_000_000 or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                return None
        return job.name
    except (OSError, ValueError, KeyError, TypeError):
        return None
