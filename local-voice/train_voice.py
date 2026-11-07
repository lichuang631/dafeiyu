"""使用已校对短句完成特征处理和两阶段声音微调。"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
REPO = ROOT / "GPT-SoVITS"
EXP = REPO / "logs/dafeiyu_recording6"
PRETRAINED = REPO / "GPT_SoVITS/pretrained_models"


def main():
    global EXP
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=ROOT / "data")
    parser.add_argument("--experiment", default="dafeiyu_recording6")
    parser.add_argument("--gpt-only", action="store_true")
    args = parser.parse_args()
    if not args.experiment.replace("_", "").isalnum():
        raise ValueError("实验名只能包含字母、数字和下划线")
    EXP = REPO / "logs" / args.experiment
    entries = json.loads(
        (args.directory / "slices-reviewed.json").read_text(encoding="utf-8")
    )
    if len(entries) < 8:
        raise ValueError("有效短句不足，停止训练")
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "logs_s2_v2ProPlus").mkdir(exist_ok=True)
    (REPO / "SoVITS_weights_v2ProPlus").mkdir(exist_ok=True)
    (REPO / "GPT_weights_v2ProPlus").mkdir(exist_ok=True)
    listing = args.directory / "training.list"
    listing.write_text(
        "\n".join(
            f"{Path(e['path']).as_posix()}|dafeiyu|zh|{e['text']}" for e in entries
        )
        + "\n",
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "PYTHONUTF8": "1",
        "version": "v2ProPlus",
        "hz": "25hz",
        "language": "zh_CN",
        "PYTHONPATH": os.pathsep.join((str(REPO), str(REPO / "GPT_SoVITS"))),
        "_CUDA_VISIBLE_DEVICES": "0",
        "is_half": "True",
        "i_part": "0",
        "all_parts": "1",
        "inp_text": str(listing),
        "inp_wav_dir": str(Path(entries[0]["path"]).parent),
        "exp_name": args.experiment,
        "opt_dir": str(EXP),
        "bert_pretrained_dir": str(PRETRAINED / "chinese-roberta-wwm-ext-large"),
        "bert_path": str(PRETRAINED / "chinese-roberta-wwm-ext-large"),
        "cnhubert_base_dir": str(PRETRAINED / "chinese-hubert-base"),
        "pretrained_s2G": str(PRETRAINED / "v2Pro/s2Gv2ProPlus.pth"),
        "sv_path": str(PRETRAINED / "sv/pretrained_eres2netv2w24s4ep4.ckpt"),
        "s2config_path": str(REPO / "GPT_SoVITS/configs/s2v2ProPlus.json"),
        "OMP_NUM_THREADS": "4",
        "MKL_NUM_THREADS": "4",
        "USE_LIBUV": "0",
    }
    log_dir = ROOT / "logs" / args.experiment
    log_dir.mkdir(parents=True, exist_ok=True)
    steps = [
        ("text", "GPT_SoVITS/prepare_datasets/1-get-text.py"),
        ("hubert", "GPT_SoVITS/prepare_datasets/2-get-hubert-wav32k.py"),
        ("speaker", "GPT_SoVITS/prepare_datasets/2-get-sv.py"),
        ("semantic", "GPT_SoVITS/prepare_datasets/3-get-semantic.py"),
    ]
    for name, script in steps:
        if "--gpt-only" in sys.argv:
            break
        print(f"开始处理：{name}", flush=True)
        with (log_dir / f"prepare-{name}.log").open("w", encoding="utf-8") as output:
            subprocess.run(
                [sys.executable, "-u", script],
                cwd=REPO,
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
                check=True,
            )
    text = EXP / "2-name2text-0.txt"
    semantic = EXP / "6-name2semantic-0.tsv"
    if len(text.read_text(encoding="utf-8").strip().splitlines()) < len(entries) * 0.9:
        raise ValueError("文本处理出现缺失，请检查日志，停止训练")
    (EXP / "2-name2text.txt").write_text(
        text.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (EXP / "6-name2semantic.tsv").write_text(
        "item_name\tsemantic_audio\n" + semantic.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    sovits = json.loads(
        (REPO / "GPT_SoVITS/configs/s2v2ProPlus.json").read_text(encoding="utf-8")
    )
    sovits["train"].update(
        {
            "batch_size": 2,
            "epochs": 8,
            "text_low_lr_rate": 0.4,
            "pretrained_s2G": str(PRETRAINED / "v2Pro/s2Gv2ProPlus.pth"),
            "pretrained_s2D": str(PRETRAINED / "v2Pro/s2Dv2ProPlus.pth"),
            "if_save_latest": True,
            "if_save_every_weights": True,
            "save_every_epoch": 4,
            "gpu_numbers": "0",
            "grad_ckpt": True,
            "lora_rank": 32,
        }
    )
    sovits["model"]["version"] = "v2ProPlus"
    sovits["data"]["exp_dir"] = str(EXP)
    sovits.update(
        {
            "s2_ckpt_dir": str(EXP),
            "save_weight_dir": str(REPO / "SoVITS_weights_v2ProPlus"),
            "name": args.experiment,
            "version": "v2ProPlus",
        }
    )
    s2_config = args.directory / "train-s2.json"
    s2_config.write_text(
        json.dumps(sovits, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    gpt = yaml.safe_load(
        (REPO / "GPT_SoVITS/configs/s1longer-v2.yaml").read_text(encoding="utf-8")
    )
    gpt["train"].update(
        {
            "batch_size": 2,
            "epochs": 15,
            "save_every_n_epoch": 5,
            "if_save_every_weights": True,
            "if_save_latest": True,
            "if_dpo": False,
            "half_weights_save_dir": str(REPO / "GPT_weights_v2ProPlus"),
            "exp_name": args.experiment,
        }
    )
    gpt["data"]["num_workers"] = 0
    gpt.update(
        {
            "pretrained_s1": str(PRETRAINED / "s1v3.ckpt"),
            "train_semantic_path": str(EXP / "6-name2semantic.tsv"),
            "train_phoneme_path": str(EXP / "2-name2text.txt"),
            "output_dir": str(EXP / "logs_s1_v2ProPlus"),
        }
    )
    s1_config = args.directory / "train-s1.yaml"
    s1_config.write_text(yaml.safe_dump(gpt, allow_unicode=True), encoding="utf-8")
    for name, args in (
        ("sovits", ["GPT_SoVITS/s2_train.py", "--config", str(s2_config)]),
        ("gpt", ["GPT_SoVITS/s1_train.py", "--config_file", str(s1_config)]),
    ):
        if "--gpt-only" in sys.argv and name != "gpt":
            continue
        print(f"开始训练：{name}", flush=True)
        with (log_dir / f"train-{name}.log").open("w", encoding="utf-8") as output:
            subprocess.run(
                [sys.executable, "-u", *args],
                cwd=REPO,
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
                check=True,
            )
    print("两阶段训练完成，等待试听验证后启用。", flush=True)


if __name__ == "__main__":
    main()
