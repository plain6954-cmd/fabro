"""Build deterministic Django PO/MO catalogs without a system gettext install."""

from __future__ import annotations

import ast
import re
import struct
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ("en", "ar", "hi")
HEADERS = {
    "en": "nplurals=2; plural=(n != 1);",
    "ar": "nplurals=2; plural=(n != 1);",
    "hi": "nplurals=2; plural=(n != 1);",
}
TEMPLATE_MESSAGE = re.compile(r'{%\s*translate\s+(["\'])(.*?)\1(?:\s+as\s+\w+)?\s*%}', re.DOTALL)
JS_MESSAGE = re.compile(r'\.gettext\(\s*(["\'])(.*?)\1\s*\)', re.DOTALL)
LEGACY_ENTRY = re.compile(
    r"'((?:\\.|[^'])*)'\s*:\s*\[\s*'((?:\\.|[^'])*)'\s*,\s*'((?:\\.|[^'])*)'\s*\]",
    re.DOTALL,
)

SUPPLEMENT = {
    "Country executives must be assigned to a country.": (
        "يجب تعيين المسؤولين التنفيذيين للبلد إلى بلد.",
        "देश कार्यकारी को किसी देश से संबद्ध करना आवश्यक है।",
    ),
    "Read": ("مقروء", "पढ़ा गया"),
    "No messages yet": ("لا توجد رسائل بعد", "अभी कोई संदेश नहीं"),
    "Start the conversation by sending a text below.": (
        "ابدأ المحادثة بإرسال رسالة أدناه.",
        "नीचे संदेश भेजकर बातचीत शुरू करें।",
    ),
    "Failed to send message.": ("تعذر إرسال الرسالة.", "संदेश भेजा नहीं जा सका।"),
    "Submitting...": ("جارٍ الإرسال...", "जमा किया जा रहा है..."),
    "Confirm Decision": ("تأكيد القرار", "निर्णय की पुष्टि करें"),
    "Search values...": ("ابحث في القيم...", "मान खोजें..."),
    "No values found": ("لم يتم العثور على قيم", "कोई मान नहीं मिला"),
    "No matching values": ("لا توجد قيم مطابقة", "कोई मेल खाता मान नहीं"),
    "Select All": ("تحديد الكل", "सभी चुनें"),
    "Loading types...": ("جارٍ تحميل الأنواع...", "प्रकार लोड हो रहे हैं..."),
    "Unable to load types": ("تعذر تحميل الأنواع", "प्रकार लोड नहीं किए जा सके"),
    "Loading SKUs...": ("جارٍ تحميل رموز المنتجات...", "एसकेयू लोड हो रहे हैं..."),
    "No matching SKUs": ("لا توجد رموز منتجات مطابقة", "कोई मेल खाता एसकेयू नहीं"),
}


def decode_literal(quote: str, value: str) -> str:
    return ast.literal_eval(quote + value + quote)


