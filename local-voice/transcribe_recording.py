"""本地识别录音，并依据词时间戳生成短句训练集。"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "asr-tools"))
os.environ["HF_HOME"] = str(ROOT / "model-cache")
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["PYTHONUTF8"] = "1"

from faster_whisper import WhisperModel
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=ROOT / "data")
    parser.add_argument("--input", type=Path, default=ROOT / "data/raw/reference.wav")
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    model = WhisperModel(str(ROOT / "model-cache/faster-whisper-small"), device="cpu", compute_type="int8", cpu_threads=6)
    decoded = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(args.input), "-f", "f32le", "-ac", "1", "-ar", "16000", "pipe:1"],
        check=True, capture_output=True,
    ).stdout
    segments, info = model.transcribe(
        np.frombuffer(decoded, dtype=np.float32),
        language="zh", beam_size=5, word_timestamps=True, vad_filter=True,
        condition_on_previous_text=False,
    )
    transcript = []
    for segment in segments:
        transcript.append({
            "start": segment.start, "end": segment.end, "text": segment.text,
            "words": [{"start": w.start, "end": w.end, "text": w.word} for w in segment.words],
        })
        print(f"{segment.start:6.1f}-{segment.end:6.1f} {segment.text}", flush=True)
    (args.directory / "transcript.json").write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
    words = [word for segment in transcript for word in segment["words"]]
    groups, group = [], []
    for word in words:
        group.append(word)
        duration = group[-1]["end"] - group[0]["start"]
        if duration >= 9 or (duration >= 3 and word["text"].strip().endswith(("。", "！", "？", ".", "!", "?", "，", ","))):
            groups.append(group)
            group = []
    if group:
        if groups and group[-1]["end"] - group[0]["start"] < 2.5:
            groups[-1].extend(group)
        else:
            groups.append(group)
    destination = args.directory / "slices"
    destination.mkdir(parents=True, exist_ok=True)
    with wave.open(str(args.input), "rb") as source:
        rate = source.getframerate()
        frames = source.readframes(source.getnframes())
        total = len(frames) / 2 / rate
    manifest = []
    for index, items in enumerate(groups, 1):
        start = max(0, items[0]["start"] - 0.12)
        end = min(total, items[-1]["end"] + 0.18)
        text = "".join(item["text"] for item in items).strip().replace("|", "，")
        if end - start < 2.0 or not text:
            continue
        path = destination / f"fish_{index:03}.wav"
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(frames[int(start * rate) * 2:int(end * rate) * 2])
        manifest.append({"path": str(path), "text": text, "start": start, "end": end, "duration": end-start})
    (args.directory / "slices.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.directory / "recording-info.json").write_text(json.dumps({"duration": total,"input":str(args.input),"sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),"asr_model":"faster-whisper-small","slice_count": len(manifest),"language_probability": info.language_probability}, indent=2), encoding="utf-8")
    print(f"已准备 {len(manifest)} 个短句，待校对后写入训练清单。", flush=True)


if __name__ == "__main__":
    main()
