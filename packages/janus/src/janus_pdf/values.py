"""Typed values: turning printed text into data, strictly.

A value type reads the whole of a printed string or fails. "46.15 ± 14.67" is a `mean_sd`;
it is not an integer, and it is not a decimal with some text left over. Strictness is what lets
the extractor say a value was extracted: the printed text and the value describe each other.

Decimals come out as strings ("41.1", "627.00") so they keep the precision they were printed
with. Dates come out as ISO strings. Compound values come out as small objects.

Each type also says when two of its values are equal (`ValueType.same`): text after collapsing
whitespace, numbers by value, dates and codes exactly, and compound values part by part. There is
no comparison without a type, because "001" and "1" are the same integer and different text.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

Kind = Literal[
    "text",
    "integer",
    "decimal",
    "percent",
    "date",
    "money",
    "count_percent",
    "mean_sd",
    "estimate_interval",
    "p_value",
]
KINDS: tuple[str, ...] = Kind.__args__  # type: ignore[attr-defined]

ABSENT = ("NR", "N/R", "NA", "N/A", "not reported", "\u2014", "\u2013", "-")

# How a scalar compares: "text" after collapsing whitespace, "number" by value, "exact" as is.
Scalar = Literal["text", "number", "exact"]
_SCALARS: dict[str, Scalar] = {
    "text": "text",
    "integer": "number",
    "decimal": "number",
    "percent": "number",
    "date": "exact",
}


class ParseError(ValueError):
    """The printed text is not a value of the declared type."""


@dataclass(frozen=True, slots=True)
class ValueType:
    """A declared type and how its values are printed.

    `numbers` is a sample number showing the group and decimal separators, such as "1,234.56"
    (the default), "1.234,56" or "1 234,56". `formats` are date patterns such as "D MMMM YYYY"
    or "DD/MM/YYYY", tried in order. `currency` is an ISO 4217 code. `pick` takes one component
    of a compound value: `count_percent` with `pick: count` is an integer.
    """

    kind: Kind = "text"
    numbers: str = "1,234.56"
    formats: tuple[str, ...] = ()
    locale: str = "en"
    currency: str | None = None
    pick: str | None = None
    absent: tuple[str, ...] = ABSENT
    bounds: Literal["share", "any"] = "share"

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown type {self.kind!r}; known types: {', '.join(KINDS)}")
        _separators(self.numbers)
        if self.locale not in MONTHS:
            raise ValueError(f"unknown locale {self.locale!r}; known: {', '.join(MONTHS)}")
        if self.pick is not None and self.pick not in COMPONENTS.get(self.kind, ()):
            raise ValueError(
                f"{self.kind} has no component {self.pick!r}; "
                f"components: {', '.join(COMPONENTS.get(self.kind, ())) or 'none'}"
            )
        for pattern in self.formats:
            _date_regex(pattern, self.locale)  # fails early on a bad pattern
        if self.bounds not in ("share", "any"):
            raise ValueError(f"bounds is share or any, not {self.bounds!r}")
        if self.bounds != "share" and self.kind != "percent":
            raise ValueError("bounds goes with percent")

    def scalar(self, component: str | None = None) -> Scalar:
        """How a value of this type, or the named component of one, compares."""
        part = component or self.pick
        if part is None:
            if self.kind in PARTS:
                raise ValueError(
                    f"a {self.kind} has parts; name one of {', '.join(PARTS[self.kind])}"
                )
            return _SCALARS[self.kind]
        parts = PARTS.get(self.kind, {})
        if part not in parts:
            raise ValueError(f"{self.kind} has no component {part!r}")
        return parts[part]

    def same(self, a: Any, b: Any, component: str | None = None) -> bool:
        """Whether `a` and `b` are the same value of this type, or of its named component. None,
        the not-reported value, equals only None."""
        if a is None or b is None:
            return a is None and b is None
        if component is not None:
            return _same(self.scalar(component), a, b)
        if self.pick is None and self.kind in PARTS:
            parts = PARTS[self.kind]
            return (
                isinstance(a, dict)
                and isinstance(b, dict)
                and a.keys() == b.keys() == parts.keys()
                and all(_same(how, a[k], b[k]) for k, how in parts.items())
            )
        return _same(self.scalar(), a, b)


def as_number(value: Any) -> Decimal | None:
    """`value` as a finite decimal: an int, a Decimal, a float, or a string that is a plain
    number such as "627.00" or "-3". Anything else, booleans included, is None."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
        return None
    if isinstance(value, str) and not re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", value):
        return None
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _same(how: Scalar, a: Any, b: Any) -> bool:
    if how == "number":
        x, y = as_number(a), as_number(b)
        return x is not None and x == y
    if not (isinstance(a, str) and isinstance(b, str)):
        return False
    if how == "text":
        return " ".join(a.split()) == " ".join(b.split())
    return a == b


