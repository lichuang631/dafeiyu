"""提前准备中英混读资源，使语音服务启动后无需在线下载。"""

import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
data = ROOT / "model-cache/nltk_data"
data.mkdir(parents=True, exist_ok=True)
os.environ["NLTK_DATA"] = str(data)

import requests

for kind, name in (
    ("corpora", "cmudict"),
    ("taggers", "averaged_perceptron_tagger"),
    ("taggers", "averaged_perceptron_tagger_eng"),
):
    destination = data / kind
    destination.mkdir(exist_ok=True)
    archive = destination / (name + ".zip")
    if not zipfile.is_zipfile(archive):
        # 固定官方资源地址，无需关闭 NLTK 的代理安全检查。
        url = f"https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/{kind}/{name}.zip"
        response = requests.get(url, timeout=45)
        response.raise_for_status()
        archive.write_bytes(response.content)
    with zipfile.ZipFile(archive) as package:
        for item in package.infolist():
            if (
                not (destination / item.filename)
                .resolve()
                .is_relative_to(destination.resolve())
            ):
                raise ValueError("语言资源路径异常")
        package.extractall(destination)
repo = ROOT / "GPT-SoVITS"
(repo / "GPT_SoVITS/pretrained_models/fast_langdetect").mkdir(
    parents=True, exist_ok=True
)
os.chdir(repo)
sys.path[:0] = [str(repo), str(repo / "GPT_SoVITS")]
from text.LangSegmenter import LangSegmenter

print(LangSegmenter.getTexts("你好，hello。", "zh"), flush=True)
print("中英混读资源已就绪。", flush=True)
