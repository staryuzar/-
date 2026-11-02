from __future__ import annotations

import hashlib
import json
import time
from typing import Any

KNOWLEDGE_VERSION = "1.0.0"

def _pattern(
    pattern_id: str, en: str, ar: str, family: str, direction: str,
    bars: int, geometry: str, context: str, confirmation: str,
    invalidation: str, limitation: str, reference: str,
) -> dict[str, Any]:
    return {
        "pattern_id": pattern_id, "name_en": en, "name_ar": ar,
        "family": family, "direction": direction, "formation_bars": bars,
        "geometry_rule": geometry, "context_rule": context,
        "confirmation_rule": confirmation, "invalidation_rule": invalidation,
        "limitations": limitation, "reference": reference,
        "definition_status": "DOCUMENTED_RULE",
        "empirical_status": "UNVALIDATED",
    }

_CANDLE_REFERENCE = "Nison, Japanese Candlestick Charting Techniques; Morris, Candlestick Charting Explained. Definitions are educational rules, not performance claims."

CANDLE_PATTERN_CATALOG: tuple[dict[str, Any], ...] = (
    _pattern("doji","Doji","دوجي","indecision","NEUTRAL",1,"Open and close are nearly equal relative to the full candle range.","Most meaningful after an extended move or at a well-defined level.","Wait for a later close to leave the doji range in the proposed direction.","A close through the opposite side of the doji range weakens the idea.","A doji alone has no reliable direction; thresholds depend on volatility and chart precision.",_CANDLE_REFERENCE),
    _pattern("dragonfly_doji","Dragonfly Doji","دوجي اليعسوب","indecision","CONTEXTUAL",1,"Very small real body near the high; long lower shadow; little upper shadow.","Potential bullish rejection after a decline or at support.","Require a subsequent bullish close or a confirmed level reclaim.","A decisive close below the pattern low invalidates the rejection thesis.","Crypto markets trade continuously; gap-based textbook context is often absent.",_CANDLE_REFERENCE),
    _pattern("gravestone_doji","Gravestone Doji","دوجي شاهد القبر","indecision","CONTEXTUAL",1,"Very small body near the low; long upper shadow; little lower shadow.","Potential bearish rejection after an advance or at resistance.","Require a subsequent bearish close or confirmed loss of a level.","A decisive close above the pattern high invalidates the rejection thesis.","A single upper wick is not proof of distribution or a reversal.",_CANDLE_REFERENCE),
    _pattern("long_legged_doji","Long-legged Doji","دوجي طويل الظلال","indecision","NEUTRAL",1,"Small body with substantial upper and lower shadows.","Can mark two-sided volatility or uncertainty near an important area.","Wait for a close outside the full range and assess volume/context separately.","A break that immediately returns into the range weakens the signal.","Large shadows can result from isolated volatility rather than a meaningful auction.",_CANDLE_REFERENCE),
    _pattern("hammer","Hammer","المطرقة","reversal","BULLISH",1,"Small body near the candle high with a lower shadow materially longer than the body.","Requires a prior decline; stronger near support or after a downside liquidity sweep.","Prefer a later close above the hammer high or a clear bullish follow-through.","A close below the hammer low invalidates the reversal structure.","The same geometry without a prior decline is not a hammer reversal.",_CANDLE_REFERENCE),
    _pattern("hanging_man","Hanging Man","الرجل المشنوق","reversal","BEARISH",1,"Hammer-like geometry with the body near the candle high.","Requires a prior advance; stronger near resistance after an extended move.","Prefer a later bearish close below the candle body or low.","A sustained close above the pattern high weakens the bearish thesis.","Geometry alone cannot distinguish it from a hammer; context is essential.",_CANDLE_REFERENCE),
    _pattern("inverted_hammer","Inverted Hammer","المطرقة المقلوبة","reversal","BULLISH",1,"Small body near the candle low with a long upper shadow and little lower shadow.","Requires a prior decline; stronger at support after selling pressure.","Require bullish follow-through, ideally a close above its high.","A close below the pattern low invalidates the setup idea.","The upper shadow shows attempted buying, not confirmed demand.",_CANDLE_REFERENCE),
    _pattern("shooting_star","Shooting Star","الشهاب","reversal","BEARISH",1,"Small body near the candle low with a long upper shadow and little lower shadow.","Requires a prior advance; stronger near resistance or a buy-side sweep.","Require bearish follow-through or a later close below the candle low.","A decisive close above the pattern high invalidates the rejection idea.","Do not confuse a long upper wick in a range with a reversal.",_CANDLE_REFERENCE),
    _pattern("bullish_marubozu","Bullish Marubozu","ماروبوزو صاعد","continuation","BULLISH",1,"Large bullish body with very small upper and lower shadows.","Stronger after a range breakout or in an established uptrend.","Look for acceptance above the high; avoid chasing an exhausted impulse.","A quick close back inside the prior range weakens continuation.","Large candles can be climax moves; size must be normalized by recent volatility.",_CANDLE_REFERENCE),
    _pattern("bearish_marubozu","Bearish Marubozu","ماروبوزو هابط","continuation","BEARISH",1,"Large bearish body with very small upper and lower shadows.","Stronger after a range breakdown or in an established downtrend.","Look for acceptance below the low and follow-through.","A quick close back inside the prior range weakens continuation.","Large candles can be capitulation rather than a durable trend.",_CANDLE_REFERENCE),
    _pattern("spinning_top","Spinning Top","القمة الدوارة","indecision","NEUTRAL",1,"Relatively small body with upper and lower shadows of meaningful size.","Interpret only with surrounding trend, levels and volatility.","Wait for the next closes to resolve the range.","A clean break against the proposed context removes the setup.","It describes balance/indecision, not a standalone directional signal.",_CANDLE_REFERENCE),
    _pattern("bullish_engulfing","Bullish Engulfing","الابتلاع الصاعد","reversal","BULLISH",2,"Second bullish real body fully contains the prior bearish real body.","More meaningful after a decline and near a tested support/liquidity area.","Prefer close above the first body and a subsequent hold above its midpoint.","A close below the two-candle low invalidates the bullish idea.","Body engulfment is not the same as full-range engulfment; define it consistently.",_CANDLE_REFERENCE),
    _pattern("bearish_engulfing","Bearish Engulfing","الابتلاع الهابط","reversal","BEARISH",2,"Second bearish real body fully contains the prior bullish real body.","More meaningful after an advance and near resistance/liquidity.","Prefer close below the first body and subsequent acceptance below midpoint.","A close above the two-candle high invalidates the bearish idea.","The pattern is weaker in low-liquidity candles or inside noisy ranges.",_CANDLE_REFERENCE),
    _pattern("bullish_harami","Bullish Harami","هارامي صاعد","reversal","BULLISH",2,"A small second body is contained inside a preceding long bearish body.","Potential loss of downside momentum after a decline.","Require a bullish close above the second candle high or reclaim of the first-body midpoint.","A close below the two-candle low weakens the idea.","Containment alone is not proof of reversal; use trend and location.",_CANDLE_REFERENCE),
    _pattern("bearish_harami","Bearish Harami","هارامي هابط","reversal","BEARISH",2,"A small second body is contained inside a preceding long bullish body.","Potential loss of upside momentum after an advance.","Require a bearish close below the second candle low or loss of midpoint.","A close above the two-candle high weakens the idea.","Containment alone is not proof of reversal; use trend and location.",_CANDLE_REFERENCE),
    _pattern("harami_cross","Harami Cross","هارامي متقاطع","reversal","CONTEXTUAL",2,"A doji-like second candle is contained inside the prior long real body.","A possible pause after a directional move.","Wait for a close outside the two-candle structure.","A break opposite to the proposed context invalidates it.","Doji thresholds and body containment must be measured consistently.",_CANDLE_REFERENCE),
    _pattern("piercing_line","Piercing Line","خط الاختراق الصاعد","reversal","BULLISH",2,"A bullish second body closes above the midpoint of the prior bearish body without fully engulfing it.","Requires prior selling pressure; level location increases relevance.","Prefer a later close above the second candle high.","A close below the two-candle low invalidates the bullish case.","Classic gap-down requirement is softened for continuous crypto markets; mark as adapted.",_CANDLE_REFERENCE),
    _pattern("dark_cloud_cover","Dark Cloud Cover","الغطاء السحابي الداكن","reversal","BEARISH",2,"A bearish second body closes below the midpoint of the prior bullish body without fully engulfing it.","Requires prior buying pressure; stronger near resistance.","Prefer a later close below the second candle low.","A close above the two-candle high invalidates the bearish case.","Classic gap-up requirement is softened for continuous crypto markets; mark as adapted.",_CANDLE_REFERENCE),
    _pattern("tweezer_bottom","Tweezer Bottom","القاع الملقط","reversal","BULLISH",2,"Two or more adjacent candles test nearly the same low within a volatility-scaled tolerance.","More meaningful after a decline and at a known demand/support area.","Require a bullish close away from the shared low and preferably above a local pivot.","A decisive close below the shared low invalidates the rejection.","Tolerance must scale with ATR/tick size; exact pixel equality is inappropriate.",_CANDLE_REFERENCE),
    _pattern("tweezer_top","Tweezer Top","القمة الملقط","reversal","BEARISH",2,"Two or more adjacent candles test nearly the same high within a volatility-scaled tolerance.","More meaningful after an advance and near resistance.","Require a bearish close away from the shared high.","A decisive close above the shared high invalidates the rejection.","Equal highs are a price-location observation, not automatically a reversal.",_CANDLE_REFERENCE),
    _pattern("inside_bar","Inside Bar","شمعة داخلية","compression","NEUTRAL",2,"The current candle high and low remain inside the preceding candle range.","Often represents short-term compression after an impulse or at a decision area.","Use a confirmed close outside the mother-bar range to establish direction.","A false break returning into the mother bar cancels the breakout thesis.","A forming candle can appear inside and later expand; only closed bars qualify.",_CANDLE_REFERENCE),
    _pattern("outside_bar","Outside Bar","شمعة خارجية","expansion","CONTEXTUAL",2,"The current candle range exceeds both the preceding high and low.","Context determines whether it is rejection, expansion or volatility noise.","Read the close location and follow-through; do not assign direction from range alone.","A close back inside the prior range weakens the expansion interpretation.","It can be a stop-run or news candle; direction depends on close and context.",_CANDLE_REFERENCE),
    _pattern("morning_star","Morning Star","نجمة الصباح","reversal","BULLISH",3,"Long bearish candle, smaller pause candle, then bullish close penetrating the first body midpoint.","Requires prior decline; stronger at support or after a sell-side sweep.","Require the third candle to close beyond the first-body midpoint, then monitor hold.","A break below the three-candle low invalidates the bullish structure.","Crypto adaptation does not require overnight gaps; three-bar context still matters.",_CANDLE_REFERENCE),
    _pattern("evening_star","Evening Star","نجمة المساء","reversal","BEARISH",3,"Long bullish candle, smaller pause candle, then bearish close penetrating the first body midpoint.","Requires prior advance; stronger at resistance or after a buy-side sweep.","Require the third candle to close beyond the first-body midpoint, then monitor hold.","A break above the three-candle high invalidates the bearish structure.","Crypto adaptation does not require overnight gaps; three-bar context still matters.",_CANDLE_REFERENCE),
    _pattern("three_white_soldiers","Three White Soldiers","الجنود الثلاثة البيض","continuation","BULLISH",3,"Three consecutive strong bullish candles with progressively higher closes and controlled wicks.","More meaningful after basing or a confirmed bullish structure shift.","Prefer subsequent acceptance above the three-candle high without immediate exhaustion.","A close below the first soldier low weakens the sequence.","Late-stage sequences can be overextended; avoid treating them as an entry by themselves.",_CANDLE_REFERENCE),
    _pattern("three_black_crows","Three Black Crows","الغربان السوداء الثلاثة","continuation","BEARISH",3,"Three consecutive strong bearish candles with progressively lower closes and controlled wicks.","More meaningful after distribution or a confirmed bearish structure shift.","Prefer acceptance below the three-candle low.","A close above the first crow high weakens the sequence.","Late-stage sequences can be overextended; avoid treating them as an entry by themselves.",_CANDLE_REFERENCE),
)