# The parts of each compound type, and how each part compares.
PARTS: dict[str, dict[str, Scalar]] = {
    "money": {"amount": "number", "currency": "exact"},
    "count_percent": {"count": "number", "percent": "number"},
    "mean_sd": {"mean": "number", "sd": "number"},
    "estimate_interval": {"estimate": "number", "lower": "number", "upper": "number"},
    "p_value": {"comparator": "exact", "value": "number"},
}
COMPONENTS: dict[str, tuple[str, ...]] = {kind: tuple(parts) for kind, parts in PARTS.items()}


@dataclass(frozen=True, slots=True)
class Parsed:
    value: Any  # None when the page prints a not-reported mark
    absent: bool = False
    notes: tuple[str, ...] = field(default=())


# ---------------------------------------------------------------------------------------------
# Printed text


def clean(text: str) -> str:
    """NFKC, one space for any run of whitespace, minus signs and dashes between digits folded."""
    text = unicodedata.normalize("NFKC", text).replace("\u2212", "-")
    return re.sub(r"\s+", " ", text).strip()


def _separators(sample: str) -> tuple[str, str]:
    """(group, decimal) from a sample like "1.234,56"."""
    m = re.fullmatch(r"1([^\d]?)234([^\d])56", clean(sample))
    if not m or m.group(1) == m.group(2) or m.group(2) not in ".,":
        raise ValueError(f"numbers sample {sample!r} must look like 1,234.56 or 1.234,56")
    return m.group(1), m.group(2)


def _number_pattern(vt: ValueType) -> str:
    group, dec = _separators(vt.numbers)
    g = re.escape(group) if group else ""
    grouped = rf"\d{{1,3}}(?:{g}\d{{3}})+" if group else r"(?!)"
    return rf"[-+]?(?:{grouped}|\d+)(?:{re.escape(dec)}\d+)?|[-+]?{re.escape(dec)}\d+"


def _number(text: str, vt: ValueType) -> Decimal:
    group, dec = _separators(vt.numbers)
    if not re.fullmatch(_number_pattern(vt), text):
        raise ParseError(f"{text!r} is not a number printed like {vt.numbers}")
    if group:
        text = text.replace(group, "")
    text = text.replace(dec, ".")
    if text.startswith((".", "-.", "+.")):
        text = text.replace(".", "0.", 1)
    try:
        return Decimal(text)
    except InvalidOperation as exc:  # pragma: no cover - the regex excludes this
        raise ParseError(f"{text!r} is not a number") from exc


def _dec(value: Decimal) -> str:
    return format(value, "f")


def _negative(value: Decimal, text: str) -> Decimal:
    """An amount printed in parentheses, as accounts print a negative one."""
    if value < 0:
        raise ParseError(f"{text!r} has both a sign and parentheses")
    return -value


def _signed(text: str, vt: ValueType) -> tuple[Decimal, tuple[str, ...]]:
    """A number with an optional sign, or in parentheses for a negative one: "-12", "+3.5",
    "\u2212 4" (the minus sign is folded by `clean`), "(1,250.00)"."""
    m = re.fullmatch(r"\(\s*(.*?)\s*\)", text)
    if m:
        return _negative(_number(m.group(1), vt), text), (
            f"{text!r} is in parentheses, read as negative",
        )
    return _number(re.sub(r"^([-+])\s+", r"\1", text), vt), ()


