#!/usr/bin/env python3
"""Exercise Aurora's real Windows launch/window-enumeration helpers against isolated MT5."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def collect_windows() -> dict:
    import windows_tools

    windows = windows_tools.list_open_windows(limit=200)
    matches = [
        item for item in windows
        if any(word in str(item.get("title", "")).casefold() for word in ("metatrader", "terminal64", "terminal"))
    ]
    details = None
    if matches:
        try:
            details = windows_tools.inspect_window(str(matches[0]["title"]), limit=80)
        except Exception as exc:
            details = {"inspection_error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    return {"visible_window_count": len(windows), "mt5_windows": matches[:10], "inspection": details}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--terminal-path", required=True)
    parser.add_argument("--install-dir", required=True)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--probe-windows", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(args.source_dir.resolve()))

    if args.probe_windows:
        try:
            print(json.dumps(collect_windows(), ensure_ascii=False))
        except Exception as exc:
            print(json.dumps({"ui_error": f"{type(exc).__name__}: {str(exc)[:400]}"}, ensure_ascii=False))
        return 0

    import windows_tools

    report = args.report
    pid = None
    try:
        launch = windows_tools.launch_program(
            args.terminal_path,
            arguments=["/portable"],
            cwd=args.install_dir,
        )
        pid = int(launch["pid"])
        with report.open("a", encoding="utf-8") as stream:
            stream.write(f"Aurora windows_tools.launch_program result: {launch}\\n")
            stream.write(f"Assistant-launched MT5 PID: {pid}\\n")
        time.sleep(15)

        tasklist = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        process_alive = str(pid) in (tasklist.stdout or "")
        with report.open("a", encoding="utf-8") as stream:
            stream.write(f"Process alive after 15s (tasklist): {process_alive}\\n")
            stream.write(f"tasklist output: {(tasklist.stdout or '').strip()[:1000]}\\n")
        if not process_alive:
            raise RuntimeError("MT5 process launched by Aurora's launch_program did not remain alive for 15 seconds.")

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
            stream.write("RESULT: PASS — Aurora launch_program started the installed terminal and the process remained alive for 15 seconds.\\n")
        return 0
    except Exception as exc:
        with report.open("a", encoding="utf-8") as stream:
            stream.write(f"RESULT: FAIL — {type(exc).__name__}: {str(exc)[:500]}\\n")
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
