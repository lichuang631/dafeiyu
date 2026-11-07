"""通过现有管理面板安装唱歌扩展，不发送QQ消息。"""

import json
import zipfile
from pathlib import Path

import requests

runtime = Path(__file__).resolve().parents[1]
name = "astrbot_plugin_fish_singing"
archive = runtime / "downloads" / f"{name}-1.0.2.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
    for file in ("main.py", "metadata.yaml", "_conf_schema.json"):
        bundle.write(runtime / "custom-plugins" / name / file, arcname=f"{name}/{file}")
credentials = json.loads((runtime / "本机登录信息.json").read_text(encoding="utf-8-sig"))
session = requests.Session()
session.trust_env = False
base = "http://127.0.0.1:16185"
login = session.post(base + "/api/auth/login", json={"username": credentials["astrbot_username"], "password": credentials["astrbot_password"]}, timeout=15).json()
session.headers["Authorization"] = "Bearer " + login["data"]["token"]
with archive.open("rb") as handle:
    result = session.post(base + "/api/v1/plugins/install/upload", files={"file": (archive.name, handle, "application/zip")}, timeout=100).json()
print("唱歌插件：", result.get("status"), result.get("message"))
assert result.get("status") == "ok"
for plugin in session.get(base + "/api/v1/plugins", timeout=20).json()["data"]:
    if plugin.get("name") == name:
        print(json.dumps({k: plugin.get(k) for k in ("name", "version", "activated")}, ensure_ascii=False))
