"""Run the commands a README shows and fail when what they do differs from what it prints.

    uv run --project packages/janus python examples/check_readme.py README.md examples/README.md
    uv run --project packages/janus python examples/check_readme.py --write examples/README.md

Every fenced block of a checked file is accounted for:

- A ```console block is run. A command is a line that starts with "$ ". The lines after it, up to
  the next command or the end of the block, are its output, compared exactly, trailing spaces
  included, with stderr merged into stdout. Each command runs in `bash -o pipefail`, in the
  directory of the README, so a pipeline fails when any part of it fails. A command that exits
  with a status other than 0 fails the check, unless the line ends with "# exit N", which says
  it is expected to exit with N. Every line before the first command, and every line that starts
  with "$" but not "$ ", is an error.
- A block in another shell language (sh, bash, shell, zsh) is not run. It must be named in
  NOT_RUN below, with the reason. A shell block that is not named there is an error, and so is
  an entry there that names no block.
- A NOT_RUN entry with `in_ci` names a block that CI runs itself. Each of its command lines must
  then be a line of a `run:` step in .github/workflows/ci.yml, in the working directory that the
  block's `cd` lines lead to, so the block and CI cannot drift apart.
- A block in any other language is not a command and is not checked. A block with no language
  is an error.

With --write the README is rewritten with the output the commands give now, when nothing else
is wrong. The exit status is 0 when every file is as it says, 1 otherwise, 2 for bad arguments.
"""

import difflib
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import yaml

ROOT = Path(__file__).resolve().parent.parent
CI = ROOT / ".github" / "workflows" / "ci.yml"
SHELLS = {"sh", "bash", "shell", "zsh"}
EXPECTED_EXIT = re.compile(r"\s# exit (\d+)$")


class NotRun(NamedTuple):
    reason: str
    in_ci: bool = False


# The shell blocks that are not run: (file from the repository root, first line of the block).
NOT_RUN: dict[tuple[str, str], NotRun] = {
    ("README.md", "# the command"): NotRun(
        "It installs from the repository's Git URL, which an unmerged commit is not at. CI "
        "installs the checkout without extras and runs `janus --help` instead."
    ),
    ("README.md", "cd packages/janus"): NotRun("It is what CI runs.", in_ci=True),
    ("README.md", "cd apps/workbench/web"): NotRun(
        "It starts a server that runs until it is stopped. CI builds the client and runs the "
        "Playwright tests against the real server instead."
    ),
    ("examples/README.md", "uv run --project ../packages/janus python make_examples.py"): NotRun(
        "CI runs it and fails when a file it writes differs from the committed one.", in_ci=True
    ),
}


@dataclass
class Block:
    language: str
    start: int  # the index of the opening fence
    lines: list[str]


@dataclass
class Result:
    errors: list[str] = field(default_factory=list)
    now: list[str] = field(default_factory=list)  # the file, with each output as it is now


def blocks(lines: list[str]) -> tuple[list[Block], list[str]]:
    """The fenced blocks of a Markdown file, and the errors in its fences."""
    found: list[Block] = []
    errors: list[str] = []
    current: Block | None = None
    for i, line in enumerate(lines):
        if not line.startswith("```"):
            if current:
                current.lines.append(line)
        elif current is None:
            current = Block(line[3:].strip(), i, [])
        elif line.strip() == "```":
            found.append(current)
            current = None
        else:
            errors.append(f"{i + 1}: a fence opens inside the block from line {current.start + 1}")
    if current:
        errors.append(f"{current.start + 1}: the block is never closed")
    return found, errors


