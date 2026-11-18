"""Typed values: turning printed text into data, strictly.

A value type reads the whole of a printed string or fails. "46.15 ± 14.67" is a `mean_sd`;
it is not an integer, and it is not a decimal with some text left over. Strictness is what lets
the extractor say a value was extracted: the printed text and the value describe each other.

Decimals come out as strings ("41.1", "627.00") so they keep the precision they were printed
with. Dates come out as ISO strings. Compound values come out as small objects.
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


COMPONENTS: dict[str, tuple[str, ...]] = {
    "money": ("amount", "currency"),
    "count_percent": ("count", "percent"),
    "mean_sd": ("mean", "sd"),
    "estimate_interval": ("estimate", "lower", "upper"),
    "p_value": ("comparator", "value"),
}


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
    num = _number_pattern(vt)
    sym = "|".join(re.escape(s) for s in [*SYMBOLS, "$"]) + r"|[A-Z]{3}"
    m = re.fullmatch(rf"(?P<pre>{sym})?\s*(?P<num>{num})\s*(?P<post>{sym})?", text)
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
    return {"amount": _dec(_number(m.group("num"), vt)), "currency": currency}


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
    match vt.kind:
        case "text":
            value: Any = text
        case "integer":
            n = _number(text, vt)
            if n != n.to_integral_value() or _separators(vt.numbers)[1] in text:
                raise ParseError(f"{text!r} is not a whole number")
            value = int(n)
        case "decimal":
            value = _dec(_number(text, vt))
        case "percent":
            value = _dec(_number(text.removesuffix("%").strip(), vt))
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
    return Parsed(value)


def same_value(a: Any, b: Any) -> bool:
    """Whether two values are equal, comparing decimal strings by number ("41.10" == "41.1")."""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same_value(a[k], b[k]) for k in a)
    if isinstance(a, str) and isinstance(b, str):
        try:
            return Decimal(a) == Decimal(b)
        except InvalidOperation:
            return a == b
    if isinstance(a, (int, Decimal)) and isinstance(b, (int, str, Decimal)):
        try:
            return Decimal(str(a)) == Decimal(str(b))
        except InvalidOperation:
            return False
    return a == b
