#!/bin/bash
set -euo pipefail
export PATH=/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
cd /opt/dafeiyu
for attempt in $(seq 1 360); do
  if docker image inspect dafeiyu-astrbot-base:4.29.4 >/dev/null 2>&1; then break; fi
  sleep 5
done
docker image inspect dafeiyu-astrbot-base:4.29.4 >/dev/null
docker run -i --rm --name dafeiyu-setup \
  -v /opt/dafeiyu/data:/AstrBot/data \
  -v /opt/dafeiyu/downloads:/migration-downloads:ro \
  -e PYTHONPATH=/AstrBot/data/cloud_python:/AstrBot \
  --entrypoint bash dafeiyu-astrbot-base:4.29.4 -s <<'CONTAINER'
set -euo pipefail
python -m pip install --no-cache-dir --target /AstrBot/data/cloud_python \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
  'minio>=7.2.20,<8' 'argon2-cffi>=25' pysilk
for attempt in $(seq 1 360); do
  if python - <<'PY'
from pathlib import Path
import hashlib
p = Path('/migration-downloads/blue-fat-fish-meme-pack.zip')
if not p.exists() or p.stat().st_size != 482905780:
    raise SystemExit(1)
with p.open('rb') as f:
    if hashlib.file_digest(f, 'sha256').hexdigest() != 'e6472fb44640daca088ad5309e4201aae925360ecd3525418e6071d5c4bcb482':
        raise SystemExit(1)
PY
  then break; fi
  sleep 5
done
python - <<'PY'
from pathlib import Path
from data.plugins.meme_manager.backend.packs.storage import import_pack_archive
result = import_pack_archive(
    Path('/migration-downloads/blue-fat-fish-meme-pack.zip'),
    set_as_default=True,
    expected_pack_id='blue-fat-fish-meme-pack',
)
print('表情包已恢复:', result['name'])
PY
CONTAINER
bash /opt/dafeiyu/start-astrbot.sh
touch /opt/dafeiyu/astrbot-bootstrap-complete
