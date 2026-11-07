"""首次联网准备唱歌与分离模型；后续换声使用本机缓存。"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.chdir(ROOT / "seed-vc")
sys.path[:0] = [str(ROOT / "seed-vc"), str(ROOT.parent / "local-voice")]

from gpu_lock import gpu_lock
from inference import load_models

with gpu_lock(timeout=45):
    models = load_models(argparse.Namespace(f0_condition=True, fp16=True, checkpoint=None, config=None))
    del models
    import torch
    torch.cuda.empty_cache()

from audio_separator.separator import Separator

separator = Separator(model_file_dir=str(ROOT / "separation-models"), info_only=True)
separator.download_model_files("UVR-MDX-NET-Inst_HQ_3.onnx")
print("歌声转换和分离模型已准备，QQ点歌仍需要网络搜索音源。", flush=True)
