"""保持本地声音服务和专用 SSH 连接运行，断开后自动重试。"""

import json
import msvcrt
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "logs"
LOGS.mkdir(exist_ok=True)
SSH = str(Path(os.environ["WINDIR"]) / "System32/OpenSSH/ssh.exe")
OPTIONS = [
    SSH,
    "-T",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=10",
    "-o",
    "ServerAliveInterval=10",
    "-o",
    "ServerAliveCountMax=2",
    "-o",
    "ExitOnForwardFailure=yes",
    "-i",
    str(ROOT / "ssh/id_ed25519"),
]
SERVER = "fishvoice@203.0.113.10"
SOCKET = (
    "/opt/dafeiyu/data/plugin_data/astrbot_plugin_fish_hybrid_voice/tunnel/voice.sock"
)


def main():
    lock = (ROOT / "manager.lock").open("a+b")
    lock.seek(0)
    if lock.read(1) == b"":
        lock.write(b"0")
        lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print("本地语音管理器已经在运行。", flush=True)
        return
    service = tunnel = singing = None
    next_connection = next_service = 0
    next_singing = 0
    connection_state = "尚未连接"

    def report(message):
        print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)
    stopped = ROOT / "stop-request"
    status_path = ROOT / "status.json"
    with (
        (LOGS / "service.log").open("a", encoding="utf-8") as service_log,
        (LOGS / "connection.log").open("a", encoding="utf-8") as connection_log,
        (LOGS / "singing-engine.log").open("a", encoding="utf-8") as singing_log,
    ):
        try:
            while not stopped.exists():
                now = time.monotonic()
                if (
                    (ROOT / "trained-voice.json").exists()
                    and (service is None or service.poll() is not None)
                    and now >= next_service
                ):
                    service = subprocess.Popen(
                        [
                            str(ROOT / ".venv/Scripts/python.exe"),
                            "-u",
                            str(ROOT / "local_service.py"),
                        ],
                        cwd=ROOT,
                        stdout=service_log,
                        stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        env={**os.environ, "PYTHONUTF8": "1"},
                    )
                    next_service = now + 15
                acceleration = ROOT.parent / "singing/acceleration.json"
                enabled = False
                if acceleration.exists():
                    try:
                        enabled = bool(json.loads(acceleration.read_text(encoding="utf-8")).get("enabled"))
                    except (OSError, ValueError):
                        pass
                if enabled and (singing is None or singing.poll() is not None) and now >= next_singing:
                    try:
                        singing = subprocess.Popen(
                            [str(ROOT.parent / "singing/.venv-gpu/Scripts/python.exe"), "-u", str(ROOT.parent / "singing/engine_service.py")],
                            cwd=ROOT.parent / "singing", stdout=singing_log, stderr=subprocess.STDOUT,
                            creationflags=subprocess.CREATE_NO_WINDOW, env={**os.environ, "PYTHONUTF8": "1"},
                        )
                    except OSError:
                        report("加速环境尚未就绪，保留旧唱歌处理路径及原语音服务。")
                    next_singing = now + 10
                if (
                    tunnel is None or tunnel.poll() is not None
                ) and now >= next_connection:
                    try:
                        cleanup = subprocess.run(
                            [*OPTIONS, SERVER, "cleanup-fish-voice"],
                            check=False,
                            stdout=connection_log,
                            stderr=subprocess.STDOUT,
                            timeout=15,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                        )
                        if cleanup.returncode == 0:
                            tunnel = subprocess.Popen(
                                [
                                    *OPTIONS,
                                    "-N",
                                    "-R",
                                    SOCKET + ":127.0.0.1:19880",
                                    SERVER,
                                ],
                                stdout=connection_log,
                                stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW,
                            )
                            connection_state = "正在连接"
                            report("正在恢复专用语音连接。")
                        elif cleanup.returncode == 2:
                            connection_state = "等待服务器释放旧连接"
                            report("服务器正在释放失联的旧连接，稍后自动重试。")
                        else:
                            connection_state = f"连接未成功（{cleanup.returncode}），将自动重试"
                            report(connection_state)
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        connection_state = "连接暂不可用，将自动重试"
                        report(f"{connection_state}：{type(exc).__name__}")
                    next_connection = now + 5
                if tunnel and tunnel.poll() is None and connection_state != "已连接":
                    connection_state = "已连接"
                    report("专用语音连接已运行；模型就绪后，机器人会自动恢复本地声音。")
                status_path.write_text(
                    json.dumps(
                        {
                            "manager_pid": os.getpid(),
                            "service_pid": service.pid
                            if service and service.poll() is None
                            else None,
                            "connection_pid": tunnel.pid
                            if tunnel and tunnel.poll() is None
                            else None,
                            "model_configured": (ROOT / "trained-voice.json").exists(),
                            "connection_state": connection_state,
                            "singing_pid": singing.pid if singing and singing.poll() is None else None,
                            "updated_at": time.time(),
                        }
                    ),
                    encoding="utf-8",
                )
                time.sleep(1)
        finally:
            for child in (singing, service, tunnel):
                if child and child.poll() is None:
                    # Windows 虚拟环境启动器会创建真正的 Python 子进程，需一起停止。
                    subprocess.run(
                        [
                            str(Path(os.environ["WINDIR"]) / "System32/taskkill.exe"),
                            "/PID",
                            str(child.pid),
                            "/T",
                            "/F",
                        ],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    try:
                        child.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        child.kill()
            status_path.write_text(
                json.dumps(
                    {
                        "manager_pid": None,
                        "service_pid": None,
                        "connection_pid": None,
                        "singing_pid": None,
                        "model_configured": (ROOT / "trained-voice.json").exists(),
                        "stopped": True,
                        "updated_at": time.time(),
                    }
                ),
                encoding="utf-8",
            )
            lock.close()


if __name__ == "__main__":
    main()
