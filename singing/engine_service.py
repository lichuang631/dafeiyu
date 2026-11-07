"""本机按需加载并复用歌声模型，单任务处理，闲置释放显存。"""

import argparse
import asyncio
import gc
import json
import os
import secrets
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT / "seed-vc")
sys.path[:0] = [str(ROOT / "seed-vc"), str(ROOT.parent / "local-voice"), str(ROOT)]
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_XET"] = "1"

import onnxruntime as ort
import torch
from audio_separator.separator import Separator
from fastapi import FastAPI, Header, HTTPException
from gpu_lock import gpu_lock
from pydantic import BaseModel, Field
from worker import write_status

ort.preload_dlls()
TOKEN = (ROOT.parent / "local-voice/bridge-token").read_text(encoding="utf-8").strip()


class Engine:
    def __init__(self):
        self.separator = None
        self.models = None
        self.inference = None
        self.lock = threading.Lock()
        self.last_used = time.monotonic()
        self.current_job = None

    def separate(self, job, source):
        if self.separator is None:
            self.separator = Separator(
                model_file_dir=str(ROOT / "separation-models"), output_dir=str(job / "stems"),
                output_format="WAV", sample_rate=44100,
                mdx_params={"hop_length": 1024, "segment_size": 256, "overlap": 0.25, "batch_size": 1, "enable_denoise": False},
            )
            self.separator.onnx_execution_provider = [
                ("CUDAExecutionProvider", {"gpu_mem_limit": 2 * 1024**3, "arena_extend_strategy": "kSameAsRequested", "cudnn_conv_algo_search": "HEURISTIC", "cudnn_conv_use_max_workspace": "0", "use_tf32": "0"}),
                "CPUExecutionProvider",
            ]
            self.separator.load_model(model_filename="UVR-MDX-NET-Inst_HQ_3.onnx")
            runner = self.separator.model_instance.model_run
            session = next(cell.cell_contents for cell in runner.__closure__ if isinstance(cell.cell_contents, ort.InferenceSession))
            if session.get_providers()[0] != "CUDAExecutionProvider":
                raise RuntimeError("未实际启用CUDA分离")
            options = ort.RunOptions()
            options.add_run_config_entry("memory.enable_memory_arena_shrinkage", "gpu:0")
            self.separator.model_instance.model_run = lambda values: session.run(None, {"input": values.cpu().numpy()}, options)[0]
        self.separator.output_dir = str(job / "stems")
        self.separator.model_instance.output_dir = str(job / "stems")
        (job / "stems").mkdir(exist_ok=True)
        return self.separator.separate(str(source))

    def process(self, job):
        source = job / "limited.wav"
        if not source.exists():
            source = job / "original.audio"
        if not source.exists():
            raise ValueError("音源尚未准备好")
        settings = json.loads((ROOT.parent / "local-voice/trained-voice.json").read_text(encoding="utf-8"))
        timings = {"models_reused": self.models is not None}
        with gpu_lock(timeout=45):
            write_status(job, "separating", message="正在用显卡分离人声与伴奏。")
            started = time.perf_counter()
            stems = self.separate(job, source)
            timings["separation_seconds"] = round(time.perf_counter() - started, 3)
            vocals = next(job / "stems" / p for p in stems if "(Vocals)" in p)
            accompaniment = next(job / "stems" / p for p in stems if "(Instrumental)" in p)
            write_status(job, "converting", message="正在换成大肥鱼的声音。")
            started = time.perf_counter()
            if self.models is None:
                import inference
                self.inference = inference
                self.models = inference.load_models(argparse.Namespace(f0_condition=True, fp16=True, checkpoint=None, config=None))
                inference.load_models = lambda args: self.models
            timings["model_load_seconds"] = round(time.perf_counter() - started, 3)
            started = time.perf_counter()
            self.inference.main(argparse.Namespace(
                source=str(vocals), target=settings["reference_audio"], output=str(job / "converted"),
                f0_condition=True, fp16=True, auto_f0_adjust=False, semi_tone_shift=0,
                diffusion_steps=30, length_adjust=1.0, inference_cfg_rate=0.7,
                checkpoint=None, config=None,
            ))
            timings["conversion_seconds"] = round(time.perf_counter() - started, 3)
            torch.cuda.empty_cache()
        self.last_used = time.monotonic()
        gc.collect()
        (job / "engine-timings.json").write_text(json.dumps(timings, indent=2), encoding="utf-8")
        return {"converted": str(next((job / "converted").glob("*.wav"))), "accompaniment": str(accompaniment), "timings": timings}


engine = Engine()


def authenticate(header):
    if not header or not secrets.compare_digest(header, "Bearer " + TOKEN):
        raise HTTPException(status_code=401, detail="未授权")


@asynccontextmanager
async def lifespan(app):
    async def release_idle():
        while True:
            await asyncio.sleep(10)
            if engine.models is not None and not engine.lock.locked() and time.monotonic() - engine.last_used > 90:
                print("歌声引擎闲置90秒，释放显存；管理器将保留轻量待命进程。", flush=True)
                os._exit(0)
    task = asyncio.create_task(release_idle())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


class Request(BaseModel):
    job_id: str = Field(pattern="^[a-f0-9]{32}$")


@app.get("/health")
def health(authorization: str | None = Header(default=None)):
    authenticate(authorization)
    return {"ready": True, "loaded": engine.models is not None, "busy": engine.lock.locked()}


@app.post("/process")
def process(body: Request, authorization: str | None = Header(default=None)):
    authenticate(authorization)
    if not engine.lock.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="引擎忙碌")
    timer = threading.Timer(600, lambda: os._exit(1))
    timer.daemon = True
    timer.start()
    engine.current_job = body.job_id
    try:
        return engine.process(ROOT / "jobs" / body.job_id)
    except Exception as exc:  # noqa: BLE001 -- 隔离GPU任务并返回明确失败，不泄露本机路径。
        print("歌声加速失败：", type(exc).__name__, str(exc)[:160], flush=True)
        raise HTTPException(status_code=500, detail="歌声加速处理失败") from None
    finally:
        timer.cancel()
        engine.last_used = time.monotonic()
        engine.current_job = None
        engine.lock.release()


@app.post("/cancel")
def cancel(body: Request, authorization: str | None = Header(default=None)):
    authenticate(authorization)
    if engine.current_job == body.job_id:
        timer = threading.Timer(0.1, lambda: os._exit(1))
        timer.daemon = True
        timer.start()
        return {"cancelled": True}
    return {"cancelled": False}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=19881, access_log=False)
