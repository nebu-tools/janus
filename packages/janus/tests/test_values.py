import pytest

from janus_pdf.spec import SpecError, value_type
from janus_pdf.values import ParseError, ValueType, parse, same_value


@pytest.mark.parametrize(
    ("printed", "type_", "value"),
    [
        ("12 (34.5%)", "count_percent", {"count": 12, "percent": "34.5"}),
        ("146 (41.1)", "count_percent count", 146),
        ("4.6 ± 1.2", "mean_sd", {"mean": "4.6", "sd": "1.2"}),
        ("14.2 (3.1)", "mean_sd sd", "3.1"),
        ("1.42 (1.10 to 1.83)", "estimate_interval", {"estimate": "1.42", "lower": "1.10", "upper": "1.83"}),
        ("−0.52 [−0.91, −0.13]", "estimate_interval lower", "-0.91"),  # noqa: RUF001
        ("2.0 (95% CI 1.1–3.0)", "estimate_interval upper", "3.0"),  # noqa: RUF001
        ("P < 0.001", "p_value", {"comparator": "<", "value": "0.001"}),
        ("p = .03", "p_value value", "0.03"),
        ("1,234", "integer", 1234),
        ("1.234,56", "decimal 1.234,56", "1234.56"),
        ("1 234,56", "decimal 1 234,56", "1234.56"),
        ("41.1%", "percent", "41.1"),
        ("£627.00", "money GBP", {"amount": "627.00", "currency": "GBP"}),
        ("3.280,92 EUR", "money 1.234,56", {"amount": "3280.92", "currency": "EUR"}),
        ("1.085,50 €", "money EUR 1.234,56", {"amount": "1085.50", "currency": "EUR"}),
        ("12 March 2026", "date", "2026-03-12"),
        ("March 12, 2026", "date", "2026-03-12"),
        ("11/04/2026", "date DD/MM/YYYY", "2026-04-11"),
        ("04/11/2026", "date MM/DD/YYYY", "2026-04-11"),
        ("n/a", "integer", None),
    ],
)  # fmt: skip
def test_reads(printed, type_, value):
    assert parse(printed, value_type(type_)).value == value


def test_a_not_reported_mark_reads_as_none_with_a_note():
    parsed = parse("N/A", value_type("integer"))
    assert parsed.value is None and parsed.absent and parsed.notes == ("printed as 'N/A'",)
    assert parse("N/A", value_type("text")).value == "N/A"


def test_locale_dates():
    vt = ValueType("date", formats=("D. MMMM YYYY",), locale="de")
    assert parse("3. März 2026", vt).value == "2026-03-03"


@pytest.mark.parametrize(
    ("printed", "type_"),
    [
        ("mm", "mean_sd"),  # a unit, not a value
        ("12.5", "integer"),
        ("11/04/2026", "date"),  # day and month order is not on the page
        ("31 February 2026", "date"),
        ("$5", "money"),  # which dollar?
        ("£5", "money EUR"),
        ("1.5 (1.6 to 2.0)", "estimate_interval"),  # estimate outside its interval
        ("146 (141.1)", "count_percent"),
        ("P = 1.2", "p_value"),
        ("4.6 ± 1.2 mm", "mean_sd"),  # text left over
    ],
)
def test_rejects(printed, type_):
    with pytest.raises(ParseError):
        parse(printed, value_type(type_))


@pytest.mark.parametrize(
    "raw",
    [
        "integr",
        "count_percent mean",
        "date YYYY",
        "decimal 1.234.56",
        {"kind": "date", "lokale": "de"},
    ],
)
def test_bad_types_fail_when_the_spec_loads(raw):
    with pytest.raises(SpecError):
        value_type(raw, "f")


def test_same_value_compares_decimals_by_number():
    assert same_value({"mean": "4.60"}, {"mean": "4.6"})
    assert not same_value("4.6", "4.7")