def run(command: str, cwd: Path) -> tuple[list[str], int]:
    """What `command` prints, on either stream, and its exit status."""
    done = subprocess.run(
        ["bash", "-o", "pipefail", "-c", command],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return done.stdout.splitlines(), done.returncode


def run_console(block: Block, cwd: Path, errors: list[str]) -> list[str]:
    """The block's lines with each command's output as it is now. Errors go to `errors`."""
    out: list[str] = []
    for offset, line in enumerate(block.lines):
        number = block.start + 2 + offset
        if line.startswith("$ "):
            command = line[2:]
            expected = EXPECTED_EXIT.search(command)
            want = int(expected.group(1)) if expected else 0
            printed, status = run(command, cwd)
            out.append(line)
            out += printed
            if status != want:
                errors.append(f"{number}: `{command}` exited with {status}, not {want}")
            for bad in (p for p in printed if p.startswith("$")):
                errors.append(f"{number}: the output line {bad!r} would read as a prompt")
        elif line.startswith("$"):
            errors.append(f"{number}: {line!r} is no command; a prompt is '$ '")
            out.append(line)
        elif not out:
            errors.append(f"{number}: a console block starts with a command")
            out.append(line)
        # Any other line is output the README printed before; the command's output replaces it.
    return out


def ci_steps(ci: Path = CI) -> set[tuple[str, str]]:
    """Each command line of a `run:` step in CI, with the directory it runs in."""
    workflow = yaml.safe_load(ci.read_text())
    steps: set[tuple[str, str]] = set()
    for job in workflow["jobs"].values():
        default = job.get("defaults", {}).get("run", {}).get("working-directory", ".")
        for step in job.get("steps", []):
            directory = os.path.normpath(step.get("working-directory", default))
            for line in str(step.get("run", "")).splitlines():
                if line.strip():
                    steps.add((directory, line.strip()))
    return steps


def missing_from_ci(block: Block, directory: str, steps: set[tuple[str, str]]) -> list[str]:
    """The command lines of `block` that no CI step runs in the same directory."""
    errors: list[str] = []
    for offset, line in enumerate(block.lines):
        command = re.sub(r"\s+#.*$", "", line).strip()
        if not command or command.startswith("#"):
            continue
        if command.startswith("cd "):
            directory = os.path.normpath(f"{directory}/{command[3:].strip()}")
        elif (directory, command) not in steps:
            number = block.start + 2 + offset
            errors.append(f"{number}: no step of CI runs `{command}` in {directory}")
    return errors


def check(
    text: str,
    name: str,
    cwd: Path,
    not_run: dict[tuple[str, str], NotRun] = NOT_RUN,
    ci: set[tuple[str, str]] | None = None,
) -> Result:
    """Check the Markdown `text` of the file `name` (from the repository root); run in `cwd`."""
    lines = text.splitlines()
    found, errors = blocks(lines)
    unused = {key for key in not_run if key[0] == name}
    replaced: dict[int, tuple[int, list[str]]] = {}  # fence index -> (lines replaced, new lines)
    for block in found:
        first = next((line for line in block.lines if line.strip()), "")
        if block.language == "console":
            replaced[block.start] = (len(block.lines), run_console(block, cwd, errors))
        elif block.language in SHELLS:
            entry = not_run.get((name, first))
            if entry is None:
                errors.append(
                    f"{block.start + 1}: a {block.language} block that is neither a console "
                    f"block nor named in NOT_RUN: {first!r}"
                )
                continue
            unused.discard((name, first))
            if entry.in_ci:
                steps = ci_steps() if ci is None else ci
                errors += missing_from_ci(block, Path(name).parent.as_posix(), steps)
        elif not block.language:
            errors.append(f"{block.start + 1}: a block with no language")
    errors += [f"NOT_RUN names a block that is not in the file: {first!r}" for _, first in unused]
    result = Result(errors=[f"{name}:{error}" for error in errors])
    i = 0
    while i < len(lines):
        result.now.append(lines[i])
        if i in replaced:
            count, new = replaced[i]
            result.now += new
            i += count
        i += 1
    return result


def main(args: list[str]) -> int:
    write = "--write" in args
    readmes = [Path(arg) for arg in args if arg != "--write"]
    if not readmes:
        print("usage: check_readme.py [--write] README.md [README.md ...]", file=sys.stderr)
        return 2
    failed = 0
    for readme in readmes:
        path = readme.resolve()
        name = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(readme)
        before = path.read_text().splitlines()
        result = check(path.read_text(), name, path.parent)
        for error in result.errors:
            print(error)
        if result.errors:
            failed += 1
            print(f"fails    {readme}")
        elif before == result.now:
            print(f"same     {readme}")
        elif write:
            path.write_text("\n".join(result.now) + "\n")
            print(f"rewrote  {readme}")
        else:
            failed += 1
            print(f"differs  {readme}")
            print("\n".join(difflib.unified_diff(before, result.now, "README", "now", lineterm="")))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
