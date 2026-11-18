import random

import pytest

from janus_pdf.canonical import _number, _number_exact, canonical_json


@pytest.mark.parametrize("seed", range(4))
def test_fast_path_agrees_with_the_exact_algorithm(seed):
    rng = random.Random(seed)
    for _ in range(5000):
        value = rng.choice(
            [
                round(rng.uniform(-2000, 2000), rng.randint(0, 6)),  # coordinates
                rng.uniform(1e-4, 1e-3),
                float(rng.randint(1, 10**15)),
                rng.uniform(1e15, 1e16) * rng.choice([1, -1]),
            ]
        )
        assert _number(value) == _number_exact(value), value


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (1e21, "1e+21"),
        (1e-7, "1e-7"),
        (123456789012345680000.0, "123456789012345680000"),
        (0.000001, "0.000001"),
        (5e-324, "5e-324"),
        (-0.0, "0"),
        (2.5, "2.5"),
        (100.0, "100"),
        (0.0001, "0.0001"),
        (1e16, "10000000000000000"),
    ],
)
def test_ecmascript_number_strings(value, text):
    assert canonical_json(value).decode() == text


def test_bytes_match_the_rfc8785_reference_implementation():
    # The expected bytes come from the `rfc8785` package (0.1.4), which Kittum uses: keys sorted
    # by UTF-16 code units, minimal escapes, ECMAScript numbers.
    value = {
        "a": [1e21, 1e-7, -0.0, 0.1, 'é\u2028"\\', {"b": None, "a": True}],
        "é": 5e-324,
        "\u00e9a": 1,
        "z": "\x01",
    }
    expected = (
        b'{"a":[1e+21,1e-7,0,0.1,"\xc3\xa9\xe2\x80\xa8\\"\\\\",{"a":true,"b":null}],'
        b'"z":"\\u0001","\xc3\xa9":5e-324,"\xc3\xa9a":1}'
    )
    assert canonical_json(value) == expected
