from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_http(url: str, process: subprocess.Popen[bytes], timeout: float) -> int | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return None
        try:
            with urlopen(url, timeout=2.0) as response:
                return int(response.status)
        except (URLError, TimeoutError, OSError):
            time.sleep(0.35)
    return None


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    dashboard = project / "dashboard.py"
    if not dashboard.is_file():
        raise SystemExit(f"Dashboard source is missing: {dashboard}")

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="mirsad-dashboard-smoke-") as temp:
        root = Path(temp)
        data_dir = root / "data"
        data_dir.mkdir()
        log_path = root / "streamlit.log"
        env = os.environ.copy()
        env["MIRSAD_DATA_DIR"] = str(data_dir)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(project), env.get("PYTHONPATH", "")]
        ).rstrip(os.pathsep)
        command = [
            sys.executable, "-m", "streamlit", "run", str(dashboard),
            "--server.headless=true", "--server.address=127.0.0.1",
            f"--server.port={port}", "--browser.gatherUsageStats=false",
        ]
        with log_path.open("w", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                command, cwd=str(project), env=env,
                stdout=log_file, stderr=subprocess.STDOUT,
            )
            try:
                health = wait_for_http(base + "/_stcore/health", process, 40.0)
                page = wait_for_http(base + "/", process, 15.0) if health == 200 else None
                if health != 200 or page != 200 or process.poll() is not None:
                    log_file.flush()
                    tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]
                    print("\n".join(tail))
                    raise SystemExit(
                        f"Dashboard smoke test failed: health={health}, "
                        f"root={page}, exit={process.poll()}."
                    )
                print(json.dumps({
                    "status": "PASS",
                    "health_endpoint_http": health,
                    "root_page_http": page,
                    "isolated_data_directory": str(data_dir),
                    "broker_orders_sent": False,
                }, ensure_ascii=False, indent=2))
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
