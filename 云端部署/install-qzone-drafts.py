"""打包配套插件，经已认证的管理隧道安装到云端。"""

import json
import zipfile
from pathlib import Path

import requests

runtime = Path(__file__).resolve().parents[1]
plugin_name = "astrbot_plugin_fish_qzone_drafts"
plugin_dir = runtime / "custom-plugins" / plugin_name
archive = runtime / "downloads" / f"{plugin_name}-1.2.3.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
    for name in ("main.py", "pictures.py", "contribution.py", "review.py", "metadata.yaml", "_conf_schema.json"):
        bundle.write(plugin_dir / name, arcname=f"{plugin_name}/{name}")

credentials = json.loads((runtime / "本机登录信息.json").read_text(encoding="utf-8-sig"))
session = requests.Session()
session.trust_env = False
base = "http://127.0.0.1:16185"
login = session.post(
    base + "/api/auth/login",
    json={"username": credentials["astrbot_username"], "password": credentials["astrbot_password"]},
    timeout=15,
).json()
session.headers["Authorization"] = "Bearer " + login["data"]["token"]

# 先重载基础空间插件，使关闭投稿人署名的配置生效。
reload_result = session.post(
    base + "/api/v1/plugins/reload", json={"plugin_id": "astrbot_plugin_qzone_ultra"}, timeout=60
).json()
print("基础空间插件：", reload_result.get("status"), reload_result.get("message"), flush=True)
assert reload_result.get("status") == "ok", "空间插件重载失败，停止安装"

with archive.open("rb") as handle:
    result = session.post(
        base + "/api/v1/plugins/install/upload",
        files={"file": (archive.name, handle, "application/zip")},
        timeout=120,
    ).json()
print("草稿插件安装：", result.get("status"), result.get("message"), flush=True)
assert result.get("status") == "ok", "草稿插件未安装成功，请检查日志"

permission_result = session.patch(
    base + "/api/v1/tools/fish_qzone_drafts/permission", json={"permission": "admin"}, timeout=20
).json()
assert permission_result.get("status") == "ok", "请检查草稿工具的主人权限设置"

plugins = session.get(base + "/api/v1/plugins", timeout=20).json()["data"]
for plugin in plugins:
    if plugin.get("name") in (plugin_name, "astrbot_plugin_qzone_ultra"):
        print(json.dumps({key: plugin.get(key) for key in ("name", "version", "activated")}, ensure_ascii=False))

status = session.get(base + "/api/v1/plugins/extensions/astrbot_plugin_qzone_ultra/page/status", timeout=25).json()
print("空间登录状态：", json.dumps(status.get("data", {}).get("login", {}), ensure_ascii=False))