# ---------------------------------------------------------------------------------------------
# Dates

MONTHS: dict[str, tuple[tuple[str, ...], ...]] = {
    "en": (
        ("january", "jan"),
        ("february", "feb"),
        ("march", "mar"),
        ("april", "apr"),
        ("may",),
        ("june", "jun"),
        ("july", "jul"),
        ("august", "aug"),
        ("september", "sep", "sept"),
        ("october", "oct"),
        ("november", "nov"),
        ("december", "dec"),
    ),
    "de": (
        ("januar", "jan", "jänner"),
        ("februar", "feb"),
        ("märz", "mär", "mrz"),
        ("april", "apr"),
        ("mai",),
        ("juni", "jun"),
        ("juli", "jul"),
        ("august", "aug"),
        ("september", "sep", "sept"),
        ("oktober", "okt"),
        ("november", "nov"),
        ("dezember", "dez"),
    ),
    "fr": (
        ("janvier", "janv"),
        ("février", "févr", "fevrier"),
        ("mars",),
        ("avril", "avr"),
        ("mai",),
        ("juin",),
        ("juillet", "juil"),
        ("août", "aout"),
        ("septembre", "sept"),
        ("octobre", "oct"),
        ("novembre", "nov"),
        ("décembre", "déc", "decembre"),
    ),
    "nl": (
        ("januari", "jan"),
        ("februari", "feb"),
        ("maart", "mrt"),
        ("april", "apr"),
        ("mei",),
        ("juni", "jun"),
        ("juli", "jul"),
        ("augustus", "aug"),
        ("september", "sep", "sept"),
        ("oktober", "okt"),
        ("november", "nov"),
        ("december", "dec"),
    ),
    "es": (
        ("enero", "ene"),
        ("febrero", "feb"),
        ("marzo", "mar"),
        ("abril", "abr"),
        ("mayo", "may"),
        ("junio", "jun"),
        ("julio", "jul"),
        ("agosto", "ago"),
        ("septiembre", "sep", "sept", "setiembre"),
        ("octubre", "oct"),
        ("noviembre", "nov"),
        ("diciembre", "dic"),
    ),
}

# Formats tried when a date type declares none. All name the month, or are ISO, so the order
# of day and month is never guessed. "11/04/2026" needs a declared format.
DEFAULT_FORMATS = ("YYYY-MM-DD", "D MMMM YYYY", "MMMM D, YYYY", "D MMMM, YYYY", "MMMM YYYY")

_DATE_TOKEN = re.compile(r"YYYY|YY|MMMM|MMM|MM|M|DD|D")


def _date_regex(pattern: str, locale: str) -> re.Pattern[str]:
    names = sorted({n for month in MONTHS[locale] for n in month}, key=len, reverse=True)
    month_name = "|".join(re.escape(n) for n in names)
    pieces = {
        "YYYY": r"(?P<year>\d{4})",
        "YY": r"(?P<yy>\d{2})",
        "MMMM": rf"(?P<mname>{month_name})\.?",
        "MMM": rf"(?P<mname>{month_name})\.?",
        "MM": r"(?P<month>\d{2})",
        "M": r"(?P<month>\d{1,2})",
        "DD": r"(?P<day>\d{2})",
        "D": r"(?P<day>\d{1,2})(?:st|nd|rd|th|\.)?",
    }
    out, pos, seen = [], 0, set()
    for m in _DATE_TOKEN.finditer(pattern):
        out.append(re.escape(pattern[pos : m.start()]).replace(r"\ ", r"\s*"))
        token = m.group()
        group = pieces[token].split("<", 1)[1].split(">", 1)[0]
        if group in seen:
            raise ValueError(f"date format {pattern!r} names {token} twice")
        seen.add(group)
        out.append(pieces[token])
        pos = m.end()
    out.append(re.escape(pattern[pos:]).replace(r"\ ", r"\s*"))
    if not ({"year", "yy"} & seen and {"month", "mname"} & seen):
        raise ValueError(f"date format {pattern!r} needs a year and a month")
    return re.compile("".join(out), re.IGNORECASE)


