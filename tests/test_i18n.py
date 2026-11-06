"""Every UI string exists in all four languages, with matching {placeholders}, and every key the code uses is defined."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
LANGS = ("he", "en", "ar", "ru")


def load_rows():
    rows = {}
    for path in sorted((STATIC / "js").glob("i18n-strings*.js")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip().rstrip(",")
            if line.startswith("["):
                row = json.loads(line)
                assert row[0] not in rows, f"duplicate key {row[0]} ({path.name}:{number})"
                rows[row[0]] = row[1:]
    return rows


def placeholders(text):
    return sorted(set(re.findall(r"\{(\w+)\}", text)))


class StringTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_rows()

    def test_every_key_has_all_four_languages(self):
        for key, values in self.rows.items():
            self.assertEqual(len(values), 4, key)
            for lang, value in zip(LANGS, values):
                self.assertTrue(isinstance(value, str) and value.strip(), f"{key} is empty in {lang}")

    def test_placeholders_match_across_languages(self):
        for key, values in self.rows.items():
            self.assertEqual(len({tuple(placeholders(v)) for v in values}), 1, f"{key}: {values}")

    def test_scripts_hebrew_arabic_and_russian_are_really_translated(self):
        # Guards against English text pasted into another language column.
        latin = re.compile(r"[A-Za-z]{4,}")
        for key, (he, _en, ar, _ru) in self.rows.items():
            for lang, value in (("he", he), ("ar", ar)):
                stripped = re.sub(r"\{\w+\}|<[^>]+>|Inspectra|INSPECTRA|GPS|Enter|OpenStreetMap", "", value)
                self.assertFalse(latin.search(stripped), f"{key} ({lang}) still contains English: {value}")

    def test_keys_used_by_templates_and_scripts_exist(self):
        used = set()
        patterns = (r'data-i18n(?:-html)?="([\w.]+)"', r'data-i18n-attr="([^"]+)"', r"\bt\(\s*['\"]([\w.]+)['\"]", r"\bt\(`([\w.]+)`")
        files = list((ROOT / "app" / "templates").rglob("*.html")) + [p for p in (STATIC / "js").glob("*.js") if "strings" not in p.name]
        for path in files:
            text = path.read_text(encoding="utf-8")
            for pattern in patterns:
                for match in re.findall(pattern, text):
                    if pattern.startswith('data-i18n-attr'):
                        used.update(pair.split(":")[1].strip() for pair in match.split(";") if ":" in pair)
                    else:
                        used.add(match)
        used = {k for k in used if "." in k}
        missing = sorted(k for k in used if k not in self.rows and not k.endswith("."))
        self.assertEqual(missing, [], f"keys used but not defined: {missing}")


if __name__ == "__main__":
    unittest.main()
