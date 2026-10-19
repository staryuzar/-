"""Apply deterministic Windows portability fixes to tests in a legacy Aurora ZIP.

This adapter changes only test portability assumptions and strips UTF-8 BOMs
from the three launcher batch files. It does not modify production Python code.
It is idempotent and fails closed if the expected test structure changes.
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
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel32.WaitForSingleObject.restype = wintypes.DWORD
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.OpenProcess(0x00100000, False, result["pid"])  # SYNCHRONIZE
            self.assertTrue(handle, "could not open background process handle")
            try:
                wait_result = kernel32.WaitForSingleObject(handle, 8000)
                self.assertEqual(wait_result, 0, "background process did not exit before temporary cleanup")
            finally:
                kernel32.CloseHandle(handle)
        else:
            time.sleep(0.2)
''',
        "background-process cleanup race",
    )
    target.write_text(source, encoding="utf-8", newline="\n")

    # cmd.exe may misread the first command in a UTF-8-BOM batch file.
    for batch_name in ("START_WINDOWS.bat", "RUN_TESTS_WINDOWS.bat", "DIAGNOSE_WINDOWS.bat"):
        batch_path = root / batch_name
        if not batch_path.is_file():
            raise SystemExit(f"Expected batch file not found: {batch_path}")
        raw = batch_path.read_bytes()
        if raw.startswith(bytes((0xEF, 0xBB, 0xBF))):
            batch_path.write_bytes(raw[3:])
            print(f"Removed UTF-8 BOM from {batch_name}")
        else:
            print(f"Verified no UTF-8 BOM in {batch_name}")
    print("Applied/verified Windows portability fixes to the extracted legacy package.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