def _date(text: str, vt: ValueType) -> str:
    formats = vt.formats or DEFAULT_FORMATS
    for pattern in formats:
        m = _date_regex(pattern, vt.locale).fullmatch(text)
        if not m:
            continue
        g = m.groupdict()
        year = int(g["year"]) if g.get("year") else 2000 + int(g["yy"])
        if g.get("mname"):
            name = g["mname"].casefold().rstrip(".")
            month = next(i + 1 for i, names in enumerate(MONTHS[vt.locale]) if name in names)
        else:
            month = int(g["month"])
        day = int(g["day"]) if g.get("day") else 1
        try:
            return date(year, month, day).isoformat()
        except ValueError as exc:
            raise ParseError(f"{text!r} matches {pattern!r} but is not a real date") from exc
    if not vt.formats and re.fullmatch(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", text):
        raise ParseError(
            f"{text!r} is a numeric date; declare its format, such as DD/MM/YYYY or MM/DD/YYYY"
        )
    raise ParseError(f"{text!r} is not a date in the format(s) {', '.join(formats)}")


# ---------------------------------------------------------------------------------------------
# Money

SYMBOLS = {"£": "GBP", "€": "EUR", "¥": "JPY", "₹": "INR", "₩": "KRW", "₺": "TRY", "zł": "PLN"}
DOLLAR_CODES = {"USD", "CAD", "AUD", "NZD", "SGD", "HKD", "MXN"}


def _money(text: str, vt: ValueType) -> dict[str, str]:
    whole = re.fullmatch(r"\(\s*([^()]*?)\s*\)", text)
    if whole:  # "(£40.00)": the amount and its currency in parentheses
        money = _money(whole.group(1), vt)
        money["amount"] = _dec(_negative(Decimal(money["amount"]), text))
        return money
    num = _number_pattern(vt)
    sym = "|".join(re.escape(s) for s in [*SYMBOLS, "$"]) + r"|[A-Z]{3}"
    m = re.fullmatch(
        rf"(?P<pre>{sym})?\s*(?P<open>\(\s*)?(?P<num>{num})(?(open)\s*\))\s*(?P<post>{sym})?", text
    )
    if not m or (m.group("pre") and m.group("post")):
        raise ParseError(f"{text!r} is not an amount printed like {vt.numbers}")
    printed = m.group("pre") or m.group("post")
    currency = vt.currency
    if printed:
        if printed == "$":
            if currency not in DOLLAR_CODES:
                raise ParseError(f"{text!r} prints $; declare which dollar, such as USD")
        else:
            code = SYMBOLS.get(printed, printed)
            if currency and code != currency:
                raise ParseError(f"{text!r} is in {code}, the field declares {currency}")
            currency = code
    if currency is None:
        raise ParseError(f"{text!r} prints no currency and the field declares none")
    amount = _number(m.group("num"), vt)
    if m.group("open"):
        amount = _negative(amount, text)
    return {"amount": _dec(amount), "currency": currency}


# ---------------------------------------------------------------------------------------------
# Compound values


def _count_percent(text: str, vt: ValueType) -> dict[str, Any]:
    num = _number_pattern(vt)
    m = re.fullmatch(rf"(?P<n>\d[\d,. ]*)\s*\(\s*(?P<p>{num})\s*%?\s*\)", text)
    if not m:
        raise ParseError(f"{text!r} is not a count with a percentage, such as 12 (34.5%)")
    count = _number(m.group("n").strip(), vt)
    percent = _number(m.group("p"), vt)
    if count != count.to_integral_value():
        raise ParseError(f"the count in {text!r} is not a whole number")
    if not 0 <= percent <= 100:
        raise ParseError(f"the percentage in {text!r} is outside 0 to 100")
    return {"count": int(count), "percent": _dec(percent)}


def _mean_sd(text: str, vt: ValueType) -> dict[str, str]:
    num = _number_pattern(vt)
    m = re.fullmatch(
        rf"(?P<m>{num})\s*(?:±|\+/-|\+-)\s*(?P<s>{num})|(?P<m2>{num})\s*\(\s*(?P<s2>{num})\s*\)",
        text,
    )
    if not m:
        raise ParseError(f"{text!r} is not a mean with an SD, such as 46.2 ± 14.7")
    mean = _number(m.group("m") or m.group("m2"), vt)
    sd = _number(m.group("s") or m.group("s2"), vt)
    if sd < 0:
        raise ParseError(f"the SD in {text!r} is negative")
    return {"mean": _dec(mean), "sd": _dec(sd)}


def _estimate_interval(text: str, vt: ValueType) -> dict[str, str]:
    num = _number_pattern(vt)
    dashes = "\u2013|\u2014|-"
    sep = (
        rf"\s*(?:to|,|;|{dashes})\s*"
        if _separators(vt.numbers)[1] == "."
        else rf"\s*(?:to|;|{dashes})\s*"
    )
    level = r"(?:\d{2}(?:\.\d)?\s*%\s*(?:CI|confidence interval|CrI)\s*[:,]?\s*)?"
    m = re.fullmatch(
        rf"(?P<e>{num})\s*[(\[]\s*{level}(?P<lo>{num}){sep}(?P<hi>{num})\s*[)\]]",
        text,
        re.IGNORECASE,
    )
    if not m:
        raise ParseError(
            f"{text!r} is not an estimate with an interval, such as 1.42 (1.10 to 1.83)"
        )
    e, lo, hi = (_number(m.group(k), vt) for k in ("e", "lo", "hi"))
    if not lo <= e <= hi:
        raise ParseError(f"the estimate in {text!r} is outside its interval")
    return {"estimate": _dec(e), "lower": _dec(lo), "upper": _dec(hi)}


def _p_value(text: str, vt: ValueType) -> dict[str, str]:
    num = _number_pattern(vt)
    m = re.fullmatch(rf"(?:p\s*)?(?P<c>[<>=≤≥]|<=|>=)?\s*(?P<v>{num})", text, re.IGNORECASE)
    if not m:
        raise ParseError(f"{text!r} is not a p-value, such as P < 0.001 or 0.04")
    value = _number(m.group("v"), vt)
    if not 0 <= value <= 1:
        raise ParseError(f"the p-value in {text!r} is outside 0 to 1")
    comparator = {"≤": "<=", "≥": ">="}.get(m.group("c") or "=", m.group("c") or "=")
    return {"comparator": comparator, "value": _dec(value)}


# ---------------------------------------------------------------------------------------------


def parse(printed: str, vt: ValueType) -> Parsed:
    """The value `printed` stands for under `vt`, or ParseError."""
    text = clean(printed)
    if not text:
        raise ParseError("nothing is printed there")
    if text.casefold() in {a.casefold() for a in vt.absent} and vt.kind != "text":
        return Parsed(None, absent=True, notes=(f"printed as {text!r}",))
    notes: tuple[str, ...] = ()
    match vt.kind:
        case "text":
            value: Any = text
        case "integer":
            n, notes = _signed(text, vt)
            if n != n.to_integral_value() or _separators(vt.numbers)[1] in text:
                raise ParseError(f"{text!r} is not a whole number")
            value = int(n)
        case "decimal":
            n, notes = _signed(text, vt)
            value = _dec(n)
        case "percent":
            n, notes = _signed(re.sub(r"\s*%(?=\)?$)", "", text), vt)
            if vt.bounds == "share" and not 0 <= n <= 100:
                raise ParseError(
                    f"{text!r} is outside 0 to 100; a change or a ratio is `percent any`"
                )
            value = _dec(n)
        case "date":
            value = _date(text, vt)
        case "money":
            value = _money(text, vt)
        case "count_percent":
            value = _count_percent(text, vt)
        case "mean_sd":
            value = _mean_sd(text, vt)
        case "estimate_interval":
            value = _estimate_interval(text, vt)
        case "p_value":
            value = _p_value(text, vt)
    if vt.pick is not None and isinstance(value, dict):
        value = value[vt.pick]
    return Parsed(value, notes=notes)
