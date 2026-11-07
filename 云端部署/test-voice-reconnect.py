# -*- coding: utf-8 -*-
"""在服务器上仅阻断当前专用语音连接35秒，验证失联回收和自动恢复。"""

from __future__ import print_function

import re
import signal
import subprocess
import time


def output(args):
    return subprocess.check_output(args).decode("utf-8", "replace")


def main():
    socket = "/opt/dafeiyu/data/plugin_data/astrbot_plugin_fish_hybrid_voice/tunnel/voice.sock"
    rows = [row for row in output(["/usr/sbin/ss", "-xlpnH"]).splitlines() if socket in row]
    if len(rows) != 1:
        raise RuntimeError("Expected one voice socket")
    pid = re.search(r"pid=(\d+)", rows[0]).group(1)
    owner = output(["ps", "-p", pid, "-o", "user="]).strip()
    if owner != "fishvoice":
        raise RuntimeError("Refusing to affect another account")
    connections = [row for row in output(["/usr/sbin/ss", "-ntpH"]).splitlines() if re.search(r"pid=" + pid + r"\b", row)]
    if len(connections) != 1:
        raise RuntimeError("Expected one dedicated TCP connection")
    fields = connections[0].split()
    local, peer = fields[3], fields[4]
    address, port = peer.rsplit(":", 1)
    if not local.endswith(":22") or not re.match(r"^\d+\.\d+\.\d+\.\d+$", address) or not port.isdigit():
        raise RuntimeError("Unexpected connection address")
    common = ["-m", "comment", "--comment", "fish-voice-reconnect-check", "-j", "DROP"]
    rules = [
        ["INPUT", "-p", "tcp", "-s", address, "--sport", port, "--dport", "22"] + common,
        ["OUTPUT", "-p", "tcp", "-d", address, "--dport", port, "--sport", "22"] + common,
    ]
    applied = []

    def interrupted(_signum, _frame):
        raise RuntimeError("Interrupted")

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    try:
        for rule in rules:
            subprocess.check_call(["/usr/sbin/iptables", "-I"] + rule)
            applied.append(rule)
        print("VOICE-LOSS-START", int(time.time()), "old_pid", pid)
        import sys
        sys.stdout.flush()
        time.sleep(35)
    finally:
        for rule in reversed(applied):
            subprocess.check_call(["/usr/sbin/iptables", "-D"] + rule)
        print("VOICE-LOSS-END", int(time.time()), "rules_removed", len(applied))


if __name__ == "__main__":
    main()
