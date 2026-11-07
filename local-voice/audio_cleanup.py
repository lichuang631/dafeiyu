"""用本机神经降噪清理合成尾噪；不连接外部语音服务。"""

import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parent


def clean_generated_audio(audio, rate):
    normalized = audio.astype(np.float32)
    if np.issubdtype(audio.dtype, np.integer):
        normalized /= 32768
    temporary_root = ROOT / "runtime-temp"
    temporary_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fish-clean-", dir=temporary_root) as folder:
        path = Path(folder)
        source = path / "speech.wav"
        sf.write(source, resample_poly(normalized, 48000, rate), 48000, subtype="PCM_16")
        subprocess.run(
            [str(ROOT / "denoise/deep-filter.exe"), "-D", "-a", "30", "-o", str(path / "clean"), str(source)],
            check=True, capture_output=True, timeout=12,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        enhanced, enhanced_rate = sf.read(path / "clean/speech.wav", dtype="float32")
    result = resample_poly(enhanced, rate, enhanced_rate).astype(np.float32)
    # 降噪工具的延迟补偿会裁去约30毫秒，短招呼也按固定时长校验。
    if result.size < normalized.size - int(rate * 0.06) or result.size == 0 or np.max(np.abs(result)) < 0.005:
        raise ValueError("降噪结果为空或严重不完整")
    return np.clip(result[:len(normalized)], -1, 1)