def legacy_translations() -> dict[str, tuple[str, str]]:
    try:
        source = subprocess.run(
            ["git", "show", "HEAD:static/js/fabro-i18n.js"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return {}
    return {
        decode_literal("'", english): (
            decode_literal("'", arabic),
            decode_literal("'", hindi),
        )
        for english, arabic, hindi in LEGACY_ENTRY.findall(source)
    }


def python_messages(path: Path) -> tuple[set[str], dict[str, str]]:
    messages: set[str] = set()
    plurals: dict[str, str] = {}
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else ""
        if name in {"_", "gettext", "gettext_lazy"} and node.args:
            if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                messages.add(node.args[0].value)
        elif name == "ngettext" and len(node.args) >= 2:
            singular, plural = node.args[:2]
            if all(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in (singular, plural)):
                messages.add(singular.value)
                plurals[singular.value] = plural.value
    return messages, plurals


def collect_messages() -> tuple[set[str], dict[str, str]]:
    messages: set[str] = set()
    plurals: dict[str, str] = {}
    for path in (ROOT / "management" / "templates").rglob("*.html"):
        source = path.read_text(encoding="utf-8")
        messages.update(decode_literal(quote, value) for quote, value in TEMPLATE_MESSAGE.findall(source))
        messages.update(decode_literal(quote, value) for quote, value in JS_MESSAGE.findall(source))
    for path in (ROOT / "management").rglob("*.py"):
        if "migrations" in path.parts:
            continue
        found, found_plurals = python_messages(path)
        messages.update(found)
        plurals.update(found_plurals)
    source = (ROOT / "static" / "js" / "fabro-i18n.js").read_text(encoding="utf-8")
    messages.update(decode_literal(quote, value) for quote, value in JS_MESSAGE.findall(source))
    return messages, plurals


def po_quote(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


def catalog_translation(language: str, message: str, legacy: dict[str, tuple[str, str]]) -> str:
    if language == "en":
        return message
    translated = SUPPLEMENT.get(message) or legacy.get(message)
    if not translated:
        return ""
    return translated[0 if language == "ar" else 1]


def write_po(language: str, messages: set[str], plurals: dict[str, str], legacy: dict[str, tuple[str, str]]) -> Path:
    locale_dir = ROOT / "locale" / language / "LC_MESSAGES"
    locale_dir.mkdir(parents=True, exist_ok=True)
    path = locale_dir / "django.po"
    lines = [
        'msgid ""',
        'msgstr ""',
        f'"Language: {language}\\n"',
        '"Content-Type: text/plain; charset=UTF-8\\n"',
        f'"Plural-Forms: {HEADERS[language]}\\n"',
        '"MIME-Version: 1.0\\n"',
        '"Content-Transfer-Encoding: 8bit\\n"',
        "",
    ]
    for message in sorted(messages, key=str.casefold):
        translated = catalog_translation(language, message, legacy)
        if "%(" in message:
            lines.append("#, python-format")
        lines.append(f"msgid {po_quote(message)}")
        if message in plurals:
            plural = plurals[message]
            lines.append(f"msgid_plural {po_quote(plural)}")
            lines.append(f"msgstr[0] {po_quote(translated if language != 'en' else message)}")
            plural_translation = catalog_translation(language, plural, legacy)
            lines.append(f"msgstr[1] {po_quote(plural_translation if language != 'en' else plural)}")
        else:
            lines.append(f"msgstr {po_quote(translated)}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path


def parse_po(path: Path) -> dict[str, str]:
    catalog: dict[str, str] = {}
    current_id: str | None = None
    current_plural: str | None = None
    translations: dict[int, str] = {}
    simple_translation = ""

    def flush() -> None:
        nonlocal current_id, current_plural, translations, simple_translation
        if current_id is not None:
            key = current_id if current_plural is None else current_id + "\0" + current_plural
            value = simple_translation if current_plural is None else "\0".join(
                translations[index] for index in sorted(translations)
            )
            if current_id == "" or value:
                catalog[key] = value
        current_id, current_plural, translations, simple_translation = None, None, {}, ""

    for raw_line in [*path.read_text(encoding="utf-8").splitlines(), ""]:
        line = raw_line.strip()
        if line.startswith("msgid "):
            flush()
            current_id = ast.literal_eval(line[6:])
        elif line.startswith("msgid_plural "):
            current_plural = ast.literal_eval(line[13:])
        elif line.startswith("msgstr["):
            index = int(line[7:line.index("]")])
            translations[index] = ast.literal_eval(line.split(None, 1)[1])
        elif line.startswith("msgstr "):
            simple_translation = ast.literal_eval(line[7:])
        elif line.startswith('"'):
            value = ast.literal_eval(line)
            if current_plural is not None and translations:
                translations[max(translations)] += value
            elif current_id is not None and simple_translation:
                simple_translation += value
            elif current_id == "":
                simple_translation += value
            elif current_id is not None:
                current_id += value
        elif not line:
            flush()
    return catalog


def compile_mo(po_path: Path) -> Path:
    catalog = parse_po(po_path)
    keys = sorted(catalog)
    ids = b"\0".join(key.encode("utf-8") for key in keys) + b"\0"
    values = b"\0".join(catalog[key].encode("utf-8") for key in keys) + b"\0"
    key_offsets = []
    value_offsets = []
    offset = 0
    for key in keys:
        encoded = key.encode("utf-8")
        key_offsets.append((len(encoded), offset))
        offset += len(encoded) + 1
    offset = 0
    for key in keys:
        encoded = catalog[key].encode("utf-8")
        value_offsets.append((len(encoded), offset))
        offset += len(encoded) + 1
    count = len(keys)
    key_table_offset = 7 * 4
    value_table_offset = key_table_offset + count * 8
    ids_offset = value_table_offset + count * 8
    values_offset = ids_offset + len(ids)
    output = [struct.pack("<7I", 0x950412DE, 0, count, key_table_offset, value_table_offset, 0, 0)]
    output.extend(struct.pack("<2I", length, ids_offset + position) for length, position in key_offsets)
    output.extend(struct.pack("<2I", length, values_offset + position) for length, position in value_offsets)
    output.extend((ids, values))
    mo_path = po_path.with_suffix(".mo")
    mo_path.write_bytes(b"".join(output))
    return mo_path


def main() -> None:
    messages, plurals = collect_messages()
    legacy = legacy_translations()
    print(f"Collected {len(messages)} messages; legacy translations: {len(legacy)}")
    for language in LANGUAGES:
        po_path = write_po(language, messages, plurals, legacy)
        mo_path = compile_mo(po_path)
        translated = sum(bool(catalog_translation(language, message, legacy)) for message in messages)
        print(f"{language}: {translated}/{len(messages)} translated; {po_path}; {mo_path}")


if __name__ == "__main__":
    main()
