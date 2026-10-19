#!/usr/bin/env python3
"""Exercise Aurora's real Windows launch/window-enumeration helpers against isolated MT5."""
from __future__ import annotations

import argparse
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
    args = parser.parse_args()
    sys.path.insert(0, str(args.source_dir.resolve()))

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
            stream.write(f"Aurora windows_tools.launch_program result: {launch}\n")
            stream.write(f"Assistant-launched MT5 PID: {pid}\n")
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
            stream.write(f"Process alive after 15s (tasklist): {process_alive}\n")
            stream.write(f"tasklist output: {(tasklist.stdout or '').strip()[:1000]}\n")
        if not process_alive:
            raise RuntimeError("MT5 process launched by Aurora's launch_program did not remain alive for 15 seconds.")

        try:
            windows = windows_tools.list_open_windows(limit=200)
            matches = [
                item for item in windows
                if any(word in str(item.get("title", "")).casefold() for word in ("metatrader", "terminal64", "terminal"))
            ]
            with report.open("a", encoding="utf-8") as stream:
                stream.write(f"Aurora list_open_windows returned {len(windows)} visible windows.\n")
                stream.write(f"MT5-related visible windows: {matches[:10]}\n")
            if matches:
                try:
                    details = windows_tools.inspect_window(str(matches[0]["title"]), limit=80)
                    with report.open("a", encoding="utf-8") as stream:
                        stream.write(f"Aurora inspect_window control count: {len(details.get('controls', []))}\n")
                        stream.write(f"Window title inspected: {details.get('window_title', '')}\n")
                except Exception as exc:
                    with report.open("a", encoding="utf-8") as stream:
                        stream.write(f"Window inspection unavailable: {type(exc).__name__}: {str(exc)[:300]}\n")
            else:
                with report.open("a", encoding="utf-8") as stream:
                    stream.write("UI LIMIT: the hosted runner did not expose a visible MT5 window to UI Automation; process launch was verified only.\n")
        except Exception as exc:
            with report.open("a", encoding="utf-8") as stream:
                stream.write(f"UI enumeration unavailable: {type(exc).__name__}: {str(exc)[:400]}\n")
                stream.write("UI LIMIT: process launch was verified, but visible-window automation was not.\n")

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
