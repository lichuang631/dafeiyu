"""本地串行执行搜歌、人声分离、指定声音转换、伴奏混音。"""

import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

from music import MusicUnavailable, find_and_download

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "local-voice"))
from gpu_lock import gpu_lock


def write_status(job, state, **details):
    status = job / "status.json"
    previous = json.loads(status.read_text(encoding="utf-8")) if status.exists() else {}
    temporary = job / "status.tmp"
    temporary.write_text(json.dumps({**previous, **details, "state": state, "updated_at": time.time()}, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(status)


def run(args, **options):
    timeout = options.pop("timeout", 600)
    process = subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW, **options)
    try:
        code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        subprocess.run([str(Path(os.environ["WINDIR"]) / "System32/taskkill.exe"), "/PID", str(process.pid), "/T", "/F"], check=False, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        process.wait(timeout=10)
        raise
    if code:
        raise subprocess.CalledProcessError(code, args)


def duration(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)], check=True, capture_output=True, timeout=15)
    seconds = float(json.loads(result.stdout)["format"]["duration"])
    if not math.isfinite(seconds) or seconds <= 1:
        raise MusicUnavailable("音源无法解码或时长过短。")
    return seconds


def make_cover(job, reference):
    from audio_separator.separator import Separator

    source = job / "original.audio"
    write_status(job, "searching", message="正在搜索原唱与可用音源。")
    song = find_and_download(json.loads((job / "request.json").read_text(encoding="utf-8"))["query"], source)
    seconds = duration(source)
    clipped = seconds > 300
    if clipped:
        limited = job / "limited.wav"
        run(["ffmpeg", "-y", "-v", "error", "-i", str(source), "-t", "300", "-ar", "44100", str(limited)])
        source = limited
        seconds = 300
    write_status(job, "separating", song=song, seconds=seconds, clipped=clipped, message="正在分离人声与伴奏。")
    separator = Separator(
        model_file_dir=str(ROOT / "separation-models"), output_dir=str(job / "stems"),
        output_format="WAV", sample_rate=44100,
        mdx_params={"hop_length": 1024, "segment_size": 256, "overlap": 0.25, "batch_size": 1, "enable_denoise": False},
    )
    separator.load_model(model_filename="UVR-MDX-NET-Inst_HQ_3.onnx")
    stems = separator.separate(str(source))
    vocals = next(job / "stems" / p for p in stems if "(Vocals)" in p)
    accompaniment = next(job / "stems" / p for p in stems if "(Instrumental)" in p)
    del separator
    write_status(job, "converting", message="正在换成大肥鱼的声音，保留原曲旋律。")
    environment = {**os.environ, "PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_XET": "1"}
    with gpu_lock(timeout=45):
        run([
            sys.executable, "-u", "inference.py", "--source", str(vocals), "--target", str(reference),
            "--output", str(job / "converted"), "--f0-condition", "True", "--auto-f0-adjust", "False",
            "--semi-tone-shift", "0", "--diffusion-steps", "30", "--fp16", "True",
        ], cwd=ROOT / "seed-vc", env=environment, timeout=600)
    converted = next((job / "converted").glob("*.wav"))
    if abs(duration(converted) - seconds) > max(1.0, seconds * 0.03):
        raise ValueError("换声结果时长异常，未发送不完整歌曲")
    write_status(job, "mixing", message="正在混回伴奏并分段。")
    mixed = job / "cover.mp3"
    run([
        "ffmpeg", "-y", "-v", "error", "-i", str(converted), "-i", str(accompaniment),
        "-filter_complex", "[0:a]volume=1.2[v];[1:a]volume=0.65[b];[v][b]amix=inputs=2:duration=shortest:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11",
        "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", str(mixed),
    ])
    parts = math.ceil(seconds / 50)
    for index in range(parts):
        run(["ffmpeg", "-y", "-v", "error", "-ss", str(index * 50), "-i", str(mixed), "-t", "50", "-ar", "44100", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "128k", str(job / f"part-{index}.mp3")])
    write_status(job, "done", parts=parts, message="翻唱已完成。")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    args = parser.parse_args()
    try:
        make_cover(args.job, args.reference)
    except MusicUnavailable as exc:
        write_status(args.job, "error", message=str(exc))
        raise SystemExit(1) from None
    except Exception as exc:  # noqa: BLE001 -- 独立任务边界须保存失败状态，且不可泄露签名链接。
        # 不把可能带有签名播放链接的异常原文传回QQ或公开日志。
        print("唱歌处理失败：", type(exc).__name__, flush=True)
        write_status(args.job, "error", message="唱歌处理未完成，请稍后重试或换一首歌。", error_type=type(exc).__name__)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
