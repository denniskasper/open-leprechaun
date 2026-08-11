"""The one JSON discipline every monetary or quantity field shares: fixed
point end to end. A value is parsed exactly from a decimal string and
answered as one, never a float in either direction; each router keeps its own
Annotated type because the bounds (gt/ge/signed) are that field's judgement,
but the refusal of a JSON number is this single function's."""


def decimal_text_only(value: object) -> object:
    """Refuse a JSON number where a fixed-point value belongs: it has been
    through — or is one parse away from — a binary float, so only a string
    states the digits exactly. Decimals pass untouched; responses are built
    from them."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        raise ValueError("a fixed-point value crosses JSON as a decimal string, not a number")
    return value
