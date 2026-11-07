"""测完整点歌冷启动、模型复用及成品缓存，不向QQ发送。"""

import json
import time
from pathlib import Path
from uuid import uuid4

import requests

ROOT = Path(__file__).resolve().parent
session = requests.Session()
session.trust_env = False
session.headers["Authorization"] = "Bearer " + (ROOT.parent / "local-voice/bridge-token").read_text().strip()
base = "http://127.0.0.1:19880/sing/jobs"
records = []
for index in range(3):
    start = time.perf_counter()
    response = session.post(base, json={"query": "叹云兮 鞠婧祎", "request_id": uuid4().hex, "refresh": index < 2}, timeout=15)
    response.raise_for_status()
    accepted = response.json()
    job = accepted["job_id"]
    previous = None
    for _ in range(180):
        response = session.get(base + "/" + job, timeout=10)
        response.raise_for_status()
        status = response.json()
        if status["state"] != previous:
            print(index, status["state"], flush=True)
            previous = status["state"]
        if status["state"] == "error":
            raise RuntimeError(status["message"])
        if status["state"] == "done":
            metrics = ROOT / "jobs" / job / "engine-timings.json"
            record = {"job_id": job, "elapsed_seconds": round(time.perf_counter() - start, 3), "cache_hit": accepted.get("cache_hit", False), "seconds": status["seconds"], "parts": status["parts"]}
            if metrics.exists():
                record["engine"] = json.loads(metrics.read_text(encoding="utf-8"))
            records.append(record)
            print(json.dumps(record, ensure_ascii=False), flush=True)
            break
        time.sleep(.5)
    else:
        raise TimeoutError("完整点歌测试超时")
(ROOT / "benchmarks/pipeline-result.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
