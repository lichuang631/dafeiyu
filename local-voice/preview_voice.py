"""只使用本次训练产出的权重生成试听，验证后再写入启用配置。"""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT / "GPT-SoVITS"
os.chdir(REPO)
sys.path[:0] = [str(REPO), str(REPO / "GPT_SoVITS")]
os.environ.update(
    {
        "version": "v2ProPlus",
        "language": "zh_CN",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }
)
os.environ["NLTK_DATA"] = str(ROOT / "model-cache/nltk_data")

import numpy as np
import soundfile as sf
import yaml
from audio_cleanup import clean_generated_audio
from TTS_infer_pack.TTS import TTS, TTS_Config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gpt-epoch", type=int, choices=(5, 10, 15), default=15)
    parser.add_argument("--experiment", default="dafeiyu_recording6")
    parser.add_argument("--directory", type=Path, default=ROOT / "data")
    parser.add_argument("--output", type=Path, default=ROOT)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--denoise-generated", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    gpt = REPO / f"GPT_weights_v2ProPlus/{args.experiment}-e{args.gpt_epoch}.ckpt"
    candidates = list(
        (REPO / "SoVITS_weights_v2ProPlus").glob(f"{args.experiment}_e8_s*.pth")
    )
    if not gpt.exists() or not candidates:
        raise FileNotFoundError("本次训练的最终权重尚未生成")
    sovits = max(candidates, key=lambda p: p.stat().st_mtime)
    original = REPO / "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth"
    if (
        hashlib.sha256(sovits.read_bytes()).digest()
        == hashlib.sha256(original.read_bytes()).digest()
    ):
        raise ValueError("训练产物与基础权重相同，不能当作已训练声音")
    config = {
        "custom": {
            "device": "cuda",
            "is_half": True,
            "version": "v2ProPlus",
            "t2s_weights_path": gpt.as_posix(),
            "vits_weights_path": sovits.as_posix(),
            "bert_base_path": (
                REPO / "GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large"
            ).as_posix(),
            "cnhuhbert_base_path": (
                REPO / "GPT_SoVITS/pretrained_models/chinese-hubert-base"
            ).as_posix(),
        }
    }
    config_path = args.output / "tts-infer.yaml"
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    entries = json.loads(
        (args.directory / "slices-reviewed.json").read_text(encoding="utf-8")
    )
    reference = min(entries, key=lambda item: abs(item["start"] - 122.3))
    if args.reference:
        reference = next(e for e in entries if Path(e["path"]).resolve() == args.reference.resolve())
    settings = {
        "config_path": str(config_path),
        "reference_audio": reference["path"],
        "reference_text": reference["text"],
        "gpt_checkpoint": str(gpt),
        "sovits_checkpoint": str(sovits),
        "denoise_generated": args.denoise_generated,
        "experiment": args.experiment,
    }
    (args.output / "voice-settings-preview.json").write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    engine = TTS(TTS_Config(str(config_path)))
    directory = args.output / "试听"
    directory.mkdir(exist_ok=True)
    texts = (
        ("01-日常聊天", "主人，我是大肥鱼。今天也在等你聊天，忙完了就来找我呀。"),
        ("02-慵懒聊天", "嗯？又在偷偷摸鱼呀。那就休息一小会儿，我陪着你。"),
        ("03-轻松聊天", "哎呀，被你发现啦！刚才只是发了会儿呆，现在精神多了。"),
    )
    manifest = []
    for name, text in texts:
        started = time.monotonic()
        request = {
            "text": text,
            "text_lang": "zh",
            "ref_audio_path": reference["path"],
            "prompt_text": reference["text"],
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
        rate = pieces[0][0]
        audio = np.concatenate([piece[1] for piece in pieces])
        normalized = (
            audio.astype(np.float32) / 32768
            if np.issubdtype(audio.dtype, np.integer)
            else audio
        )
        if len(audio) / rate < len(text) * 0.06 or np.max(np.abs(normalized)) < 0.01:
            raise ValueError("试听音频为空、过短或近乎静音")
        if args.denoise_generated:
            sf.write(directory / (name + "-降噪前.wav"), audio, rate, subtype="PCM_16")
            audio = clean_generated_audio(audio, rate)
        path = directory / (name + ".wav")
        sf.write(path, audio, rate, subtype="PCM_16")
        manifest.append(
            {
                "path": str(path),
                "text": text,
                "seconds": round(len(audio) / rate, 2),
                "generation_seconds": round(time.monotonic() - started, 2),
                "peak": float(np.max(np.abs(audio.astype(np.float32))))
                / (32768 if np.issubdtype(audio.dtype, np.integer) else 1),
                "denoise_generated": args.denoise_generated,
            }
        )
        print("试听完成：", json.dumps(manifest[-1], ensure_ascii=False), flush=True)
    (args.output / "preview-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("试听生成完成，尚未启用到QQ。", flush=True)


if __name__ == "__main__":
    main()
