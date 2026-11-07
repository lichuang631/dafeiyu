"""通过已认证管理连接安装语音自动回退插件，或测试原语音提供商。"""

import json
import sys
import zipfile
from pathlib import Path

import requests

runtime = Path(__file__).resolve().parents[1]
name = "astrbot_plugin_fish_hybrid_voice"
credentials = json.loads(
    (runtime / "本机登录信息.json").read_text(encoding="utf-8-sig")
)
session = requests.Session()
session.trust_env = False
base = "http://127.0.0.1:16185"
response = session.post(
    base + "/api/auth/login",
    json={
        "username": credentials["astrbot_username"],
        "password": credentials["astrbot_password"],
    },
    timeout=15,
).json()
session.headers["Authorization"] = "Bearer " + response["data"]["token"]
if "--test" in sys.argv:
    response = session.post(
        base + "/api/v1/providers/bailian_voice/test", timeout=70
    ).json()
    print(json.dumps(response, ensure_ascii=False))
    raise SystemExit(0 if response.get("data", {}).get("status") == "available" else 1)
archive = runtime / "downloads" / f"{name}-1.0.1.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
    for item in ("main.py", "hybrid.py", "metadata.yaml", "_conf_schema.json"):
        bundle.write(runtime / "custom-plugins" / name / item, arcname=f"{name}/{item}")
with archive.open("rb") as handle:
    response = session.post(
        base + "/api/v1/plugins/install/upload",
        files={"file": (archive.name, handle, "application/zip")},
        timeout=100,
    ).json()
print("语音插件安装：", response.get("status"), response.get("message"), flush=True)
assert response.get("status") == "ok"
plugins = session.get(base + "/api/v1/plugins", timeout=20).json()["data"]
for plugin in plugins:
    if plugin.get("name") == name:
        print(
            json.dumps(
                {key: plugin.get(key) for key in ("name", "version", "activated")},
                ensure_ascii=False,
            )
        )
