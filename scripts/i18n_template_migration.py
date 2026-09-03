"""Mechanical migration helper for Django template translation tags.

This script is intentionally conservative around JavaScript, CSS, Django template
expressions, and user/database values. Run without ``--apply`` for an inventory.
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = ROOT / "management" / "templates" / "management"
LEGACY_CATALOG = ROOT / "static" / "js" / "fabro-i18n.js"

CATALOG_ENTRY = re.compile(
    r"'((?:\\.|[^'])*)'\s*:\s*\[\s*'((?:\\.|[^'])*)'\s*,\s*'((?:\\.|[^'])*)'\s*\]",
    re.DOTALL,
)
PROTECTED_BLOCK = re.compile(
    r"(<(?:script|style)\b[^>]*>.*?</(?:script|style)>)",
    re.IGNORECASE | re.DOTALL,
)
TEXT_NODE = re.compile(r">([^<>]+)<")
TRANSLATABLE_ATTRIBUTE = re.compile(
    r'\b(placeholder|title|aria-label)="([^"{}]+)"',
    re.IGNORECASE,
)
LETTERS = re.compile(r"[A-Za-z]")
HTML_ROOT = re.compile(r'<html(?:\s+lang="[^"]*")?(?:\s+dir="[^"]*")?>', re.IGNORECASE)


def decode_js_string(value: str) -> str:
    return ast.literal_eval("'" + value + "'")


def legacy_catalog() -> dict[str, tuple[str, str]]:
    source = LEGACY_CATALOG.read_text(encoding="utf-8")
    return {
        decode_js_string(english): (decode_js_string(arabic), decode_js_string(hindi))
        for english, arabic, hindi in CATALOG_ENTRY.findall(source)
    }


def translation_tag(text: str) -> str:
    escaped = text.replace('\\', '\\\\').replace('"', '\\"')
    return f'{{% translate "{escaped}" %}}'


def ensure_i18n_loaded(source: str) -> str:
    if re.search(r"{%\s*load\s+[^%]*\bi18n\b", source):
        return source
    static_load = re.search(r"{%\s*load\s+static\s*%}", source)
    if static_load:
        return source[:static_load.start()] + "{% load static i18n %}" + source[static_load.end():]
    return "{% load i18n %}\n" + source


def mark_segment(segment: str) -> tuple[str, set[str]]:
    messages: set[str] = set()

    def replace_attribute(match: re.Match[str]) -> str:
        name, value = match.groups()
        normalized = re.sub(r"\s+", " ", value).strip()
        if not normalized or not LETTERS.search(normalized):
            return match.group(0)
        messages.add(normalized)
        return f'{name}="{translation_tag(normalized)}"'

    segment = TRANSLATABLE_ATTRIBUTE.sub(replace_attribute, segment)

    def replace_text(match: re.Match[str]) -> str:
        value = match.group(1)
        if "{%" in value or "{{" in value or "<!--" in value:
            return match.group(0)
        normalized = re.sub(r"\s+", " ", value).strip()
        if not normalized or not LETTERS.search(normalized):
            return match.group(0)
        if normalized.startswith(("http://", "https://")):
            return match.group(0)
        leading = value[: len(value) - len(value.lstrip())]
        trailing = value[len(value.rstrip()) :]
        messages.add(normalized)
        return f">{leading}{translation_tag(normalized)}{trailing}<"

    return TEXT_NODE.sub(replace_text, segment), messages


def migrate_template(path: Path, apply: bool) -> set[str]:
    source = path.read_text(encoding="utf-8")
    parts = PROTECTED_BLOCK.split(source)
    messages: set[str] = set()
    for index in range(0, len(parts), 2):
        parts[index], found = mark_segment(parts[index])
        messages.update(found)
    migrated = ensure_i18n_loaded("".join(parts))
    migrated = HTML_ROOT.sub(
        '<html lang="{{ LANGUAGE_CODE|default:\'en\' }}" '
        'dir="{% if LANGUAGE_CODE == \'ar\' %}rtl{% else %}ltr{% endif %}">',
        migrated,
    )
    if apply and migrated != source:
        path.write_text(migrated, encoding="utf-8", newline="")
    return messages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    catalog = legacy_catalog()
    all_messages: set[str] = set()
    for path in sorted(TEMPLATE_ROOT.glob("*.html")):
        messages = migrate_template(path, args.apply)
        all_messages.update(messages)
        missing = sorted(message for message in messages if message not in catalog)
        print(f"{path.name}: {len(messages)} strings, {len(missing)} absent from legacy catalog")
    print(f"TOTAL: {len(all_messages)} unique strings")
    print(f"LEGACY: {len(catalog)} translated strings")
    print(f"COVERED: {sum(message in catalog for message in all_messages)}")


if __name__ == "__main__":
    main()
