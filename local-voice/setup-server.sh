#!/bin/sh
set -eu
install_dir=/opt/dafeiyu/voice-tunnel
voice_data=/opt/dafeiyu/data/plugin_data/astrbot_plugin_fish_hybrid_voice
backup_dir=/opt/dafeiyu/backups/local-voice-20261107
umask 077
mkdir -p "$backup_dir" "$install_dir" "$voice_data"
cp -a /opt/dafeiyu/data/cmd_config.json "$backup_dir/cmd_config-before.json"
if ! id fishvoice >/dev/null 2>&1; then
    useradd -M -d "$install_dir" -s /bin/sh fishvoice
    usermod -p '*' fishvoice
fi
mkdir -p "$install_dir/.ssh" "$voice_data/tunnel"
chmod 755 "$install_dir" "$voice_data"
chown fishvoice:fishvoice "$voice_data/tunnel"
chmod 700 "$voice_data/tunnel"
cat > "$install_dir/session.sh" <<'SESSION'
#!/bin/sh
set -eu
socket=/opt/dafeiyu/data/plugin_data/astrbot_plugin_fish_hybrid_voice/tunnel/voice.sock
if [ "${SSH_ORIGINAL_COMMAND:-}" != "cleanup-fish-voice" ]; then
    exit 1
fi
if /usr/sbin/ss -xlH | grep -Fq -- "$socket"; then
    exit 2
fi
if [ -S "$socket" ]; then
    rm -- "$socket"
fi
SESSION
chmod 755 "$install_dir/session.sh"
printf '%s ' 'restrict,port-forwarding,permitopen="127.0.0.1:1",command="/opt/dafeiyu/voice-tunnel/session.sh"' > "$install_dir/.ssh/authorized_keys"
cat /opt/dafeiyu/voice-setup/id_ed25519.pub >> "$install_dir/.ssh/authorized_keys"
chown -R root:root "$install_dir"
chmod 755 "$install_dir/.ssh"
chmod 644 "$install_dir/.ssh/authorized_keys"
install -m 600 /opt/dafeiyu/voice-setup/bridge-token "$voice_data/bridge-token"
# 只给专用账号逐级穿过目录的权限，禁止访问现有配置和其他插件数据。
setfacl -m u:fishvoice:--x,d:u:fishvoice:--- /opt/dafeiyu /opt/dafeiyu/data /opt/dafeiyu/data/plugin_data "$voice_data"
find /opt/dafeiyu -mindepth 1 -maxdepth 1 ! -name data ! -name voice-tunnel -exec setfacl -m u:fishvoice:--- {} +
find /opt/dafeiyu/data -mindepth 1 -maxdepth 1 ! -name plugin_data -exec setfacl -m u:fishvoice:--- {} +
find /opt/dafeiyu/data/plugin_data -mindepth 1 -maxdepth 1 ! -name astrbot_plugin_fish_hybrid_voice -exec setfacl -m u:fishvoice:--- {} +
if ! grep -q '^# dafeiyu-voice-only$' /etc/ssh/sshd_config; then
    cp -a /etc/ssh/sshd_config "$backup_dir/sshd_config-before"
    cp -a /etc/ssh/sshd_config "$backup_dir/sshd_config-voice-next"
    cat >> "$backup_dir/sshd_config-voice-next" <<'SSH_CONFIG'

# dafeiyu-voice-only
Match User fishvoice
    ClientAliveInterval 10
    ClientAliveCountMax 2
    AllowTcpForwarding no
    AllowStreamLocalForwarding remote
    PermitTTY no
    ForceCommand /opt/dafeiyu/voice-tunnel/session.sh
Match all
SSH_CONFIG
    /usr/sbin/sshd -t -f "$backup_dir/sshd_config-voice-next"
    cp -a "$backup_dir/sshd_config-voice-next" /etc/ssh/sshd_config
    systemctl reload sshd
fi
if ! /usr/sbin/sshd -T -C user=fishvoice,host=localhost,addr=127.0.0.1 | grep -q '^clientaliveinterval 10$'; then
    cp -a /etc/ssh/sshd_config "$backup_dir/sshd_config-before-reconnect"
    python - <<'RECONNECT_CONFIG'
p = '/etc/ssh/sshd_config'
with open(p) as source:
    config = source.read()
config = config.replace('Match User fishvoice\n', 'Match User fishvoice\n    ClientAliveInterval 10\n    ClientAliveCountMax 2\n')
with open(p, 'w') as target:
    target.write(config)
RECONNECT_CONFIG
    if /usr/sbin/sshd -t; then
        systemctl reload sshd
    else
        cp -a "$backup_dir/sshd_config-before-reconnect" /etc/ssh/sshd_config
        exit 1
    fi
fi
printf '%s\n' '专用语音连接已配置，仅使用本机地址和专用 Unix socket。'
