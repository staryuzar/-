#!/usr/bin/env python3
"""Compare matched TV26 exit-on / exit-off MT5 Strategy Tester arms."""
from pathlib import Path
import re
import sys

ROOT = Path.cwd()
ARMS = {
    "on": ROOT / "tv26-exit-a-on",
    "off": ROOT / "tv26-exit-b-off",
}
EXPECTED = {
    "on": ("26102481", "true"),
    "off": ("26102482", "false"),
}
METRICS = {
    "Net profit": "Total Net Profit:",
    "Profit factor": "Profit Factor:",
    "Equity DD max": "Equity Drawdown Maximal:",
    "Total trades": "Total Trades:",
    "Winning trades": "Profit Trades (% of total):",
    "Losing trades": "Loss Trades (% of total):",
    "Expected payoff": "Expected Payoff:",
}


def metric(html: str, label: str) -> str:
    pattern = r"(?is)<td[^>]*>\s*" + re.escape(label) + r"\s*</td>\s*<td[^>]*>\s*<b>(.*?)</b>"
    m = re.search(pattern, html)
    return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else "NOT FOUND"


def first_number(value: str):
    m = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", value.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None



def event_key(line: str):
    """Stable identity for an exit trigger/close event; refuses incomplete logs."""
    ticket = re.search(r"ticket=(\\d+)", line)
    reason = re.search(r"reason=([^;]+)", line)
    bar = re.search(r"bar=([^;]+)", line)
    if not ticket or not reason or not bar:
        return None
    return (ticket.group(1), reason.group(1), bar.group(1))


def read_arm(key: str) -> dict:
    folder = ARMS[key]
    summary_path = folder / "strategy-backtest-summary.txt"
    html_path = folder / "strategy-tester-report.html"
    audit_path = folder / "formula-parity-report.md"
    integrity_path = folder / "data-integrity-report.md"
    for path in (summary_path, html_path, audit_path, integrity_path):
        if not path.exists():
            raise RuntimeError(f"{key} arm missing required output: {path}")
    summary = summary_path.read_text(encoding="utf-8", errors="replace")
    html = html_path.read_text(encoding="utf-8", errors="replace")
    source = re.search(r"Source SHA-256:\s*([a-f0-9]{64})", summary, re.I)
    history = re.search(r"Reference OHLCV SHA-256:\s*([a-f0-9]{64})", summary, re.I)
    magic, early = EXPECTED[key]
    if not source or not history:
        raise RuntimeError(f"{key} arm is missing source/history hashes")
    if not re.search(r"(?is)InpMagic=" + re.escape(magic) + r"</b>", html):
        raise RuntimeError(f"{key} arm report does not prove expected magic {magic}")
    if not re.search(r"(?is)InpUseRuleBasedEarlyExit=" + re.escape(early) + r"</b>", html):
        raise RuntimeError(f"{key} arm report does not prove early-exit setting={early}")
    if "PASS" not in audit_path.read_text(encoding="utf-8", errors="replace"):
        raise RuntimeError(f"{key} formula audit did not pass")
    if "PASS" not in integrity_path.read_text(encoding="utf-8", errors="replace"):
        raise RuntimeError(f"{key} integrity audit did not pass")
    metrics = {name: metric(html, label) for name, label in METRICS.items()}
    event_set = set()
    for log_root in (folder / "diagnostic-logs", folder / "diagnostics"):
        if log_root.exists():
            for p in log_root.glob("*.txt"):
                for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                    for marker in ("TV26_EXIT_TRIGGER;", "TV26_EXIT_COMPLETED;", "TV26_EXIT_FAILED;"):
                        idx = line.find(marker)
                        if idx >= 0:
                            event_set.add(line[idx:].strip())
                            break
    triggers = sorted(x for x in event_set if x.startswith("TV26_EXIT_TRIGGER;"))
    completed = sorted(x for x in event_set if x.startswith("TV26_EXIT_COMPLETED;"))
    failed = sorted(x for x in event_set if x.startswith("TV26_EXIT_FAILED;"))
    trigger_keys = [event_key(x) for x in triggers]
    done_keys = {key for x in completed if (key := event_key(x)) is not None}
    paired = sum(1 for key in trigger_keys if key is not None and key in done_keys)
    return {
        "summary": summary, "source": source.group(1).lower(), "history": history.group(1).lower(),
        "metrics": metrics, "events": event_set, "triggers": triggers, "completed": completed,
        "failed": failed, "paired": paired, "folder": folder, "magic": magic, "early": early,
    }


