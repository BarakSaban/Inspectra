"""Normalisation of identifiers that arrive in inconsistent shapes (ints, floats, 'null', padded strings)."""

_EMPTY = {"", "none", "null", "nan"}


def normalize_id(value):
    """GTFS/SIRI id as a clean string: stripped, '12.0' -> '12', and None/'null'/'nan' -> None."""
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return None if text.lower() in _EMPTY else text


def normalize_line_ref(value):
    """SIRI LineRef may be namespaced ('ISR:44290'); keep the last segment."""
    text = normalize_id(value)
    return text.split(":")[-1] if text else None


def normalize_route_name(value):
    """Public bus number without spaces ('2 A' -> '2A')."""
    text = normalize_id(value)
    return text.replace(" ", "") if text else None
