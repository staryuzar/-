"""Apply deterministic Windows-only portability fixes to tests in the uploaded ZIP.

The archive in the repository is an older binary package. This adapter changes
only two flaky test assertions after extraction; it does not modify production
application code. It fails closed if the expected test structure changes.
"""
from __future__ import annotations

import sys
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    if old not in source:
        raise SystemExit(f"Cannot safely apply Windows test compatibility fix: {label}")
    return source.replace(old, new, 1)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python ci_windows_test_compat.py <extracted-source-dir>")
    root = Path(sys.argv[1]).resolve()
    target = root / "tests" / "test_tool_executor.py"
    if not target.is_file():
        raise SystemExit(f"Expected test file not found: {target}")

    source = target.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "import sys\nimport tempfile\nimport unittest\nfrom pathlib import Path\n",
        "import os\nimport subprocess\nimport sys\nimport tempfile\nimport time\nimport unittest\nfrom pathlib import Path\n",
        "cross-platform imports",
    )
    source = replace_once(
        source,
        'mocked.assert_called_once_with(self.workspace.parent / "Attachments")',
        'mocked.assert_called_once_with((self.workspace.parent / "Attachments").resolve())',
        "Windows canonical path comparison",
    )
    source = replace_once(
        source,
        '        self.assertGreater(result["pid"], 0)\n        self.assertTrue(Path(result["log_path"]).parent.exists())\n',
        '''        self.assertGreater(result["pid"], 0)
        self.assertTrue(Path(result["log_path"]).parent.exists())
        # On Windows, wait for the child process to close its inherited log handle
        # before TemporaryDirectory cleanup tries to unlink that file.
        if os.name == "nt":
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                try:
                    listing = subprocess.run(
                        ["tasklist", "/FI", f"PID eq {result['pid']}", "/FO", "CSV", "/NH"],
                        capture_output=True, text=True, timeout=2, check=False,
                    ).stdout
                except Exception:
                    break
                if str(result["pid"]) not in listing:
                    break
                time.sleep(0.1)
            else:
                self.fail("Background child process did not exit before temporary workspace cleanup")
        else:
            time.sleep(0.2)
''',
        "background-process cleanup race",
    )
    target.write_text(source, encoding="utf-8", newline="\n")
    print("Applied/verified Windows test portability fixes; production code was not changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
