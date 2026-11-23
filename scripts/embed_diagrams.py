#!/usr/bin/env python3
"""Inline Mermaid sources from diagrams/*.mmd into architecture docs.

Source docs (*.src.md) contain markers like:
    <!-- diagram: 03-gke-runtime -->
Each marker is replaced with a ```mermaid block containing diagrams/03-gke-runtime.mmd,
followed by a link to the source file. Output is written next to the source without ".src".
Keeping one copy of each diagram (the .mmd file) stops docs and diagrams drifting apart.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MARKER = re.compile(r"<!-- diagram: ([\w.-]+) -->")


def render(src: pathlib.Path) -> None:
    text = src.read_text(encoding="utf-8")

    def repl(match: re.Match) -> str:
        name = match.group(1)
        mmd = ROOT / "diagrams" / f"{name}.mmd"
        if not mmd.exists():
            sys.exit(f"missing diagram source: {mmd}")
        rel = pathlib.Path("..") / "diagrams" / f"{name}.mmd"
        body = mmd.read_text(encoding="utf-8").rstrip()
        return f"```mermaid\n{body}\n```\n\n*Source: [`diagrams/{name}.mmd`]({rel.as_posix()})*"

    out = src.with_name(src.name.replace(".src.md", ".md"))
    out.write_text(MARKER.sub(repl, text), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    for path in sorted(ROOT.glob("architecture/**/*.src.md")):
        render(path)
