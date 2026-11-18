"""Run the commands a README shows and fail when their output differs from what it prints.

    uv run --project packages/janus python examples/check_readme.py README.md examples/README.md
    uv run --project packages/janus python examples/check_readme.py --write examples/README.md

A command is a line that starts with "$ " inside a ```console block. The lines after it, up to
the next command or the end of the block, are its output. Each command runs in bash, in the
directory of the README that shows it. With --write the README is rewritten with the output the
commands give now.
"""

import difflib
import subprocess
import sys
from pathlib import Path


def run(command: str, cwd: Path) -> list[str]:
    """The lines `command` prints, on either stream, without trailing spaces."""
    done = subprocess.run(
        ["bash", "-c", command],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return [line.rstrip() for line in done.stdout.splitlines()]


def refresh(readme: Path) -> list[str]:
    """The README's lines with the output under every command replaced by what it prints now."""
    out: list[str] = []
    inside = running = False
    for line in readme.read_text().splitlines():
        if line.startswith("```"):
            inside, running = line.strip() == "```console", False
        elif inside and line.startswith("$ "):
            out.append(line)
            out += run(line[2:], readme.parent)
            running = True
            continue
        elif running:
            continue  # the output the README printed before
        out.append(line)
    return out


def main(args: list[str]) -> int:
    write = "--write" in args
    readmes = [Path(arg) for arg in args if arg != "--write"]
    if not readmes:
        print("usage: check_readme.py [--write] README.md [README.md ...]", file=sys.stderr)
        return 2
    differing = 0
    for readme in readmes:
        before = [line.rstrip() for line in readme.read_text().splitlines()]
        now = refresh(readme)
        if before == now:
            print(f"same     {readme}")
        elif write:
            readme.write_text("\n".join(now) + "\n")
            print(f"rewrote  {readme}")
        else:
            differing += 1
            print(f"differs  {readme}")
            print("\n".join(difflib.unified_diff(before, now, "README", "now", lineterm="")))
    return 1 if differing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
