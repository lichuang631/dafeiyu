"""复用现有私有语音连接，受理本机唱歌任务；一次只运行一首。"""

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent / "singing"
sys.path.insert(0, str(ROOT))
from cache import find_result
from worker import write_status

JOBS = ROOT / "jobs"
processes = {}
start_lock = asyncio.Lock()


class SingingRequest(BaseModel):
    query: str = Field(min_length=2, max_length=80)
    request_id: str = Field(pattern="^[a-f0-9]{32}$")
    refresh: bool = False


def job_path(identifier):
    if not re.fullmatch(r"[a-f0-9]{32}", identifier):
        raise HTTPException(status_code=404, detail="任务不存在")
    return JOBS / identifier


def read_status(identifier):
    job = job_path(identifier)
    if not (job / "status.json").exists():
        raise HTTPException(status_code=404, detail="任务不存在")
    data = json.loads((job / "status.json").read_text(encoding="utf-8"))
    process = processes.get(identifier)
    if data["state"] not in ("done", "error") and (process is None or process.poll() is not None):
        return {**data, "state": "error", "message": "本地任务已中断，请重新点歌。"}
    elapsed = time.time() - data.get("started_at", time.time())
    inactive = time.time() - data.get("updated_at", data.get("started_at", time.time()))
    duration = float(data.get("seconds", 60))
    limit = {"queued": 60, "searching": 120, "separating": max(90, duration * 1.5), "converting": max(120, duration * 2), "mixing": 60}.get(data["state"], 900)
    if process and process.poll() is None and (elapsed > 900 or inactive > limit):
        config = ROOT / "acceleration.json"
        if config.exists() and json.loads(config.read_text(encoding="utf-8")).get("enabled"):
            import requests
            token = (ROOT.parent / "local-voice/bridge-token").read_text(encoding="utf-8").strip()
            try:
                requests.post("http://127.0.0.1:19881/cancel", json={"job_id": identifier}, headers={"Authorization": "Bearer " + token}, timeout=2)
            except requests.RequestException:
                pass
        subprocess.run([str(Path(os.environ["WINDIR"]) / "System32/taskkill.exe"), "/PID", str(process.pid), "/T", "/F"], check=False, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        write_status(job, "error", message="本次处理超时，已停止任务；可以稍后重试或换一首歌。")
        return json.loads((job / "status.json").read_text(encoding="utf-8"))
    return data


def build_router(authenticate, settings):
    router = APIRouter()

    def start_job(body):
        query = body.query.strip()
        if not query or "://" in query or any(ord(c) < 32 for c in query):
            raise HTTPException(status_code=422, detail="请输入歌名与歌手，不接受链接")
        job = job_path(body.request_id)
        if job.exists():
            old = json.loads((job / "request.json").read_text(encoding="utf-8"))
            if old["query"] != query:
                raise HTTPException(status_code=409, detail="任务编号已使用")
            return {"job_id": body.request_id, **read_status(body.request_id)}
        cached = None if body.refresh else find_result(query, settings["reference_audio"], JOBS)
        if cached:
            return {"job_id": cached, **read_status(cached), "cache_hit": True}
        if any(p.poll() is None for p in processes.values()):
            raise HTTPException(status_code=429, detail="正在唱另一首，完成后再点歌")
        python = ROOT / ".venv/Scripts/python.exe"
        if not python.exists() or not (ROOT / "worker.py").exists():
            raise HTTPException(status_code=503, detail="本地唱歌组件尚未准备好")
        job.mkdir(parents=True)
        (job / "request.json").write_text(json.dumps({"query": query}, ensure_ascii=False), encoding="utf-8")
        (job / "status.json").write_text(json.dumps({"state": "queued", "started_at": time.time(), "message": "已接收点歌。"}, ensure_ascii=False), encoding="utf-8")
        with (job / "worker.log").open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                [str(python), "-u", str(ROOT / "worker.py"), "--job", str(job), "--reference", settings["reference_audio"]],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONUTF8": "1"}, creationflags=subprocess.CREATE_NO_WINDOW,
            )
        processes[body.request_id] = process
        return {"job_id": body.request_id, **read_status(body.request_id)}

    @router.post("/sing/jobs")
    async def start(body: SingingRequest, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        async with start_lock:
            return await asyncio.to_thread(start_job, body)

    @router.get("/sing/jobs/{identifier}")
    async def status(identifier: str, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        return read_status(identifier)

    @router.get("/sing/jobs/{identifier}/audio/{part}")
    async def audio(identifier: str, part: int, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        data = read_status(identifier)
        if data["state"] != "done" or not 0 <= part < data.get("parts", 0):
            raise HTTPException(status_code=404, detail="音频尚不可用")
        path = job_path(identifier) / f"part-{part}.mp3"
        if not path.exists() or path.stat().st_size > 2_000_000:
            raise HTTPException(status_code=404, detail="音频尚不可用")
        return FileResponse(path, media_type="audio/mpeg")

    return router
