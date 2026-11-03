from __future__ import annotations

from typing import Any

import numpy as np

def _body_bounds(bar: dict[str, Any]) -> tuple[float, float]:
    top = float(min(bar["body_top_y_px"], bar["body_bottom_y_px"]))
    bottom = float(max(bar["body_top_y_px"], bar["body_bottom_y_px"]))
    return top, bottom


def _patterns(
    bars: list[dict[str, Any]], *, last_candle_closed: bool = True
) -> list[dict[str, Any]]:
    """Return low-confidence visual pattern candidates; never directional votes.

    The rules use only visible candle geometry. They are intentionally
    conservative and remain diagnostics until compared with labelled,
    out-of-sample chart images.
    """
    patterns: list[dict[str, Any]] = []

    def add(index: int, start_index: int, name: str, colour: str | None = None) -> None:
        item: dict[str, Any] = {
            "index": index,
            "start_index": start_index,
            "pattern": name,
            "confidence": "LOW",
            "confirmation_state": (
                "FORMING" if index == len(bars) - 1 and not last_candle_closed
                else "CANDIDATE_ONLY"
            ),
            "uses_unconfirmed_latest_candle": bool(
                index == len(bars) - 1 and not last_candle_closed
            ),
        }
        if colour is not None:
            item["colour"] = colour
        patterns.append(item)

    body_sizes = [
        max(1.0, abs(float(bar["body_bottom_y_px"]) - float(bar["body_top_y_px"])))
        for bar in bars
    ]
    candle_ranges = [
        max(1.0, float(bar["low_y_px"]) - float(bar["high_y_px"]))
        for bar in bars
    ]

    for i, bar in enumerate(bars):
        if i >= 10:
            previous_10_body = float(np.mean(body_sizes[i - 10:i]))
            previous_10_range = float(np.mean(candle_ranges[i - 10:i]))
            current_body = body_sizes[i]
            body_top, body_bottom = _body_bounds(bar)
            upper_shadow = max(0.0, body_top - float(bar["high_y_px"]))
            lower_shadow = max(0.0, float(bar["low_y_px"]) - body_bottom)
            very_short_shadow = previous_10_range * 0.10

            # TA-Lib defaults: BodyDoji = 10% of previous 10 High-Low ranges.
            # Use prior candles only; do not validate an earlier candle with
            # future bars that would not have been available at its close.
            if current_body <= very_short_shadow:
                add(i, i, "doji_candidate", str(bar.get("colour", "UNKNOWN")))

            # TA-Lib hammer geometry: short real body, lower shadow longer
            # than the body, very short upper shadow, and body near prior low.
            if i >= 5:
                near_range = float(np.mean(candle_ranges[i - 5:i]))
                previous_low_y = float(bars[i - 1]["low_y_px"])
                body_near_prior_low = body_bottom >= previous_low_y - near_range * 0.20
                if (
                    current_body < previous_10_body
                    and lower_shadow > current_body
                    and upper_shadow < very_short_shadow
                    and body_near_prior_low
                ):
                    add(i, i, "hammer_candidate", str(bar.get("colour", "UNKNOWN")))

            # TA-Lib shooting star also requires a real-body gap up from the
            # previous candle. Pixel y is inverted, so a price gap up means
            # today's body-bottom y is above yesterday's body-top y.
            previous_body_top, _ = _body_bounds(bars[i - 1])
            gap_up = body_bottom < previous_body_top
            if (
                current_body < previous_10_body
                and upper_shadow > current_body
                and lower_shadow < very_short_shadow
                and gap_up
            ):
                add(i, i, "shooting_star_candidate", str(bar.get("colour", "UNKNOWN")))

        if i >= 1:
            previous = bars[i - 1]
            prev_top, prev_bottom = _body_bounds(previous)
            curr_top, curr_bottom = _body_bounds(bar)
            prev_size = max(1.0, prev_bottom - prev_top)
            curr_size = max(1.0, curr_bottom - curr_top)
            opposite_colours = previous.get("colour") != bar.get("colour")

            if (
                previous.get("colour") == "RED"
                and bar.get("colour") == "GREEN"
                and curr_top <= prev_top
                and curr_bottom >= prev_bottom
            ):
                add(i, i - 1, "bullish_engulfing_candidate")
            elif (
                previous.get("colour") == "GREEN"
                and bar.get("colour") == "RED"
                and curr_top <= prev_top
                and curr_bottom >= prev_bottom
            ):
                add(i, i - 1, "bearish_engulfing_candidate")

            # TA-Lib Harami: first body is long against its preceding
            # ten-body mean; second is short against its own prior-ten mean
            # and fully contained in the first body. TA-Lib's generic class
            # does not require opposite candle colours.
            if i >= 11:
                previous_body_long_mean = float(np.mean(body_sizes[i - 11:i - 1]))
                current_body_short_mean = float(np.mean(body_sizes[i - 10:i]))
                if (
                    prev_size > previous_body_long_mean
                    and curr_size <= current_body_short_mean
                    and curr_top >= prev_top
                    and curr_bottom <= prev_bottom
                ):
                    add(i, i - 1, "harami_candidate")

        if i >= 12:
            first, middle, last = bars[i - 2], bars[i - 1], bar
            first_top, first_bottom = _body_bounds(first)
            middle_top, middle_bottom = _body_bounds(middle)
            last_top, last_bottom = _body_bounds(last)
            first_size = body_sizes[i - 2]
            middle_size = body_sizes[i - 1]
            last_size = body_sizes[i]
            long_body_mean = float(np.mean(body_sizes[i - 12:i - 2]))
            middle_short_mean = float(np.mean(body_sizes[i - 11:i - 1]))
            last_short_mean = float(np.mean(body_sizes[i - 10:i]))

            # TA-Lib Morning Star: long red first body, small second body
            # gaps below the first, and a third green close penetrates at
            # least 30% into the first body.
            morning_gap_down = middle_top > first_bottom
            first_red = first.get("colour") == "RED"
            third_green = last.get("colour") == "GREEN"
            first_close_y = first_bottom  # red candle closes at its lower body edge
            third_close_y = last_top      # green candle closes at its upper body edge
            morning_penetration = third_close_y < first_close_y - first_size * 0.30

            if (
                first_red and third_green
                and first_size > long_body_mean
                and middle_size <= middle_short_mean
                and last_size > last_short_mean
                and morning_gap_down
                and morning_penetration
            ):
                add(i, i - 2, "morning_star_candidate")

            # TA-Lib Evening Star is the mirrored case: long green first
            # body, small second body gaps above it, and a red third close
            # penetrates at least 30% into the first body.
            evening_gap_up = middle_bottom < first_top
            first_green = first.get("colour") == "GREEN"
            third_red = last.get("colour") == "RED"
            first_close_y = first_top  # green candle closes at its upper body edge
            third_close_y = last_bottom  # red candle closes at its lower body edge
            evening_penetration = third_close_y > first_close_y + first_size * 0.30

            if (
                first_green and third_red
                and first_size > long_body_mean
                and middle_size <= middle_short_mean
                and last_size > last_short_mean
                and evening_gap_up
                and evening_penetration
            ):
                add(i, i - 2, "evening_star_candidate")

    return patterns[-60:]
