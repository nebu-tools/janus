"""The README check, on small Markdown files."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from check_readme import NotRun, check, ci_steps, main

FENCE = "```"


def md(*blocks: str) -> str:
    return "\n".join(blocks) + "\n"


def console(*lines: str) -> str:
    return "\n".join([f"{FENCE}console", *lines, FENCE])


def run(text: str, tmp_path: Path, not_run=None, ci=None) -> tuple[list[str], bool]:
    """The errors, and whether the file is as it says once there are none."""
    result = check(text, "README.md", tmp_path, not_run or {}, ci)
    return result.errors, result.now == text.splitlines()


def test_matching_output_passes(tmp_path):
    assert run(md(console("$ printf 'a\\nb\\n'", "a", "b")), tmp_path) == ([], True)


def test_output_is_compared_with_trailing_spaces(tmp_path):
    assert run(md(console('$ printf "x "', "x")), tmp_path) == ([], False)
    assert run(md(console('$ printf "x "', "x ")), tmp_path) == ([], True)


def test_output_cut_short_differs(tmp_path):
    assert run(md(console('$ printf "abcdef"', "abc")), tmp_path) == ([], False)


def test_a_command_that_fails_fails_the_check(tmp_path):
    errors, _ = run(md(console("$ false")), tmp_path)
    assert errors == ["README.md:2: `false` exited with 1, not 0"]


def test_a_pipeline_fails_when_any_part_fails(tmp_path):
    errors, _ = run(md(console("$ false | cat")), tmp_path)
    assert errors == ["README.md:2: `false | cat` exited with 1, not 0"]


def test_a_block_can_state_the_exit_status_it_expects(tmp_path):
    assert run(md(console("$ exit 3  # exit 3")), tmp_path) == ([], True)
    errors, _ = run(md(console("$ true  # exit 1")), tmp_path)
    assert errors == ["README.md:2: `true  # exit 1` exited with 0, not 1"]


def test_a_malformed_prompt_fails_instead_of_being_skipped(tmp_path):
    errors, _ = run(md(console("$false")), tmp_path)
    assert errors == ["README.md:2: '$false' is no command; a prompt is '$ '"]
    errors, _ = run(md(console("$ true", "$true")), tmp_path)
    assert errors == ["README.md:3: '$true' is no command; a prompt is '$ '"]


def test_a_console_block_starts_with_a_command(tmp_path):
    errors, _ = run(md(console("hello", "$ true")), tmp_path)
    assert errors == ["README.md:2: a console block starts with a command"]


def test_a_shell_block_not_in_the_table_fails(tmp_path):
    text = md(f"{FENCE}sh", "false", FENCE)
    errors, _ = run(text, tmp_path)
    assert errors == [
        "README.md:1: a sh block that is neither a console block nor named in NOT_RUN: 'false'"
    ]


def test_a_shell_block_in_the_table_is_not_run(tmp_path):
    text = md(f"{FENCE}bash", "false", FENCE)
    not_run = {("README.md", "false"): NotRun("an example")}
    assert run(text, tmp_path, not_run=not_run) == ([], True)


def test_a_table_entry_that_names_no_block_fails(tmp_path):
    not_run = {("README.md", "gone"): NotRun("an example"), ("other.md", "x"): NotRun("other")}
    errors, _ = run(md(console("$ true")), tmp_path, not_run=not_run)
    assert errors == ["README.md:NOT_RUN names a block that is not in the file: 'gone'"]


def test_a_block_ci_runs_must_be_in_ci_in_the_same_directory(tmp_path):
    text = md(f"{FENCE}sh", "cd pkg", "uv run pytest   # the tests", "", "cd ..", "make", FENCE)
    not_run = {("README.md", "cd pkg"): NotRun("CI runs it", in_ci=True)}
    ci = {("pkg", "uv run pytest"), (".", "make")}
    assert run(text, tmp_path, not_run=not_run, ci=ci) == ([], True)
    errors, _ = run(text, tmp_path, not_run=not_run, ci={(".", "uv run pytest"), (".", "make")})
    assert errors == ["README.md:3: no step of CI runs `uv run pytest` in pkg"]


def test_ci_steps_reads_each_line_of_each_run_step_with_its_directory(tmp_path):
    ci = tmp_path / "ci.yml"
    ci.write_text(
        "jobs:\n"
        "  a:\n"
        "    defaults: {run: {working-directory: pkg}}\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - run: uv run pytest\n"
        "      - working-directory: examples\n"
        "        run: |\n"
        "          one\n"
        "          two\n"
        "  b:\n"
        "    steps:\n"
        "      - run: make\n"
    )
    assert ci_steps(ci) == {
        ("pkg", "uv run pytest"),
        ("examples", "one"),
        ("examples", "two"),
        (".", "make"),
    }


def test_other_languages_are_not_run_and_a_block_needs_a_language(tmp_path):
    assert run(md(f"{FENCE}yaml", "a: 1", FENCE), tmp_path) == ([], True)
    errors, _ = run(md(FENCE, "false", FENCE), tmp_path)
    assert errors == ["README.md:1: a block with no language"]


def test_a_block_left_open_fails(tmp_path):
    errors, _ = run(md(f"{FENCE}console", "$ true"), tmp_path)
    assert errors == ["README.md:1: the block is never closed"]


@pytest.mark.parametrize(
    ("body", "status"),
    [
        (console("$ printf 'ok\\n'", "ok"), 0),
        (console("$ printf 'ok\\n'", "no"), 1),
        (console("$ false"), 1),
        (f"{FENCE}sh\nfalse\n{FENCE}", 1),
    ],
)
def test_main_exits_1_when_a_file_is_not_as_it_says(tmp_path, capsys, body, status):
    readme = tmp_path / "README.md"
    readme.write_text(body + "\n")
    assert main([str(readme)]) == status
    capsys.readouterr()


def test_write_rewrites_output_but_not_a_failing_file(tmp_path, capsys):
    readme = tmp_path / "README.md"
    readme.write_text(md(console("$ printf 'new\\n'", "old")))
    assert main(["--write", str(readme)]) == 0
    assert readme.read_text() == md(console("$ printf 'new\\n'", "new"))
    readme.write_text(md(console("$ false", "old")))
    assert main(["--write", str(readme)]) == 1
    assert readme.read_text() == md(console("$ false", "old"))
    capsys.readouterr()
