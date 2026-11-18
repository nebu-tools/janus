from janus_pdf.document import Span, find_quote

ABSTRACT = (
    "Methods: We surveyed 412 ponds between 12 and 17 metres\n"
    "deep in the north-west of the county. Sam-\npling lasted 24 weeks."
)


def test_exact_quote_is_found_at_original_offsets() -> None:
    (span,) = find_quote("ponds between 12 and 17 metres", ABSTRACT)
    assert ABSTRACT[span.start : span.end] == "ponds between 12 and 17 metres"


def test_whitespace_differences_are_tolerated() -> None:
    (span,) = find_quote("17 metres deep", ABSTRACT)
    assert ABSTRACT[span.start : span.end] == "17 metres\ndeep"


def test_line_break_hyphenation_is_joined() -> None:
    (span,) = find_quote("Sampling lasted 24 weeks", ABSTRACT)
    assert span == Span(ABSTRACT.index("Sam-"), len(ABSTRACT) - 1)


def test_real_hyphens_are_kept() -> None:
    assert find_quote("north-west", ABSTRACT)
    assert not find_quote("northwest", ABSTRACT)


def test_paraphrase_is_not_found() -> None:
    assert find_quote("shallow lakes", ABSTRACT) == ()


def test_repeated_quote_returns_every_occurrence() -> None:
    assert len(find_quote("aged", "aged 12, aged 70")) == 2


def test_empty_quote_is_never_found() -> None:
    assert find_quote("  ", ABSTRACT) == ()


def test_hyphenated_and_plain_occurrences_are_both_reported() -> None:
    assert len(find_quote("Sampling", "Sampling and Sam-\npling")) == 2


def test_soft_hyphens_are_ignored() -> None:
    (span,) = find_quote("residing", "fish resid­ing here")
    assert span == Span(5, 14)
