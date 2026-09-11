"""
APEX Quant OS - Strategy Engine Shared SMC Utilities
Common structural primitives used by the HTF / MTF / LTF strategy engines and
the MTF trailing engine: event classification, keyzone selection, mitigation
checks and swing price extraction.
"""

from typing import List, Optional, Sequence, Tuple

from market_language.market_structure import Candle
from market_language.key_zones import PriceZone, ZoneType


# ---------------------------------------------------------------------------
# Event classification sets (string-safe: EventType is a str-Enum)
# ---------------------------------------------------------------------------

BULLISH_EXTERNAL_EVENTS = {"EXTERNAL_BOS_BULLISH", "EXTERNAL_CHOCH_BULLISH"}
BEARISH_EXTERNAL_EVENTS = {"EXTERNAL_BOS_BEARISH", "EXTERNAL_CHOCH_BEARISH"}

BULLISH_SHIFT_EVENTS = {
    "EXTERNAL_BOS_BULLISH", "EXTERNAL_CHOCH_BULLISH",
    "INTERNAL_BOS_BULLISH", "INTERNAL_CHOCH_BULLISH",
}
BEARISH_SHIFT_EVENTS = {
    "EXTERNAL_BOS_BEARISH", "EXTERNAL_CHOCH_BEARISH",
    "INTERNAL_BOS_BEARISH", "INTERNAL_CHOCH_BEARISH",
}

BULLISH_ZONE_TYPES = {ZoneType.BULLISH_OB, ZoneType.BULLISH_FVG}
BEARISH_ZONE_TYPES = {ZoneType.BEARISH_OB, ZoneType.BEARISH_FVG}


def event_name(evt) -> str:
    """Returns the plain string name of a structural event (enum-safe)."""
    return str(getattr(evt, "event_type", "")).replace("EventType.", "")


def swing_price(swing) -> Optional[float]:
    """Extracts the float price from a Swing anchor (None-safe)."""
    if swing is None:
        return None
    point = getattr(swing, "price_point", None)
    if point is None:
        return None
    return float(point.price)


def swing_timestamp(swing) -> int:
    if swing is None:
        return 0
    point = getattr(swing, "price_point", None)
    if point is None:
        return 0
    return int(point.timestamp)


def latest_external_bias_event(events: Sequence) -> Tuple[str, str, Optional[object]]:
    """
    Scans events newest -> oldest for the last EXTERNAL BOS/CHoCH.
    Returns (bias, event_name, event) where bias is BULLISH / BEARISH / NEUTRAL.
    """
    for evt in reversed(list(events)):
        name = event_name(evt)
        if name in BULLISH_EXTERNAL_EVENTS:
            return "BULLISH", name, evt
        if name in BEARISH_EXTERNAL_EVENTS:
            return "BEARISH", name, evt
    return "NEUTRAL", "NONE", None


def latest_shift_event(events: Sequence, direction: str):
    """
    Returns the newest structural shift event (BOS or CHoCH, internal or
    external) in the requested direction, or None.
    """
    wanted = BULLISH_SHIFT_EVENTS if direction == "BULLISH" else BEARISH_SHIFT_EVENTS
    for evt in reversed(list(events)):
        if event_name(evt) in wanted:
            return evt
    return None


def has_opposing_shift(events: Sequence, direction: str, since_timestamp: int = 0) -> bool:
    """True if any structural shift AGAINST the trade direction occurred after the given ts."""
    opposing = BEARISH_SHIFT_EVENTS if direction == "BULLISH" else BULLISH_SHIFT_EVENTS
    for evt in reversed(list(events)):
        ts = int(getattr(evt, "trigger_timestamp", 0))
        if ts <= since_timestamp:
            break
        if event_name(evt) in opposing:
            return True
    return False


# ---------------------------------------------------------------------------
# Keyzone (OB / FVG) helpers
# ---------------------------------------------------------------------------

def bias_zone_types(direction: str):
    return BULLISH_ZONE_TYPES if direction == "BULLISH" else BEARISH_ZONE_TYPES


def zone_invalidated(zone: PriceZone, candles: List[Candle], direction: str) -> bool:
    """
    A zone is invalidated when price CLOSES through its far boundary after creation.
    Bullish zone invalidated on close below zone low; bearish on close above zone high.
    """
    for c in candles:
        if c.timestamp <= zone.creation_timestamp:
            continue
        if direction == "BULLISH" and c.close < zone.low_price:
            return True
        if direction == "BEARISH" and c.close > zone.high_price:
            return True
    return False


def zone_tapped(zone: PriceZone, candles: List[Candle], direction: str) -> bool:
    """
    True when price has traded INTO the zone after its creation (wick touch of
    the near boundary) without necessarily closing through it.
    """
    for c in candles:
        if c.timestamp <= zone.creation_timestamp:
            continue
        if direction == "BULLISH" and c.low <= zone.high_price:
            return True
        if direction == "BEARISH" and c.high >= zone.low_price:
            return True
    return False


def select_keyzone(
    zones: Sequence[PriceZone],
    candles: List[Candle],
    direction: str,
    reference_price: float,
) -> Optional[PriceZone]:
    """
    Selects the newest unmitigated bias-aligned zone sitting on the tradeable
    side of price (below price for bullish pullback zones, above for bearish).
    """
    wanted = bias_zone_types(direction)
    ordered = sorted(
        (z for z in zones if z.zone_type in wanted),
        key=lambda z: z.creation_timestamp,
        reverse=True,
    )
    for zone in ordered:
        if direction == "BULLISH" and zone.high_price >= reference_price:
            continue  # zone must sit below price to be a pullback destination
        if direction == "BEARISH" and zone.low_price <= reference_price:
            continue
        if zone_invalidated(zone, candles, direction):
            continue
        return zone
    return None


def average_range(candles: List[Candle], period: int = 14) -> float:
    """Simple average candle range used for stop-loss buffers."""
    if not candles:
        return 0.0
    window = candles[-period:]
    ranges = [c.high - c.low for c in window]
    return sum(ranges) / len(ranges) if ranges else 0.0
