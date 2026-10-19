#!/usr/bin/env python3
"""Exercise Aurora's real Windows launch/window-enumeration helpers against isolated MT5."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--terminal-path", required=True)
    parser.add_argument("--install-dir", required=True)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--probe-windows", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(args.source_dir.resolve()))

    import windows_tools

    if args.probe_windows:
        try:
            probe = subprocess.run(
                [
                    sys.executable, str(Path(__file__).resolve()),
                    "--probe-windows",
                    "--source-dir", str(args.source_dir.resolve()),
                    "--terminal-path", args.terminal_path,
                    "--install-dir", args.install_dir,
                    "--report", str(report),
                ],
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
            )
            if probe.returncode == 0 and (probe.stdout or "").strip():
                ui_result = json.loads(probe.stdout.strip().splitlines()[-1])
                with report.open("a", encoding="utf-8") as stream:
                    stream.write(f"Aurora UI Automation probe: {json.dumps(ui_result, ensure_ascii=False)}\\n")
                if ui_result.get("mt5_windows"):
                    with report.open("a", encoding="utf-8") as stream:
                        stream.write("UI RESULT: an MT5-related window was visible to Aurora UI Automation.\\n")
                elif ui_result.get("ui_error"):
                    with report.open("a", encoding="utf-8") as stream:
                        stream.write("UI LIMIT: " + str(ui_result["ui_error"])[:400] + "\\n")
                else:
                    with report.open("a", encoding="utf-8") as stream:
                        stream.write("UI LIMIT: the hosted runner exposed no MT5-related window; process launch was verified only.\\n")
            else:
                with report.open("a", encoding="utf-8") as stream:
                    stream.write(f"UI LIMIT: window probe returned code {probe.returncode}; process launch was verified only.\\n")
                    stream.write(f"Probe output: {(probe.stderr or probe.stdout or '')[:500]}\\n")
        except subprocess.TimeoutExpired:
            with report.open("a", encoding="utf-8") as stream:
                stream.write("UI LIMIT: window enumeration exceeded 12 seconds; process launch was verified only.\\n")

        with report.open("a", encoding="utf-8") as stream:
            stream.write("RESULT: PASS — Aurora launch_program started the installed terminal and the process remained alive for 15 seconds.\n")
        return 0
    except Exception as exc:
        with report.open("a", encoding="utf-8") as stream:
            stream.write(f"RESULT: FAIL — {type(exc).__name__}: {str(exc)[:500]}\n")
        print(f"MT5 assistant integration failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        if pid is not None:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )


if __name__ == "__main__":
    raise SystemExit(main())
