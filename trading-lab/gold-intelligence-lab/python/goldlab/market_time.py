"""Broker-server wall-time conversion for MetaTrader timestamps.

Some MT5 server feeds expose broker-wall-clock timestamps encoded as epoch
seconds. Headway documents a seasonal GMT+2/GMT+3 server clock. Never silently
guess an offset: callers specify an IANA timezone, defaulting to the verified
Headway-compatible Europe/Athens seasonal rule for this project.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Iterable

UTC = timezone.utc
DEFAULT_SERVER_TIMEZONE = os.environ.get("GOLDLAB_MT5_SERVER_TIMEZONE", "Europe/Athens")


def _zone(timezone_name: str) -> ZoneInfo | timezone:
    name = str(timezone_name).strip()
    if name.upper() in {"UTC", "ETC/UTC", "GMT", "Z"}:
        return UTC
    if not name:
        raise ValueError("A server timezone is required; choose UTC or an IANA timezone.")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown MT5 server timezone {name!r}; choose an IANA timezone.") from exc


def _utc_candidates(server_epoch: float, zone: ZoneInfo | timezone) -> list[float]:
    """Map an encoded server-wall timestamp to possible real UTC instants."""
    value = float(server_epoch)
    if not value == value or value in (float("inf"), float("-inf")):
        raise ValueError("MT5 timestamp must be finite.")
    if zone is UTC:
        return [value]
    # MT5's server wall-clock fields are represented as if the wall clock were UTC.
    wall = datetime.fromtimestamp(value, UTC).replace(tzinfo=None)
    candidates: set[float] = set()
    for fold in (0, 1):
        aware = wall.replace(tzinfo=zone, fold=fold)
        instant = aware.astimezone(UTC)
        round_trip = instant.astimezone(zone).replace(tzinfo=None)
        if round_trip == wall:
            candidates.add(instant.timestamp())
    if not candidates:
        raise ValueError(
            f"MT5 server timestamp {wall.isoformat()} falls in a nonexistent local-clock interval "
            f"for timezone {getattr(zone, 'key', str(zone))}."
        )
    return sorted(candidates)


def server_timestamp_to_utc(
    server_epoch: float, timezone_name: str = DEFAULT_SERVER_TIMEZONE, *,
    reference_utc_epoch: float | None = None,
) -> float:
    """Convert one broker-wall timestamp into real UTC epoch seconds.

    For a repeated daylight-saving hour, a current quote uses the candidate
    closest to the capture clock. A historical sequence should use the sequence
    converter below so chronology disambiguates the repeated hour.
    """
    zone = _zone(timezone_name)
    candidates = _utc_candidates(server_epoch, zone)
    if reference_utc_epoch is None or len(candidates) == 1:
        return candidates[0]
    reference = float(reference_utc_epoch)
    return min(candidates, key=lambda candidate: abs(candidate - reference))


def server_timestamp_sequence_to_utc(
    values: Iterable[float], timezone_name: str = DEFAULT_SERVER_TIMEZONE, *,
    expected_interval_seconds: int | None = None,
) -> list[float]:
    """Convert an ordered MT5 bar-time sequence, including a DST clock rollback.

    Input order is preserved; no sorting or interpolation is performed. During
    a repeated daylight-saving hour, monotonic UTC chronology chooses the fold.
    Invalid or non-chronological data raises instead of being silently repaired.
    """
    zone = _zone(timezone_name)
    result: list[float] = []
    previous: float | None = None
    for raw in values:
        candidates = _utc_candidates(raw, zone)
        if previous is None:
            selected = candidates[0]
        else:
            chronological = [candidate for candidate in candidates if candidate > previous]
            if not chronological:
                raise ValueError(
                    "MT5 bar timestamps cannot be mapped to a strictly increasing UTC sequence; "
                    "check server timezone and raw history."
                )
            if expected_interval_seconds and len(chronological) > 1:
                target = previous + int(expected_interval_seconds)
                selected = min(chronological, key=lambda candidate: abs(candidate - target))
            else:
                selected = min(chronological)
        result.append(float(selected))
        previous = float(selected)
    return result


__all__ = [
    "DEFAULT_SERVER_TIMEZONE", "server_timestamp_to_utc",
    "server_timestamp_sequence_to_utc",
]