def _structure(
    structure_id: str, en: str, ar: str, category: str, rule: str,
    confirmation: str, invalidation: str, limitations: str,
    reference: str = "Murphy, Technical Analysis of the Financial Markets; rule definitions are not empirical claims.",
) -> dict[str, Any]:
    return {
        "structure_id": structure_id, "name_en": en, "name_ar": ar,
        "category": category, "rule": rule, "confirmation_rule": confirmation,
        "invalidation_rule": invalidation, "limitations": limitations,
        "reference": reference, "definition_status": "DOCUMENTED_RULE",
        "empirical_status": "UNVALIDATED",
    }

MARKET_STRUCTURE_CATALOG: tuple[dict[str, Any], ...] = (
    _structure("pivot_high","Pivot High","قمة محورية","swing","A local high exceeds the highs in a declared left/right neighbourhood.","Only after all required right-side bars close.","A later close above the level changes its role; do not rewrite its original confirmation time.","A pivot is scale-dependent; shoulder count and prominence must be reported."),
    _structure("pivot_low","Pivot Low","قاع محوري","swing","A local low is below the lows in a declared left/right neighbourhood.","Only after all required right-side bars close.","A later close below the level changes its role; preserve the original pivot record.","A pivot is scale-dependent; shoulder count and prominence must be reported."),
    _structure("internal_structure","Internal Structure","البنية الداخلية","structure","Shorter confirmed pivots describe the internal swings within a larger leg.","Use a shorter declared pivot width and retain confirmation delay.","A break against the latest internal sequence changes internal bias, not necessarily external trend.","Internal noise must not be mislabeled as an external trend reversal."),
    _structure("external_structure","External Structure","البنية الخارجية","structure","Larger confirmed pivots define the dominant visible swing range.","Use a wider pivot width and enough history for confirmed shoulders.","A confirmed close through the protected external swing changes the external thesis.","A single screenshot cannot provide true multi-timeframe confluence."),
    _structure("higher_high","Higher High (HH)","قمة أعلى","trend","Latest confirmed swing high is above the preceding confirmed swing high.","Compare at least two confirmed highs on the same scale.","A later lower high or structural break changes the sequence.","Two highs alone do not establish a trend without corresponding lows."),
    _structure("higher_low","Higher Low (HL)","قاع أعلى","trend","Latest confirmed swing low is above the preceding confirmed swing low.","Compare at least two confirmed lows on the same scale.","A close below the protected higher low is a potential bearish shift.","Two lows alone do not establish a trend without corresponding highs."),
    _structure("lower_high","Lower High (LH)","قمة أدنى","trend","Latest confirmed swing high is below the preceding confirmed swing high.","Compare at least two confirmed highs on the same scale.","A later higher high changes the descending sequence.","Use matched pivot scales; do not compare internal with external pivots."),
    _structure("lower_low","Lower Low (LL)","قاع أدنى","trend","Latest confirmed swing low is below the preceding confirmed swing low.","Compare at least two confirmed lows on the same scale.","A later higher low changes the descending sequence.","Use matched pivot scales; do not compare internal with external pivots."),
    _structure("bos_bullish","Bullish BOS","كسر بنية صاعد","break","A confirmed candle close crosses above a previously confirmed swing high.","Close beyond the pivot after that pivot became confirmed.","A close back below the broken level may indicate failed acceptance.","Wick-only breaks are not BOS; the pivot must be known at break time."),
    _structure("bos_bearish","Bearish BOS","كسر بنية هابط","break","A confirmed candle close crosses below a previously confirmed swing low.","Close beyond the pivot after that pivot became confirmed.","A close back above the broken level may indicate failed acceptance.","Wick-only breaks are not BOS; the pivot must be known at break time."),
    _structure("choch_bullish","Bullish CHOCH","تغير طابع صاعد","break","A confirmed bullish break occurs against a previously established bearish structure.","Require a prior bearish sequence and a confirmed close above a protected high.","A renewed close below the last protected low invalidates the shift.","A CHOCH is an early structural warning, not a guaranteed reversal."),
    _structure("choch_bearish","Bearish CHOCH","تغير طابع هابط","break","A confirmed bearish break occurs against a previously established bullish structure.","Require a prior bullish sequence and a confirmed close below a protected low.","A renewed close above the last protected high invalidates the shift.","A CHOCH is an early structural warning, not a guaranteed reversal."),
    _structure("equal_highs","Equal Highs (EQH)","قمم متساوية","liquidity","Two or more confirmed highs cluster within a volatility-scaled tolerance.","Require multiple independently confirmed pivots and report tolerance/touches.","A sustained close above the cluster changes it from resting liquidity to a broken level.","Equal highs are approximate; do not require exact equality."),
    _structure("equal_lows","Equal Lows (EQL)","قيعان متساوية","liquidity","Two or more confirmed lows cluster within a volatility-scaled tolerance.","Require multiple independently confirmed pivots and report tolerance/touches.","A sustained close below the cluster changes its state.","Equal lows are approximate; do not require exact equality."),
    _structure("high_liquidity_sweep","High-side Liquidity Sweep","سحب سيولة القمم","liquidity","Price trades above a known prior high and the same candle closes back below that level.","The swept high must have been confirmed before the sweep candle.","A later accepted close above the swept high negates the rejection interpretation.","A wick above a level does not prove stop orders were present."),
    _structure("low_liquidity_sweep","Low-side Liquidity Sweep","سحب سيولة القيعان","liquidity","Price trades below a known prior low and the same candle closes back above that level.","The swept low must have been confirmed before the sweep candle.","A later accepted close below the swept low negates the rejection interpretation.","A wick below a level does not prove stop orders were present."),
    _structure("support_zone","Support Zone","منطقة دعم","zone","A price area formed from clustered confirmed lows and/or repeated reactions.","Record touches, width, timeframe, and the pivots used.","Sustained closes below the zone weaken support; retests may change its role.","A single pivot is a level candidate, not a multi-touch zone."),
    _structure("resistance_zone","Resistance Zone","منطقة مقاومة","zone","A price area formed from clustered confirmed highs and/or repeated reactions.","Record touches, width, timeframe, and the pivots used.","Sustained closes above the zone weaken resistance; retests may change its role.","A single pivot is a level candidate, not a multi-touch zone."),
    _structure("bullish_fvg","Bullish Fair Value Gap","فجوة قيمة عادلة صاعدة","imbalance","In a three-candle sequence, the first candle high is below the third candle low.","Record the zone boundaries and the middle candle; use closed bars only.","Track later overlap/fill; do not assume every gap must fill.","This is a price-range imbalance definition, not proof of institutional orders."),
    _structure("bearish_fvg","Bearish Fair Value Gap","فجوة قيمة عادلة هابطة","imbalance","In a three-candle sequence, the first candle low is above the third candle high.","Record the zone boundaries and the middle candle; use closed bars only.","Track later overlap/fill; do not assume every gap must fill.","This is a price-range imbalance definition, not proof of institutional orders."),
    _structure("bullish_order_block","Bullish Order Block Candidate","كتلة أوامر صاعدة مرشحة","order_block","A candidate is the last bearish candle before a later confirmed bullish displacement/break.","Must be linked to a specific confirmed structure break and report the source candle.","Track mitigations and invalidation by closes below the zone.","The term is methodology-dependent; never infer hidden institutional orders."),
    _structure("bearish_order_block","Bearish Order Block Candidate","كتلة أوامر هابطة مرشحة","order_block","A candidate is the last bullish candle before a later confirmed bearish displacement/break.","Must be linked to a specific confirmed structure break and report the source candle.","Track mitigations and invalidation by closes above the zone.","The term is methodology-dependent; never infer hidden institutional orders."),
    _structure("breaker_block","Breaker Block Candidate","كتلة كاسرة مرشحة","order_block","A previously tracked block fails and its zone is later retested from the opposite side.","Require a prior documented block, failed close, and retest.","A decisive close back through the zone invalidates the breaker interpretation.","Not all broken support/resistance is a breaker block."),
    _structure("mitigation_block","Mitigation Block Candidate","كتلة تخفيف مرشحة","order_block","A previously identified opposing block is revisited after a structure shift.","Require a documented antecedent block and return into its boundaries.","A close beyond the invalidation side removes the candidate.","Definitions vary across trading frameworks; persist source methodology."),
    _structure("premium_discount","Premium / Discount","منطقة علاوة وخصم","range","Locate price relative to the 50% equilibrium of a declared confirmed dealing range.","Use matched confirmed external high/low boundaries.","A new external swing changes the dealing range and equilibrium.","Premium/discount has meaning only relative to a declared range."),
    _structure("range_equilibrium","Range Equilibrium","منتصف النطاق","range","The arithmetic midpoint between a confirmed range high and range low.","Both boundaries must be confirmed and from the same range.","A confirmed range expansion replaces the old equilibrium.","Do not mix prices from different swing regimes."),
    _structure("trend_protected_low","Protected Low","القاع المحمي","trend","The last confirmed low whose hold is required for the current bullish external structure.","Derive from a confirmed bullish BOS and subsequent swing sequence.","A confirmed close below it is a structural invalidation candidate.","Protected swing rules are framework-specific; keep the derivation trace."),
    _structure("trend_protected_high","Protected High","القمة المحمية","trend","The last confirmed high whose hold is required for the current bearish external structure.","Derive from a confirmed bearish BOS and subsequent swing sequence.","A confirmed close above it is a structural invalidation candidate.","Protected swing rules are framework-specific; keep the derivation trace."),
)

