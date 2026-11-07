"""使用与基础模型一致的网络连接下载中文处理及识别模型。"""

import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

import download_models

ROOT = Path(__file__).resolve().parent


def download_asr():
    download_models.ROOT = ROOT / "model-cache/faster-whisper-small"
    download_models.REPO = "Systran/faster-whisper-small"
    result = requests.get("https://huggingface.co/api/models/Systran/faster-whisper-small/tree/main", timeout=30)
    result.raise_for_status()
    selected = [item for item in result.json() if Path(item["path"]).name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(download_models.download, selected))


def download_g2pw():
    archive = ROOT / "G2PWModel.zip"
    if not zipfile.is_zipfile(archive):
        url = "https://www.modelscope.cn/models/kamiorinn/g2pw/resolve/master/G2PWModel_1.1.zip"
        with requests.get(url, stream=True, timeout=(20, 90)) as result:
            result.raise_for_status()
            with archive.open("wb") as output:
                for chunk in result.iter_content(1024 * 1024):
                    output.write(chunk)
    target = ROOT / "GPT-SoVITS/GPT_SoVITS/text"
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            destination = (target / item.filename).resolve()
            if not destination.is_relative_to(target.resolve()):
                raise ValueError("压缩包路径超出模型目录")
        bundle.extractall(target)
    extracted = target / "G2PWModel_1.1"
    if extracted.is_dir() and not (target / "G2PWModel").exists():
        extracted.rename(target / "G2PWModel")
    print("中文多音字模型已就绪。", flush=True)


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(download_g2pw), executor.submit(download_asr)]
        for future in futures:
            future.result()
