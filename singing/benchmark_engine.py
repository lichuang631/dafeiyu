"""相同60秒音源连续处理两次，记录冷启动与复用耗时，不发送QQ。"""

import argparse
import io
import json
import shutil
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import requests
import soundfile as sf

ROOT = Path(__file__).resolve().parent
session = requests.Session()
session.trust_env = False
session.headers["Authorization"] = "Bearer " + (ROOT.parent / "local-voice/bridge-token").read_text().strip()
records = []
parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, required=True)
args = parser.parse_args()
for index in range(2):
    job = ROOT / "jobs" / uuid4().hex
    job.mkdir()
    shutil.copyfile(args.source, job / "original.audio")
    (job / "status.json").write_text(json.dumps({"state": "queued", "started_at": time.time()}), encoding="utf-8")
    start = time.perf_counter()
    response = session.post("http://127.0.0.1:19881/process", json={"job_id": job.name}, timeout=240)
    response.raise_for_status()
    result = response.json()
    record = {"job_id": job.name, "seconds": round(time.perf_counter() - start, 3), **result["timings"]}
    records.append(record)
    print(json.dumps(record, ensure_ascii=False), flush=True)
gpu = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader"], text=True).strip()
response = session.post("http://127.0.0.1:19880/tts", json={"text": "主人，我是大肥鱼。忙完了就来找我呀。"}, timeout=35)
response.raise_for_status()
audio, rate = sf.read(io.BytesIO(response.content))
print("POST_ENGINE_SPEECH_OK", round(len(audio) / rate, 2), "GPU", gpu, flush=True)
report = {"records": records, "post_engine_speech_ok": True, "idle_gpu_memory": gpu}
(ROOT / "benchmarks/engine-result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