def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def seed_visual_knowledge(db_path: str | None = None) -> dict[str, Any]:
    """Idempotently seed documented rule catalogues; no performance stats are fabricated."""
    from ..storage import connect

    conn = connect(db_path) if db_path is not None else connect()
    now = int(time.time() * 1000)
    try:
        with conn:
            for item in CANDLE_PATTERN_CATALOG:
                conn.execute(
                    """INSERT INTO visual_candle_pattern_knowledge
                    (pattern_id,version,name_en,name_ar,family,direction,formation_bars,
                     definition_json,empirical_status,updated_at_ms)
                    VALUES(?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(pattern_id) DO UPDATE SET
                    version=excluded.version,name_en=excluded.name_en,name_ar=excluded.name_ar,
                    family=excluded.family,direction=excluded.direction,
                    formation_bars=excluded.formation_bars,definition_json=excluded.definition_json,
                    empirical_status='UNVALIDATED',updated_at_ms=excluded.updated_at_ms""",
                    (item["pattern_id"], KNOWLEDGE_VERSION, item["name_en"], item["name_ar"],
                     item["family"], item["direction"], item["formation_bars"],
                     _json(item), item["empirical_status"], now),
                )
            for item in MARKET_STRUCTURE_CATALOG:
                conn.execute(
                    """INSERT INTO visual_structure_knowledge
                    (structure_id,version,name_en,name_ar,category,definition_json,
                     empirical_status,updated_at_ms)
                    VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(structure_id) DO UPDATE SET
                    version=excluded.version,name_en=excluded.name_en,name_ar=excluded.name_ar,
                    category=excluded.category,definition_json=excluded.definition_json,
                    empirical_status='UNVALIDATED',updated_at_ms=excluded.updated_at_ms""",
                    (item["structure_id"], KNOWLEDGE_VERSION, item["name_en"], item["name_ar"],
                     item["category"], _json(item), item["empirical_status"], now),
                )
            conn.execute(
                """INSERT INTO visual_knowledge_meta(namespace,version,updated_at_ms)
                VALUES('engine_2',?,?) ON CONFLICT(namespace) DO UPDATE SET
                version=excluded.version,updated_at_ms=excluded.updated_at_ms""",
                (KNOWLEDGE_VERSION, now),
            )
        return {
            "status": "READY",
            "version": KNOWLEDGE_VERSION,
            "candle_pattern_definitions": len(CANDLE_PATTERN_CATALOG),
            "market_structure_definitions": len(MARKET_STRUCTURE_CATALOG),
            "empirical_status": "UNVALIDATED",
        }
    finally:
        conn.close()

