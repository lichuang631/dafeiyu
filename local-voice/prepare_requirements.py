"""保持官方依赖要求，在 Windows 使用兼容的繁简转换实现。"""

from pathlib import Path

root = Path(__file__).resolve().parent
lines = (root / "GPT-SoVITS/requirements.txt").read_text(encoding="utf-8").splitlines()
lines = [line for line in lines if line.strip() not in ("--no-binary=opencc", "opencc") and not line.strip().startswith("onnxruntime")]
lines.append("opencc-python-reimplemented==0.1.7")
lines.append("onnxruntime==1.22.1")
lines.append("resampy==0.4.3")
(root / "requirements-windows.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
