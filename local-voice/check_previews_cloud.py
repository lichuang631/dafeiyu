"""用机器人现有听写服务独立核对最终试听的发音内容。"""

import argparse
import base64
import difflib
import json
import re
from pathlib import Path

import requests

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--directory", type=Path, default=root)
args = parser.parse_args()
config = json.loads((root.parent / "AstrBot-4.29.4/data/cmd_config.json").read_text(encoding="utf-8-sig"))
key = next(p["api_key"] for p in config["provider"] if p.get("id") == "bailian_voice")
manifest = json.loads((args.directory / "preview-manifest.json").read_text(encoding="utf-8"))
reports = []
for entry in manifest:
    encoded = base64.b64encode(Path(entry["path"]).read_bytes()).decode("ascii")
    response = requests.post(
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        headers={"Authorization":"Bearer " + key},
        json={"model":"qwen3-asr-flash","input":{"messages":[{"role":"user","content":[{"audio":"data:audio/wav;base64," + encoded}]}]},"parameters":{"result_format":"message","asr_options":{"language":"zh","enable_itn":False}}},
        timeout=45,
    )
    response.raise_for_status()
    items = response.json()["output"]["choices"][0]["message"]["content"]
    text = "".join(i.get("text", "") for i in items) if isinstance(items,list) else str(items)
    expected = re.sub(r"[^\w]", "", entry["text"])
    actual = re.sub(r"[^\w]", "", text)
    report = {"expected":entry["text"],"recognized":text,"similarity":round(difflib.SequenceMatcher(None,expected,actual).ratio(),3)}
    reports.append(report)
    print(json.dumps(report,ensure_ascii=False),flush=True)
(args.directory / "preview-checks-independent.json").write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding="utf-8")
