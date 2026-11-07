"""仅在本机提供已训练模型的语音合成接口。"""

import asyncio
import io
import json
import os
import secrets
import sys
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT / "GPT-SoVITS"
os.chdir(REPO)
sys.path[:0] = [str(REPO), str(REPO / "GPT_SoVITS")]
os.environ["version"] = "v2ProPlus"
os.environ["language"] = "zh_CN"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["PYTHONUTF8"] = "1"
os.environ["NLTK_DATA"] = str(ROOT / "model-cache/nltk_data")

import soundfile as sf
from audio_cleanup import clean_generated_audio
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from TTS_infer_pack.TTS import TTS, TTS_Config

settings = json.loads((ROOT / "trained-voice.json").read_text(encoding="utf-8"))
token = (ROOT / "bridge-token").read_text(encoding="utf-8").strip()
engine = None
generation_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(_app):
    global engine
    engine = await asyncio.to_thread(TTS, TTS_Config(settings["config_path"]))
    print("大肥鱼本地训练声音已就绪。", flush=True)
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def authenticate(authorization):
    if not authorization or not secrets.compare_digest(
        authorization, "Bearer " + token
    ):
        raise HTTPException(status_code=401, detail="未授权")


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=800)


@app.get("/health")
async def health(authorization: str | None = Header(default=None)):
    authenticate(authorization)
    return {"ready": engine is not None, "model": "dafeiyu-v2ProPlus-trained"}


def synthesize(text):
    request = {
        "text": text,
        "text_lang": "zh",
        "ref_audio_path": settings["reference_audio"],
        "prompt_text": settings["reference_text"],
        "prompt_lang": "zh",
        "top_k": 15,
        "top_p": 0.9,
        "temperature": 0.8,
        "text_split_method": "cut2",
        "batch_size": 1,
        "speed_factor": 1.0,
        "seed": 33525,
        "parallel_infer": False,
        "use_cuda_graph": False,
        "use_flash_attention": False,
        "split_bucket": False,
        "repetition_penalty": 1.35,
        "streaming_mode": False,
    }
    pieces = list(engine.run(request))
    if not pieces:
        raise RuntimeError("模型没有生成音频")
    import numpy as np

    rate = pieces[0][0]
    audio = np.concatenate([item[1] for item in pieces])
    normalized = (
        audio.astype(np.float32) / 32768
        if np.issubdtype(audio.dtype, np.integer)
        else audio
    )
    if len(audio) / rate < len(text) * 0.06 or np.max(np.abs(normalized)) < 0.01:
        raise RuntimeError("本地模型返回静音或不完整音频")
    if settings.get("denoise_generated", False):
        audio = clean_generated_audio(audio, rate)
    buffer = io.BytesIO()
    sf.write(buffer, audio, rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


@app.post("/tts")
async def tts(body: SpeechRequest, authorization: str | None = Header(default=None)):
    authenticate(authorization)
    if engine is None:
        raise HTTPException(status_code=503, detail="模型尚未就绪")
    async with generation_lock:
        content = await asyncio.to_thread(synthesize, body.text)
    if len(content) > 8_000_000:
        raise HTTPException(status_code=413, detail="合成音频过长")
    return Response(content, media_type="audio/wav")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=19880, access_log=False)
