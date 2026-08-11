#!/usr/bin/env python3
"""Validazione locale, senza dipendenze, del contratto minimo di una skill."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _frontmatter(skill_path: Path) -> dict[str, str]:
    text = skill_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("SKILL.md deve iniziare con il frontmatter YAML")
    try:
        closing = lines.index("---", 1)
    except ValueError as error:
        raise ValueError("frontmatter YAML non terminato") from error

    values: dict[str, str] = {}
    for line in lines[1:closing]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"riga frontmatter non valida: {line}")
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def validate_skill(root: Path) -> list[str]:
    errors: list[str] = []
    skill_path = root / "SKILL.md"
    if not skill_path.is_file():
        return [f"file mancante: {skill_path}"]
    try:
        values = _frontmatter(skill_path)
    except (OSError, UnicodeError, ValueError) as error:
        return [str(error)]

    name = values.get("name", "")
    description = values.get("description", "")
    unexpected = sorted(set(values) - {"name", "description"})
    if unexpected:
        errors.append(f"chiavi frontmatter non supportate: {', '.join(unexpected)}")
    if not name or len(name) > 64 or not NAME_PATTERN.fullmatch(name):
        errors.append("name deve essere kebab-case e lungo al massimo 64 caratteri")
    if not description or len(description) > 1024:
        errors.append("description deve contenere tra 1 e 1024 caratteri")
    if "<" in description or ">" in description:
        errors.append("description non può contenere parentesi angolari")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    errors = validate_skill(root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"OK: {root / 'SKILL.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
