"""用本地识别核对试听是否漏读或重复，并保存检查结果。"""

import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "asr-tools"), str(ROOT / ".venv/Lib/site-packages")]
import numpy as np
from faster_whisper import WhisperModel
from opencc import OpenCC


def main():
    model = WhisperModel(str(ROOT / "model-cache/faster-whisper-small"), device="cpu", compute_type="int8", cpu_threads=6)
    converter = OpenCC("t2s")
    manifest = json.loads((ROOT / "preview-manifest.json").read_text(encoding="utf-8"))
    reports = []
    for entry in manifest:
        pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", entry["path"], "-f", "f32le", "-ac", "1", "-ar", "16000", "pipe:1"], capture_output=True, check=True).stdout
        segments, _ = model.transcribe(np.frombuffer(pcm,dtype=np.float32),language="zh",beam_size=5,condition_on_previous_text=False)
        text = converter.convert("".join(s.text for s in segments))
        expected = re.sub(r"[^\w]", "", entry["text"])
        actual = re.sub(r"[^\w]", "", text)
        score = difflib.SequenceMatcher(None,expected,actual).ratio()
        report = {"path":entry["path"],"expected":entry["text"],"recognized":text,"similarity":round(score,3)}
        reports.append(report)
        print(json.dumps(report,ensure_ascii=False),flush=True)
    (ROOT / "preview-checks.json").write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding="utf-8")
    if min(report["similarity"] for report in reports) < 0.75:
        raise SystemExit("试听有读音差异，启用前需要检查。")


if __name__ == "__main__":
    main()
