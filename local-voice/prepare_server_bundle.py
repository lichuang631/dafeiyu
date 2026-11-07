"""打包连接配置，只包含公钥和随机请求凭据，不包含本机私钥。"""

import secrets
import tarfile
from pathlib import Path

root = Path(__file__).resolve().parent
token = root / "bridge-token"
if not token.exists():
    token.write_text(secrets.token_urlsafe(32), encoding="utf-8")
with tarfile.open(root / "server-setup.tar.gz", "w:gz") as bundle:
    for path in (token, root / "setup-server.sh", root / "ssh/id_ed25519.pub"):
        bundle.add(path, arcname=path.name)
print("已准备语音连接安装包，私钥留在本机。")
