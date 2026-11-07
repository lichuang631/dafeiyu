"""只使用有效的第六、八份素材，建立独立的净化训练集。"""

import json
import subprocess
from pathlib import Path

import soundfile as sf

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DEST = DATA / "clean68"


def main():
    DEST.mkdir(exist_ok=True)
    raw = DEST / "recording6_48.wav"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(DATA / "raw/reference.mp3"),
        "-ac", "1", "-ar", "48000", str(raw),
    ], check=True)
    subprocess.run([
        str(ROOT / "denoise/deep-filter.exe"), "-D", "-o", str(DEST / "enhanced"), str(raw),
    ], check=True)
    cleaned = DEST / "recording6.wav"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(DEST / "enhanced" / raw.name),
        "-ar", "32000", str(cleaned),
    ], check=True)
    sources = [
        (6, cleaned, json.loads((DATA / "slices-reviewed.json").read_text(encoding="utf-8"))),
        (8, DATA / "recording8/reference.wav", [
            e for i, e in enumerate(json.loads((DATA / "recording8/slices-crosschecked.json").read_text(encoding="utf-8")))
            if i in (1, 3, 5, 6, 10, 13, 16, 18)
        ]),
    ]
    slices = DEST / "slices"
    slices.mkdir(exist_ok=True)
    manifest = []
    for recording, path, entries in sources:
        audio, rate = sf.read(path)
        for i, entry in enumerate(entries, 1):
            clip = audio[int(entry["start"] * rate):int(entry["end"] * rate)]
            output = slices / f"recording{recording}_{i:03}.wav"
            sf.write(output, clip, rate, subtype="PCM_16")
            manifest.append({**entry, "path": str(output), "recording": recording, "duration": len(clip) / rate})
    (DEST / "slices-reviewed.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("有效素材：第6、第8份；第7份已排除。", flush=True)
    print("短句数：", len(manifest), "总秒数：", round(sum(e["duration"] for e in manifest), 1), flush=True)


if __name__ == "__main__":
    main()