def fmt_delta(on_value: str, off_value: str) -> str:
    a, b = first_number(on_value), first_number(off_value)
    if a is None or b is None:
        return "n/a"
    return f"{a - b:+.2f}"


def main() -> int:
    on = read_arm("on")
    off = read_arm("off")
    source_equal = on["source"] == off["source"]
    history_equal = on["history"] == off["history"]
    on_valid_exit = len(on["triggers"]) > 0 and on["paired"] == len(on["triggers"]) and not on["failed"]
    off_clean = len(off["triggers"]) == 0 and len(off["completed"]) == 0 and not off["failed"]
    settings_ok = source_equal and history_equal
    rows = [
        "# TV26 matched early-exit A/B — 2026-10-24",
        "",
        "Both arms use the same three-day XAUUSD M1 window, MT5 Model 4, source file, history feed, risk 2%, SL 5 ATR and TP 20 ATR. Only InpUseRuleBasedEarlyExit differs. These diagnostic risk/SL/TP values are not the candidate's production defaults.",
        "",
        f"- Source hash equal: {'YES' if source_equal else 'NO'} ({on['source']} vs {off['source']})",
        f"- OHLCV history hash equal: {'YES' if history_equal else 'NO'} ({on['history']} vs {off['history']})",
        f"- Formula/data audits: PASS for both arms",
        f"- Early-exit ON triggers/completed/failed: {len(on['triggers'])}/{len(on['completed'])}/{len(on['failed'])}; paired trigger tickets: {on['paired']}",
        f"- Early-exit OFF triggers/completed/failed: {len(off['triggers'])}/{len(off['completed'])}/{len(off['failed'])}",
        "",
        "| Metric | Exit ON | Exit OFF | ON minus OFF |",
        "|---|---:|---:|---:|",
    ]
    for name, label in METRICS.items():
        a = on["metrics"][name]
        b = off["metrics"][name]
        rows.append(f"| {name} | {a} | {b} | {fmt_delta(a, b)} |")
    rows.extend(["", "## Early exit events with exit ON", ""])
    rows.extend([f"- {x}" for x in on["triggers"]])
    rows.extend(["", "## Early exit events with exit OFF", ""])
    rows.extend([f"- Unexpected event: {x}" for x in sorted(off["events"])])
    rows.extend(["", "## Verdict", ""])
    if not settings_ok:
        verdict = "INVALID_MATCH: source or data history hashes differ"
    elif not on_valid_exit:
        verdict = "INCONCLUSIVE: exit-ON arm did not demonstrate successful rule-based closes"
    elif not off_clean:
        verdict = "INVALID_MATCH: exit-OFF arm emitted early-exit events"
    else:
        verdict = "MATCHED_A_B_VALID: same source/history and switch is isolated"
    rows.append(f"**{verdict}.**")
    rows.append("")
    rows.append("The A/B comparison measures the effect of enabling early exits on this one historical window; it cannot prove a general profitability edge. The opposite-summary branch remains unvalidated unless a trigger reason OPPOSITE_SUMMARY appears.")
    out = ROOT / "tv26-exit-ab-comparison.md"
    out.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(out.read_text(encoding="utf-8"))
    return 0 if settings_ok and on_valid_exit and off_clean else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"TV26 A/B comparison failed: {exc}", file=sys.stderr)
        raise