def record_pattern_observations(
    sample_fingerprint: str, symbol: str, timeframe: str,
    observations: list[dict[str, Any]], *, db_path: str | None = None,
    observed_at_ms: int | None = None,
) -> int:
    """Persist auditable pattern detections; duplicate sample events are idempotent."""
    from ..storage import connect

    if not sample_fingerprint.strip() or not symbol.strip() or not timeframe.strip():
        raise ValueError("sample_fingerprint, symbol and timeframe are required")
    known = {item["pattern_id"] for item in CANDLE_PATTERN_CATALOG}
    conn = connect(db_path) if db_path is not None else connect()
    now = observed_at_ms or int(time.time() * 1000)
    count = 0
    try:
        with conn:
            for event in observations:
                pattern_id = str(event.get("pattern_id", ""))
                if pattern_id not in known:
                    raise ValueError(f"Unknown candle pattern id: {pattern_id}")
                start = int(event.get("start_index", event.get("index", 0)))
                end = int(event.get("end_index", event.get("index", start)))
                identity = "|".join((sample_fingerprint, symbol.upper(), timeframe, pattern_id, str(start), str(end), KNOWLEDGE_VERSION))
                observation_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
                conn.execute(
                    """INSERT INTO visual_pattern_observations
                    (observation_id,sample_fingerprint,symbol,timeframe,observed_at_ms,
                     pattern_id,start_index,end_index,confirmation_state,evidence_json,engine_version)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(observation_id) DO UPDATE SET
                    confirmation_state=excluded.confirmation_state,
                    evidence_json=excluded.evidence_json,observed_at_ms=excluded.observed_at_ms""",
                    (observation_id, sample_fingerprint, symbol.upper(), timeframe, now,
                     pattern_id, start, end, str(event.get("confirmation_state", "CANDIDATE_ONLY")),
                     _json(event), KNOWLEDGE_VERSION),
                )
                count += 1
        return count
    finally:
        conn.close()

