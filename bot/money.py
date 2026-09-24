"""The one money parser and the one money formatter.

Four hand-rolled copies of this used to live in the routers (`transactions.parse_amount`,
`wizard._amount_pos`, `wizard._number`, `months._num`) and all four did the same thing:
strip spaces and commas, then `float()`. That reads "50.000" — which is how this product's
own web app prints fifty thousand — as fifty, and books a thousand-fold error into the
ledger without a word of complaint. It also rejected the dot-grouped figure outright at the
month-close prompt, where the owner is copying balances straight off the web app screen.

So the rules here are explicit rather than incidental:

* Separators come in groups of three digits  → they are thousands grouping, drop them.
  `1.500.000` · `1,500,000` · `1 500 000` · `50.000` all mean the same number.
* One separator with one or two trailing digits → it is a decimal mark. `1.5` · `1,25`.
* Both `.` and `,` present → the LAST one is the decimal mark and the other groups, which
  covers the European `1.500,75` and the Anglo `1,500.75` without having to guess a locale.
* Shorthand the owner actually types: `50k`, `1.5m`, `250 ming`, `2 mln`, `3 mlrd`.
* A trailing unit (`UZS`, `soʻm`, `sum`) is ignored, so `fmt_money`'s own output parses back.

`fmt_money` groups with plain spaces. A space is unambiguous in both languages, it is what
the region writes, and — unlike the comma this used to emit — it survives a round trip
through `parse_amount` if the owner ever copies a figure out of one screen and into another.
"""
import re

from .config import CURRENCY

# Every space Telegram clients can deliver when a human types or pastes a grouped figure:
# ordinary, NBSP (iOS keyboards), narrow NBSP and thin space (copied from a web page).
_SPACES = str.maketrans({" ": "", " ": "", " ": "", " ": "", "_": ""})

# Trailing units to ignore, longest first so "soʻm" is not half-eaten by "som". All three
# apostrophe forms are here because the owner's keyboard produces whichever it produces.
_UNITS = ("uzs", "soʻm", "soʼm", "so'm", "som", "sum")

# Multiplier suffixes, longest first: "ming" must be tested before "m", or "250 ming"
# becomes 250 million. Uzbek and English shorthand share the table because the owner
# switches between them mid-sentence.
_MULTIPLIERS = (
    ("milliard", 1_000_000_000.0),
    ("million", 1_000_000.0),
    ("mlrd", 1_000_000_000.0),
    ("ming", 1_000.0),
    ("mln", 1_000_000.0),
    ("mil", 1_000_000.0),
    ("md", 1_000_000_000.0),
    ("m", 1_000_000.0),
    ("k", 1_000.0),
)

_DIGITS = re.compile(r"\d[\d.,]*")


def _digits_to_float(body: str) -> float | None:
    """Turn a bare digit/separator string into a number, resolving grouping vs decimals."""
    if not _DIGITS.fullmatch(body):
        return None
    dots, commas = body.count("."), body.count(",")
    if dots and commas:
        dec = "." if body.rfind(".") > body.rfind(",") else ","
        body = body.replace("," if dec == "." else ".", "").replace(dec, ".")
    elif dots + commas == 1:
        sep = "." if dots else ","
        # Exactly three trailing digits is a thousands group. UZS has no circulating
        # sub-unit, so "1.500" is one and a half thousand, never one and a half.
        body = body.replace(sep, "" if len(body.rsplit(sep, 1)[1]) == 3 else ".")
    elif dots + commas > 1:
        sep = "." if dots else ","
        head, *groups = body.split(sep)
        if not head or any(len(g) != 3 for g in groups):
            return None  # "12.34.567" is not a number anyone meant to type
        body = body.replace(sep, "")
    try:
        return float(body)
    except ValueError:
        return None


def _parse(text: str | None) -> float | None:
    raw = (text or "").strip().lower().translate(_SPACES)
    if not raw:
        return None
    sign = 1.0
    if raw[0] in "+-":
        sign, raw = (-1.0 if raw[0] == "-" else 1.0), raw[1:]
    for unit in _UNITS:
        if raw.endswith(unit):
            raw = raw[: -len(unit)]
            break
    factor = 1.0
    for suffix, mult in _MULTIPLIERS:
        if raw.endswith(suffix):
            raw, factor = raw[: -len(suffix)], mult
            break
    value = _digits_to_float(raw)
    if value is None:
        return None
    # 1.1 * 1000 is 1100.0000000000002 in binary floating point; the owner typed "1.1k" and
    # expects to see 1 100, so collapse the noise before anyone formats or POSTs it.
    return round(sign * value * factor, 2)


def parse_amount(text: str | None) -> float | None:
    """A money amount the backend will accept: strictly positive, or None."""
    value = _parse(text)
    return value if value is not None and value > 0 else None


def parse_number(text: str | None) -> float | None:
    """Any number, including 0 and negatives — an end-of-month balance can be either."""
    return _parse(text)


def fmt_num(amount) -> str:
    """"1 500 000" — the figure alone, for "0 of 1 213 450 UZS" where the unit is said once."""
    if amount is None:
        return "—"
    try:
        n = float(amount)
    except (TypeError, ValueError):
        from .keyboards import esc
        return esc(amount)
    return f"{n:,.0f}".replace(",", " ")


def fmt_money(amount) -> str:
    """"1 500 000 UZS". Space-grouped, no fractional part (UZS has no circulating coin)."""
    if amount is None:
        return "—"
    number = fmt_num(amount)
    try:
        float(amount)
    except (TypeError, ValueError):
        return number  # prose where a number belongs, already escaped
    return f"{number} {CURRENCY}"
