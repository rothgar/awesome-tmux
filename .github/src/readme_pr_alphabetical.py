#!/usr/bin/env python3
"""
Alphabetical-order check for README.md additions in awesome-tmux.

Reads the base README and the PR's unified diff, reconstructs the
post-PR README, parses `##` sections (and `###` sub-sections), and
reports ordering violations for top-level list items that involve a
line added by the PR. Indented sub-bullets (e.g. plugins listed under
a parent entry like `[tmux-plugins](...)`) are not sorted; they are
treated as part of the parent entry's description.

Sections whose name starts with `Table of Contents` are skipped.
"""
import re


ITEM_RE = re.compile(r"^- \[([^\]]+)\]")
H2_RE = re.compile(r"^##\s+(?!#)(.+?)\s*$")
H3_RE = re.compile(r"^###\s+(?!#)(.+?)\s*$")
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def apply_patch(base_lines: list[str], patch_text: str) -> tuple[list[str], set[int]]:
    """Reconstruct the post-PR file from base + diff. Returns
    (new_lines, set_of_added_line_numbers_1_indexed)."""
    new_lines: list[str] = []
    added: set[int] = set()
    hunks: list[dict] = []
    current: dict | None = None
    for line in patch_text.splitlines(keepends=False):
        m = HUNK_RE.match(line)
        if m:
            if current is not None:
                hunks.append(current)
            current = {
                "old_start": int(m.group(1)),
                "new_start": int(m.group(2)),
                "lines": [],
            }
        elif current is not None:
            current["lines"].append(line)
    if current is not None:
        hunks.append(current)

    old_pos = 1
    new_pos = 1
    for hunk in hunks:
        while old_pos < hunk["old_start"]:
            new_lines.append(base_lines[old_pos - 1])
            old_pos += 1
            new_pos += 1
        for hunk_line in hunk["lines"]:
            if hunk_line.startswith("---") or hunk_line.startswith("+++"):
                continue
            if hunk_line.startswith("\\"):
                continue
            if hunk_line.startswith("-"):
                old_pos += 1
            elif hunk_line.startswith("+"):
                content = hunk_line[1:]
                if not content.endswith("\n"):
                    content += "\n"
                new_lines.append(content)
                added.add(new_pos)
                new_pos += 1
            elif hunk_line.startswith(" "):
                new_lines.append(base_lines[old_pos - 1])
                old_pos += 1
                new_pos += 1
    while old_pos <= len(base_lines):
        new_lines.append(base_lines[old_pos - 1])
        old_pos += 1
        new_pos += 1
    return new_lines, added


def is_sub_bullet(line: str) -> bool:
    """Return True if the line is an indented (sub) bullet."""
    stripped = line.lstrip()
    return stripped.startswith("- ") and line[:len(line) - len(stripped)] not in ("",)


def is_item_line(line: str) -> bool:
    """True if line is a top-level `- [...]` list item."""
    return bool(ITEM_RE.match(line))


def parse_sections(content: str) -> list[dict]:
    """Parse README into sections.

    Returns a list of:
        {"name": str, "items": [(line_no, name)], "subsections": [{name, items}]}
    """
    sections: list[dict] = []
    current: dict | None = None
    current_sub: dict | None = None
    in_toc = False

    for i, raw in enumerate(content.splitlines(), start=1):
        line = raw

        m2 = H2_RE.match(line)
        if m2:
            name = m2.group(1).strip()
            current_sub = None
            if name.lower().startswith("table of contents"):
                current = None
                in_toc = True
                continue
            in_toc = False
            current = {"name": name, "items": [], "subsections": []}
            sections.append(current)
            continue

        if in_toc:
            continue

        m3 = H3_RE.match(line)
        if m3:
            if current is not None:
                current_sub = {"name": m3.group(1).strip(), "items": []}
                current["subsections"].append(current_sub)
            continue

        if is_sub_bullet(line):
            continue

        if is_item_line(line):
            name_match = ITEM_RE.match(line)
            name = name_match.group(1).strip()
            entry = (i, name)
            if current_sub is not None:
                current_sub["items"].append(entry)
            elif current is not None:
                current["items"].append(entry)
    return sections


def iter_checkable_groups(sections: list[dict]) -> list[tuple[str, list[tuple[int, str]]]]:
    """Return (display_name, items) pairs we should check for ordering."""
    out: list[tuple[str, list[tuple[int, str]]]] = []
    for s in sections:
        if s["subsections"]:
            for sub in s["subsections"]:
                out.append((f"{s['name']} > {sub['name']}", sub["items"]))
        else:
            out.append((s["name"], s["items"]))
    return out


def find_ordering_violations(
    items: list[tuple[int, str]],
    added_lines: set[int],
) -> tuple[bool, list[str]]:
    """Report violations only when at least one of the two items is on a
    line added by the PR (case-insensitive alphabetical)."""
    names = [n.casefold() for _, n in items]
    descriptions: list[str] = []
    involves_added = False
    for i in range(len(items) - 1):
        if names[i] > names[i + 1]:
            line_a, name_a = items[i]
            line_b, name_b = items[i + 1]
            if (line_a in added_lines) or (line_b in added_lines):
                involves_added = True
                descriptions.append(
                    f"`{name_a}` (line {line_a}) should come after `{name_b}` (line {line_b})"
                )
    return involves_added, descriptions


def check_alphabetical(base_content: str, readme_patch: str) -> str:
    """Return a markdown section (empty string if sorted)."""
    base_lines = base_content.splitlines(keepends=True)
    new_lines, added_lines = apply_patch(base_lines, readme_patch)
    new_content = "".join(new_lines)

    sections = parse_sections(new_content)
    flagged: list[tuple[str, list[str]]] = []
    for group_name, items in iter_checkable_groups(sections):
        if len(items) < 2:
            continue
        involves_added, descriptions = find_ordering_violations(items, added_lines)
        if involves_added and descriptions:
            flagged.append((group_name, descriptions))

    if not flagged:
        return ""

    lines = [
        "",
        "### Alphabetical order",
        "",
        "Items below are not in alphabetical order within their section. "
        "Please sort the affected entries so the section stays alphabetical.",
        "",
    ]
    for group_name, descriptions in flagged:
        lines.append(f"- **{group_name}**")
        for d in descriptions:
            lines.append(f"  - {d}")
    return "\n".join(lines) + "\n"
