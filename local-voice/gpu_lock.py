"""让唱歌与说话错开显卡计算，忙碌时语音使用原有云端备用。"""

import msvcrt
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def gpu_lock(timeout=2):
    with (Path(__file__).resolve().parent / "gpu.lock").open("a+b") as handle:
        if handle.seek(0, 2) == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("显卡正在处理另一项语音任务") from None
                time.sleep(0.1)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
