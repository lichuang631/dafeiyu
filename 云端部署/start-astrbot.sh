#!/bin/bash
set -euo pipefail
export PATH=/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
docker start dafeiyu-astrbot 2>/dev/null && exit 0
docker network inspect dafeiyu >/dev/null 2>&1 || docker network create dafeiyu
docker run -d --name dafeiyu-astrbot --hostname dafeiyu-astrbot \
  --restart unless-stopped --network dafeiyu --network-alias astrbot \
  --security-opt no-new-privileges:true \
  --memory-swappiness 60 --memory 700m --memory-swap 1800m --pids-limit 512 \
  -p 127.0.0.1:6185:6185 \
  -e TZ=Asia/Shanghai -e PYTHONUNBUFFERED=1 \
  -e PYTHONPATH=/AstrBot/data/cloud_python:/AstrBot \
  -v /opt/dafeiyu/data:/AstrBot/data \
  -v /opt/dafeiyu/napcat/qq:/app/.config/QQ:ro \
  dafeiyu-astrbot-base:4.29.4
