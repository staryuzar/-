from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import math
from pathlib import Path
import zipfile

from ..quality import utc_now_ms
from .http import get_bytes


CFTC_TFF_CODES = {"133741": "BTC", "133742": "BTC_MICRO"}
CFTC_ARCHIVE = "https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip"


def _number(raw: object) -> float | None:
    value = str(raw or "").strip().replace(",", "")
    if value.lower() in {"", "-", "--", "n/a", "na", "null", "none"}:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _report_date(raw: object) -> str | None:
    value = str(raw or "").strip().strip('\"')
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def parse_tff_csv(csv_text: str) -> list[dict]:
    """Parse official CFTC Traders in Financial Futures, Futures Only rows."""
    if not isinstance(csv_text, str) or not csv_text.strip():
        raise ValueError("CFTC TFF file is empty.")
    reader = csv.reader(io.StringIO(csv_text))
    rows = []
    for fields in reader:
        if len(fields) < 16:
            continue
        if fields[0].strip().lower() in {"market_and_exchange_names", "market and exchange names"}:
            continue
        code = fields[3].strip().strip('"')
        if code not in CFTC_TFF_CODES:
            continue
        # Optional positioning fields may be blank or represented by dashes.
        report_date = _report_date(fields[2])
        if report_date is None:
            continue
        oi = _number(fields[7])
        if oi is None or oi <= 0:
            continue
        dealer_long, dealer_short = _number(fields[8]), _number(fields[9])
        asset_long, asset_short = _number(fields[11]), _number(fields[12])
        lev_long, lev_short = _number(fields[14]), _number(fields[15])
        rows.append({
            "asset": CFTC_TFF_CODES[code], "contract_code": code,
            "market_name": fields[0].strip(), "report_date": report_date,
            "open_interest": oi,
            "dealer_net": dealer_long - dealer_short if dealer_long is not None and dealer_short is not None else None,
            "asset_manager_net": asset_long - asset_short if asset_long is not None and asset_short is not None else None,
            "leveraged_money_net": lev_long - lev_short if lev_long is not None and lev_short is not None else None,
            "source": "CFTC Traders in Financial Futures — Futures Only",
        })
    return sorted(rows, key=lambda row: (row["report_date"], row["contract_code"]), reverse=True)


def fetch_bitcoin_cot(year: int | None = None) -> dict:
    selected_year = year or datetime.now(timezone.utc).year
    if selected_year < 2010 or selected_year > datetime.now(timezone.utc).year:
        raise ValueError("Unsupported CFTC archive year.")
    payload = get_bytes(CFTC_ARCHIVE.format(year=selected_year), timeout=20.0)
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            candidates = [name for name in archive.namelist() if name.lower().endswith((".txt", ".csv"))]
            if not candidates:
                raise ValueError("CFTC archive has no text/CSV member.")
            member = max(candidates, key=lambda name: archive.getinfo(name).file_size)
            raw = archive.read(member)
    except zipfile.BadZipFile as exc:
        raise ValueError("CFTC archive is not a valid ZIP file.") from exc
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    rows = parse_tff_csv(text)
    return {
        "fetched_at_ms": utc_now_ms(), "year": selected_year, "rows": rows,
        "source_url": CFTC_ARCHIVE.format(year=selected_year),
        "note": "Weekly CME futures-only positioning; not spot exchange positions and not a real-time signal.",
    }
