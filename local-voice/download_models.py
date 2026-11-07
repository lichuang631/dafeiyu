"""从官方权重仓库下载训练所需文件，并核对 LFS 校验值。"""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent / "GPT-SoVITS/GPT_SoVITS/pretrained_models"
REPO = "lj1995/GPT-SoVITS"
SELECTED = {
    "v2Pro/s2Gv2ProPlus.pth",
    "v2Pro/s2Dv2ProPlus.pth",
    "s1v3.ckpt",
    "sv/pretrained_eres2netv2w24s4ep4.ckpt",
}


def download(item):
    relative = item["path"]
    path = ROOT / relative
    expected = item.get("lfs", {}).get("oid")
    if path.exists() and path.stat().st_size == item["size"]:
        if not expected or hashlib.sha256(path.read_bytes()).hexdigest() == expected:
            print(f"已就绪：{relative}", flush=True)
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    url = f"https://huggingface.co/{REPO}/resolve/main/{relative}"
    for attempt in range(3):
        try:
            with requests.get(url, stream=True, timeout=(20, 90)) as response:
                response.raise_for_status()
                digest = hashlib.sha256()
                with temporary.open("wb") as output:
                    for block in response.iter_content(1024 * 1024):
                        digest.update(block)
                        output.write(block)
            if temporary.stat().st_size != item["size"]:
                raise ValueError("文件长度不符")
            if expected and digest.hexdigest() != expected:
                raise ValueError("文件校验值不符")
            temporary.replace(path)
            print(f"已下载：{relative} ({item['size'] // 1024 // 1024} MiB)", flush=True)
            return
        except Exception:
            if attempt == 2:
                raise


def main():
    files = []
    for subdir in ("", "v2Pro", "sv", "chinese-hubert-base", "chinese-roberta-wwm-ext-large"):
        result = requests.get(
            f"https://huggingface.co/api/models/{REPO}/tree/main/{subdir}",
            timeout=30,
        )
        result.raise_for_status()
        for item in result.json():
            name = item["path"]
            if item["type"] != "file":
                continue
            if name in SELECTED or (
                subdir in ("chinese-hubert-base", "chinese-roberta-wwm-ext-large")
                and not name.endswith((".bin.index.json", ".h5", ".msgpack", ".md"))
                and Path(name).name != ".gitattributes"
            ):
                files.append(item)
    (ROOT.parent.parent.parent / "model-manifest.json").write_text(
        json.dumps(files, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"下载 {len(files)} 个文件，共 {sum(x['size'] for x in files) / 1024**3:.2f} GiB", flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(download, files))


if __name__ == "__main__":
    main()
