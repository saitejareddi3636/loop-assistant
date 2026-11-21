from __future__ import annotations

import re

_DIGIT = {
    "0": "zero",
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
}

_ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]

_TENS = {
    2: "twenty",
    3: "thirty",
    4: "forty",
    5: "fifty",
    6: "sixty",
    7: "seventy",
    8: "eighty",
    9: "ninety",
}

# Optional leading "invoice"/"ticket" so we never say "invoice invoice …".
_INV = re.compile(r"(?:\binvoice\s+)?\bINV[-\s]?(\d{3,8})\b", re.IGNORECASE)
_TCK = re.compile(r"(?:\bticket\s+)?\bTCK[-\s]?([A-Z0-9]{4,12})\b", re.IGNORECASE)
_MONEY = re.compile(r"\$\s?(\d+)(?:\.(\d{2}))?\b")
_MONEY_USD = re.compile(r"\b(\d+)(?:\.(\d{2}))?\s*(?:USD|dollars?)\b", re.IGNORECASE)

_INV_COMPACT = re.compile(r"\bINV(\d{3,8})\b", re.IGNORECASE)
_TCK_COMPACT = re.compile(r"\bTCK([A-Z0-9]{4,12})\b", re.IGNORECASE)


def _spell_digits(num: str) -> str:
    return " ".join(_DIGIT.get(ch, ch) for ch in num)


def _spell_alnum(token: str) -> str:
    parts: list[str] = []
    for ch in token.upper():
        if ch.isdigit():
            parts.append(_DIGIT.get(ch, ch))
        elif ch.isalpha():
            parts.append(ch.lower())
    return " ".join(parts)


def _number_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens, rem = divmod(n, 10)
        return _TENS[tens] + (f"-{_ONES[rem]}" if rem else "")
    return _spell_digits(str(n))


def _money_words(dollars: str, cents: str | None) -> str:
    """Deterministic currency phrasing, including non-zero cents ($29.50)."""
    whole = int(dollars)
    dollar_words = _number_words(whole)
    unit = "dollar" if whole == 1 else "dollars"
    if cents and cents != "00":
        cent_n = int(cents)
        cent_words = _number_words(cent_n)
        cent_unit = "cent" if cent_n == 1 else "cents"
        return f"{dollar_words} {unit} and {cent_words} {cent_unit}"
    return f"{dollar_words} {unit}"


def normalize_transcript_ids(text: str) -> str:
    """Restore canonical ID hyphens after STT drops them (INV1042 → INV-1042)."""

    def inv(match: re.Match[str]) -> str:
        return f"INV-{match.group(1)}"

    def tck(match: re.Match[str]) -> str:
        return f"TCK-{match.group(1).upper()}"

    out = _INV_COMPACT.sub(inv, text)
    out = _TCK_COMPACT.sub(tck, out)
    return out


def normalize_for_speech(text: str) -> str:
    """Deterministic TTS pronunciation helpers for IDs and currency."""

    def inv_sub(match: re.Match[str]) -> str:
        return f"invoice I N V {_spell_digits(match.group(1))}"

    def tck_sub(match: re.Match[str]) -> str:
        return f"ticket T C K {_spell_alnum(match.group(1))}"

    def money_sub(match: re.Match[str]) -> str:
        return _money_words(match.group(1), match.group(2))

    out = _INV.sub(inv_sub, text)
    out = _TCK.sub(tck_sub, out)
    out = _MONEY.sub(money_sub, out)
    out = _MONEY_USD.sub(money_sub, out)
    return out
