#!/usr/bin/env python3
"""Validazione locale, senza dipendenze, del contratto minimo di una skill."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import unquote, urlparse


NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


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


def _local_link_errors(root: Path) -> list[str]:
    """Validate packaged Markdown links without following paths outside the skill."""
    root = root.resolve()
    documents = [root / "SKILL.md"]
    references = root / "references"
    if references.is_dir():
        documents.extend(sorted(references.glob("*.md")))

    errors: list[str] = []
    for document in documents:
        try:
            source = document.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            errors.append(f"impossibile leggere {document.relative_to(root)}: {error}")
            continue
        for raw_target in MARKDOWN_LINK_PATTERN.findall(source):
            target = raw_target.strip()
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            target = target.split(maxsplit=1)[0]
            parsed = urlparse(target)
            if parsed.scheme or parsed.netloc or target.startswith("#"):
                continue
            relative_target = unquote(parsed.path)
            if not relative_target:
                continue
            resolved = (document.parent / relative_target).resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                errors.append(
                    f"link locale fuori dalla skill in {document.relative_to(root)}: {target}"
                )
                continue
            if not resolved.is_file():
                errors.append(
                    f"link locale mancante in {document.relative_to(root)}: {target}"
                )
    return errors


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
    errors.extend(_local_link_errors(root))
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
