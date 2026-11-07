"""复用机器人现有百炼听写服务，交叉核对训练短句文字。"""

import argparse
import base64
import json
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=ROOT / "data")
    parser.add_argument("--input", type=Path, default=ROOT / "data/raw/reference.wav")
    args = parser.parse_args()
    config = json.loads((ROOT.parent / "AstrBot-4.29.4/data/cmd_config.json").read_text(encoding="utf-8-sig"))
    key = next(p["api_key"] for p in config["provider"] if p.get("id") == "bailian_voice")
    transcript = json.loads((args.directory / "transcript.json").read_text(encoding="utf-8"))
    words = [w for segment in transcript for w in segment["words"]]
    groups, group = [], []
    for word in words:
        if group and (
            (word["start"] - group[-1]["end"] > 0.4 and group[-1]["end"] - group[0]["start"] > 2.3)
            or group[-1]["end"] - group[0]["start"] > 12
        ):
            groups.append(group)
            group = []
        group.append(word)
    if group:
        groups.append(group)
    with wave.open(str(args.input), "rb") as original:
        rate = original.getframerate()
        frames = original.readframes(original.getnframes())
    directory = args.directory / "reviewed-slices"
    directory.mkdir(exist_ok=True)
    entries = []
    for index, group in enumerate(groups, 1):
        start = max(0, group[0]["start"] - 0.1)
        end = group[-1]["end"] + 0.14
        if end - start < 2.3:
            continue
        path = directory / f"fish_{index:03}.wav"
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(frames[int(start * rate) * 2:int(end * rate) * 2])
        entries.append({"path": str(path), "start": start, "end": end, "duration": end-start, "first_pass": "".join(w["text"] for w in group)})

    def review(entry):
        encoded = base64.b64encode(Path(entry["path"]).read_bytes()).decode("ascii")
        response = requests.post(
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
            headers={"Authorization": "Bearer " + key},
            json={"model":"qwen3-asr-flash","input":{"messages":[{"role":"user","content":[{"audio":"data:audio/wav;base64," + encoded}]}]},"parameters":{"result_format":"message","asr_options":{"language":"zh","enable_itn":False}}},
            timeout=60,
        )
        response.raise_for_status()
        result = response.json()
        content = result["output"]["choices"][0]["message"]["content"]
        text = "".join(item.get("text", "") for item in content) if isinstance(content, list) else content
        entry["text"] = str(text).strip().replace("|", "，")
        print(f"{entry['start']:6.1f}-{entry['end']:6.1f} {entry['text']}", flush=True)
        return entry

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(review, entries))
    (args.directory / "slices-crosschecked.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("交叉听写已保存，等待校对后训练。", flush=True)


if __name__ == "__main__":
    main()
