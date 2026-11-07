#!/bin/bash
set -euo pipefail
export PATH=/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
docker start dafeiyu-napcat 2>/dev/null && exit 0
docker network inspect dafeiyu >/dev/null 2>&1 || docker network create dafeiyu
mkdir -p /opt/dafeiyu/napcat/qq /opt/dafeiyu/napcat/plugins
docker run -d --name dafeiyu-napcat --hostname dafeiyu-qq \
  --restart unless-stopped --network dafeiyu \
  --security-opt no-new-privileges:true \
  --memory-swappiness 60 --memory 700m --memory-swap 1800m --pids-limit 512 \
  -p 127.0.0.1:6099:6099 \
  -e TZ=Asia/Shanghai -e ACCOUNT=100000002 \
  -e NAPCAT_UID=0 -e NAPCAT_GID=0 \
  -v /opt/dafeiyu/napcat/qq:/app/.config/QQ \
  -v /opt/dafeiyu/napcat/config:/app/napcat/config \
  -v /opt/dafeiyu/napcat/plugins:/app/napcat/plugins \
  -v /opt/dafeiyu/data:/AstrBot/data \
  dafeiyu-napcat:4.18.42