def record_structure_observations(
    sample_fingerprint: str, symbol: str, timeframe: str,
    observations: list[dict[str, Any]], *, db_path: str | None = None,
    observed_at_ms: int | None = None,
) -> int:
    """Persist structural levels/events with their source evidence."""
    from ..storage import connect

    if not sample_fingerprint.strip() or not symbol.strip() or not timeframe.strip():
        raise ValueError("sample_fingerprint, symbol and timeframe are required")
    known = {item["structure_id"] for item in MARKET_STRUCTURE_CATALOG}
    conn = connect(db_path) if db_path is not None else connect()
    now = observed_at_ms or int(time.time() * 1000)
    count = 0
    try:
        with conn:
            for event in observations:
                structure_id = str(event.get("structure_id", ""))
                if structure_id not in known:
                    raise ValueError(f"Unknown market structure id: {structure_id}")
                start = int(event.get("start_index", event.get("index", 0)))
                end = int(event.get("end_index", event.get("index", start)))
                identity = "|".join((sample_fingerprint, symbol.upper(), timeframe, structure_id, str(start), str(end), KNOWLEDGE_VERSION))
                observation_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
                conn.execute(
                    """INSERT INTO visual_structure_observations
                    (observation_id,sample_fingerprint,symbol,timeframe,observed_at_ms,
                     structure_id,start_index,end_index,confirmed,level_price,zone_low,
                     zone_high,evidence_json,engine_version)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(observation_id) DO UPDATE SET
                    confirmed=excluded.confirmed,level_price=excluded.level_price,
                    zone_low=excluded.zone_low,zone_high=excluded.zone_high,
                    evidence_json=excluded.evidence_json,observed_at_ms=excluded.observed_at_ms""",
                    (observation_id, sample_fingerprint, symbol.upper(), timeframe, now,
                     structure_id, start, end, 1 if event.get("confirmed") else 0,
                     event.get("level_price"), event.get("zone_low"), event.get("zone_high"),
                     _json(event), KNOWLEDGE_VERSION),
                )
                count += 1
        return count
    finally:
        conn.close()

