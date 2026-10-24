#!/usr/bin/env python3
"""Manual, read-only independent reviews of TV26 source via official model APIs."""
from __future__ import annotations
import json, os, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tv26-independent-review"
OUT.mkdir(parents=True, exist_ok=True)
SCOPE = os.getenv("TV26_REVIEW_SCOPE", "full")
BRANCH = os.getenv("TV26_BRANCH", "unknown")
COMMIT = os.getenv("TV26_COMMIT", "unknown")
FILES = {
    "EA candidate": ROOT / "trading-lab/tv26/TV26_FiveTF_Arabic_CANDIDATE.mq5",
    "exit contract tests": ROOT / "trading-lab/tv26/test_tv26_exit_contract.py",
    "A/B pairing tests": ROOT / "trading-lab/tv26/test_tv26_exit_ab_pairing.py",
    "A/B comparison logic": ROOT / "trading-lab/tv26/compare_tv26_exit_ab.py",
    "direct parity guide": ROOT / "trading-lab/tv26/DIRECT_TRADINGVIEW_PARITY_GUIDE_AR.md",
}

def read_packet():
    parts = [
        "Repository: staryuzar/-", f"Branch: {BRANCH}", f"Commit: {COMMIT}",
        f"Review scope: {SCOPE}",
        "Review only the supplied source. Do not assume tests passed unless source proves it.",
        "Never recommend enabling live trading based on code review alone.",
    ]
    for label, path in FILES.items():
        if not path.is_file():
            parts.append(f"\n===== {label}: FILE MISSING =====")
            continue
        data = path.read_text(encoding="utf-8", errors="replace")
        if label != "EA candidate" and len(data) > 18000:
            data = data[:14000] + "\n...[truncated for review context]...\n" + data[-4000:]
        parts.append(f"\n===== {label} ({path.relative_to(ROOT)}) =====\n{data}")
    focus = {
        "full": "Review correctness, trading logic, MQL5 API use, state handling, risk/position management, edge cases, and test gaps.",
        "exit-path": "Focus on early-exit triggers, close result handling, duplicate closes, event logging, ticket/reason/bar pairing, and test gaps.",
        "tradingview-parity": "Focus on formula parity, symbol/feed/timeframe alignment, bar-close vs intrabar behavior, warm-up/history, Ichimoku offsets, rounding and direct exported-CSV comparison.",
    }.get(SCOPE, "Review correctness and test gaps.")
    parts.append("\n===== REVIEW INSTRUCTIONS =====\n" + focus + "\n"
        + "Return: (1) executive verdict; (2) ranked findings with file/function/line references; "
        + "(3) reproducible failure scenarios; (4) exact proposed fixes; (5) tests proving each fix; "
        + "(6) what source review cannot conclude. Avoid generic style comments. Separate confirmed defects from hypotheses.")
    return "\n".join(parts)

def post_json(url, headers, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={**headers, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=150) as response:
        return json.loads(response.read().decode())

def call_anthropic(prompt):
    data = post_json("https://api.anthropic.com/v1/messages", {
        "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"
    }, {"model": "claude-sonnet-4-5-20250929", "max_tokens": 6500,
        "messages": [{"role": "user", "content": prompt}]})
    return "\n".join(x.get("text", "") for x in data.get("content", []) if x.get("type") == "text")

def call_deepseek(prompt):
    data = post_json("https://api.deepseek.com/chat/completions", {
        "Authorization": "Bearer " + os.environ["DEEPSEEK_API_KEY"]
    }, {"model": "deepseek-chat", "temperature": 0.1, "messages": [
        {"role": "system", "content": "You are an independent senior MQL5 and algorithmic-trading code auditor. Be skeptical and evidence-based."},
        {"role": "user", "content": prompt}]})
    return data["choices"][0]["message"]["content"]

def call_gemini(prompt):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent"
    data = post_json(url, {"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, {
        "systemInstruction": {"parts": [{"text": "Act as an independent senior MQL5 reviewer. Find concrete defects; distinguish evidence from hypotheses."}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 6500}})
    return "\n".join(p.get("text", "") for c in data.get("candidates", []) for p in c.get("content", {}).get("parts", []) if p.get("text"))

def main():
    packet = read_packet()
    (OUT / "review_scope.txt").write_text(f"Branch: {BRANCH}\nCommit: {COMMIT}\nScope: {SCOPE}\nMode: manual; source-only; read-only; no trading or repository writes.\n", encoding="utf-8")
    providers = [("Claude", "ANTHROPIC_API_KEY", call_anthropic), ("DeepSeek", "DEEPSEEK_API_KEY", call_deepseek), ("Gemini", "GEMINI_API_KEY", call_gemini)]
    if not any(os.getenv(key) for _, key, _ in providers):
        msg = "No provider API keys configured. Add repository Actions secrets: ANTHROPIC_API_KEY, DEEPSEEK_API_KEY, GEMINI_API_KEY; then dispatch this workflow manually."
        (OUT / "SETUP_REQUIRED.md").write_text("# Setup required\n\n" + msg + "\n", encoding="utf-8")
        print(msg, file=sys.stderr)
        return 2
    results = []
    for name, env_key, fn in providers:
        if not os.getenv(env_key):
            results.append((name, "SKIPPED", "API key secret not configured."))
            continue
        try:
            response = fn(packet)
            if not response.strip():
                raise ValueError("Provider returned an empty text response")
            (OUT / f"{name.lower()}_review.md").write_text(
                f"# {name} independent review\n\nBranch: {BRANCH}\nCommit: {COMMIT}\nScope: {SCOPE}\n\n{response}\n", encoding="utf-8")
            results.append((name, "SUCCESS", "Review saved."))
        except Exception as exc:
            safe = f"{type(exc).__name__}: {str(exc)[:900]}"
            (OUT / f"{name.lower()}_ERROR.txt").write_text(safe + "\n", encoding="utf-8")
            results.append((name, "ERROR", safe))
        time.sleep(1)
    lines = ["# TV26 independent multi-model review — run summary", "", f"- Branch: {BRANCH}", f"- Commit: {COMMIT}", f"- Scope: {SCOPE}",
        "- Mode: manual, read-only review of selected source files; no MT5 credentials or trading data sent.",
        "- Provider reviews are advisory, not proof of correctness or profitability.", "", "| Provider | Status | Details |", "|---|---|---|"]
    for name, status, detail in results:
        lines.append(f"| {name} | {status} | {detail.replace('|', '/')} |")
    lines += ["", "## Synthesis protocol", "",
        "Treat a defect as confirmed only when the cited source path and behavior can be reproduced. Prioritize independently repeated findings, then add a deterministic regression test before changing the EA. Do not merge or enable live trading based on model opinions.", ""]
    (OUT / "SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if any(status == "SUCCESS" for _, status, _ in results) else 1

if __name__ == "__main__":
    raise SystemExit(main())
