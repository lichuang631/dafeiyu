"""只生成和读取音频，不向QQ发送；验证真实点歌流程。"""

import json
import time
from pathlib import Path
from uuid import uuid4

import requests

ROOT = Path(__file__).resolve().parent
token = (ROOT.parent / "local-voice/bridge-token").read_text(encoding="utf-8").strip()
session = requests.Session()
session.trust_env = False
session.headers["Authorization"] = "Bearer " + token
base = "http://127.0.0.1:19880"
job = uuid4().hex
response = session.post(base + "/sing/jobs", json={"query": "叹云兮 鞠婧祎", "request_id": job}, timeout=15)
response.raise_for_status()
previous = None
for _ in range(180):
    response = session.get(base + "/sing/jobs/" + job, timeout=10)
    response.raise_for_status()
    status = response.json()
    if status["state"] != previous:
        print(status["state"], status.get("message", ""), flush=True)
        previous = status["state"]
    if status["state"] == "error":
        raise SystemExit(json.dumps(status, ensure_ascii=False))
    if status["state"] == "done":
        target = ROOT / "verified-parts"
        target.mkdir(exist_ok=True)
        for part in range(status["parts"]):
            audio = session.get(base + f"/sing/jobs/{job}/audio/{part}", timeout=20)
            audio.raise_for_status()
            (target / f"part-{part}.mp3").write_bytes(audio.content)
        status["job_id"] = job
        (ROOT / "verify-result.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        print("LOCAL-SINGING-VERIFIED", status["seconds"], status["parts"], status["song"]["preview_only"], flush=True)
        break
    time.sleep(2)
else:
    raise SystemExit("唱歌测试等待超时")