def visual_knowledge_summary(db_path: str | None = None) -> dict[str, Any]:
    from ..storage import connect

    conn = connect(db_path) if db_path is not None else connect()
    try:
        patterns = conn.execute("SELECT COUNT(*) FROM visual_candle_pattern_knowledge").fetchone()[0]
        structures = conn.execute("SELECT COUNT(*) FROM visual_structure_knowledge").fetchone()[0]
        pattern_events = conn.execute("SELECT COUNT(*) FROM visual_pattern_observations").fetchone()[0]
        structure_events = conn.execute("SELECT COUNT(*) FROM visual_structure_observations").fetchone()[0]
        meta = conn.execute("SELECT version FROM visual_knowledge_meta WHERE namespace='engine_2'").fetchone()
        evaluations = conn.execute(
            "SELECT COUNT(*) FROM visual_pattern_evaluations WHERE validation_status='VALIDATED'"
        ).fetchone()[0]
        return {
            "version": meta[0] if meta else None,
            "candle_pattern_definitions": int(patterns),
            "market_structure_definitions": int(structures),
            "pattern_observations": int(pattern_events),
            "structure_observations": int(structure_events),
            "validated_evaluation_records": int(evaluations),
            "empirical_status": "UNVALIDATED" if not evaluations else "HAS_VALIDATED_RECORDS",
        }
    finally:
        conn.close()

__all__ = [
    "KNOWLEDGE_VERSION", "CANDLE_PATTERN_CATALOG", "MARKET_STRUCTURE_CATALOG",
    "seed_visual_knowledge", "record_pattern_observations",
    "record_structure_observations", "visual_knowledge_summary",
]
