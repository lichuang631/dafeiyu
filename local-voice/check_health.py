"""等待本地声音就绪，并验证接口需要请求凭据。"""

import time
from pathlib import Path

import requests

root = Path(__file__).resolve().parent
token = (root / "bridge-token").read_text(encoding="utf-8").strip()
session = requests.Session()
session.trust_env = False
for attempt in range(35):
    try:
        response = session.get(
            "http://127.0.0.1:19880/health",
            headers={"Authorization": "Bearer " + token},
            timeout=2,
        )
        response.raise_for_status()
        body = response.json()
        assert body.get("ready") is True
        assert (
            session.get("http://127.0.0.1:19880/health", timeout=2).status_code == 401
        )
        print("本地模型已就绪，未授权请求已拒绝。", flush=True)
        break
    except (requests.RequestException, AssertionError):
        if attempt == 34:
            raise
        time.sleep(1)
