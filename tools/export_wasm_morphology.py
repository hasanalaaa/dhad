"""Compile the Python morphology lexicon into a browser/Rust lookup pack.

The runtime Rust engine deliberately does not depend on Python or JSON Schema.
This build-time exporter mirrors ``MorphologicalLexicon``'s productive form
generation and writes the exact normalized records consumed by
``dhad_core::morphology``.  Keeping generation here makes the WASM runtime
small, deterministic, and independent of filesystem APIs.

Run after changing ``core_lexicon.json`` or Python morphology generation::

    python tools/export_wasm_morphology.py
"""

from __future__ import annotations

import json
import unicodedata
import zlib
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "dhad" / "data" / "lexicon" / "core_lexicon.json"
OUTPUT = ROOT / "rust" / "dhad-core-rs" / "data" / "morphology.json"
COMPRESSED_OUTPUT = OUTPUT.with_suffix(".json.zlib")

AR_DIACRITIC_RANGES = ((0x064B, 0x065F), (0x0670, 0x0670), (0x06D6, 0x06DC),
                       (0x06DF, 0x06E8), (0x06EA, 0x06ED))


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFC", value).replace("ـ", "")
    return "".join(
        char
        for char in value
        if not any(start <= ord(char) <= end for start, end in AR_DIACRITIC_RANGES)
    )


def feature_map(values: Mapping[str, Any] | Iterable[tuple[str, Any]]) -> dict[str, str]:
    items = values.items() if isinstance(values, Mapping) else values
    return {str(key): str(value) for key, value in sorted(items)}


def record(
    form: str,
    lexeme: int,
    *,
    prefixes: Sequence[tuple[str, str]] = (),
    suffixes: Sequence[tuple[str, str]] = (),
    features: Mapping[str, Any] | Iterable[tuple[str, Any]] = (),
    source: str,
    confidence: float,
) -> dict[str, Any]:
    return {
        "form": normalize(form),
        "lexeme": lexeme,
        "prefixes": [list(item) for item in prefixes],
        "suffixes": [list(item) for item in suffixes],
        "features": feature_map(features),
        "source": source,
        "confidence": confidence,
    }


def base_records(index: int, lexeme: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    yield record(
        lexeme["lemma"], index, features=lexeme["features"], source="lexicon", confidence=0.995
    )
    for item in lexeme["forms"]:
        yield record(
            item["form"], index, features=item.get("features", {}),
            source="lexicon", confidence=0.99,
        )


def noun_records(index: int, lexeme: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    lemma, pos = lexeme["lemma"], lexeme["pos"]
    if pos not in {"noun", "adjective", "proper_noun", "verbal_noun"}:
        return
    if not lemma.startswith("ال"):
        yield record(
            "ال" + lemma, index, prefixes=(("ال", "definite"),),
            features={"definiteness": "definite"}, source="generated", confidence=0.965,
        )
    if lemma.endswith("ة") and len(lemma) > 2:
        stem = lemma[:-1]
        yield record(
            stem + "ات", index, suffixes=(("ات", "plural_feminine"),),
            features={"number": "plural", "gender": "feminine"},
            source="generated", confidence=0.94,
        )
        for suffix, feature, case in (
            ("تان", "dual_feminine_nominative", "nominative"),
            ("تين", "dual_feminine_oblique", "oblique"),
        ):
            yield record(
                stem + suffix, index, suffixes=((suffix, feature),),
                features={"number": "dual", "gender": "feminine", "case": case},
                source="generated", confidence=0.90,
            )
        for suffix, feature, case in (
            ("تا", "dual_feminine_construct_nominative", "nominative"),
            ("تي", "dual_feminine_construct_oblique", "oblique"),
        ):
            yield record(
                stem + suffix, index, suffixes=((suffix, feature),),
                features={"number": "dual", "gender": "feminine", "case": case,
                          "construct_state": "true"},
                source="generated", confidence=0.86,
            )
    elif len(lemma) >= 3 and pos != "proper_noun":
        for suffix, feature, case in (
            ("ان", "dual_nominative", "nominative"),
            ("ين", "dual_oblique", "oblique"),
        ):
            yield record(
                lemma + suffix, index, suffixes=((suffix, feature),),
                features={"number": "dual", "case": case},
                source="generated", confidence=0.84,
            )
        for suffix, feature, case in (
            ("ا", "dual_construct_nominative", "nominative"),
            ("ي", "dual_construct_oblique", "oblique"),
        ):
            yield record(
                lemma + suffix, index, suffixes=((suffix, feature),),
                features={"number": "dual", "case": case, "construct_state": "true"},
                source="generated", confidence=0.80,
            )
    if lexeme["features"].get("gender") == "masculine" and pos in {"noun", "adjective"}:
        for suffix, feature, case in (
            ("ون", "plural_masculine_nominative", "nominative"),
            ("ين", "plural_masculine_oblique", "oblique"),
        ):
            yield record(
                lemma + suffix, index, suffixes=((suffix, feature),),
                features={"number": "plural", "gender": "masculine", "case": case},
                source="generated", confidence=0.93,
            )
        for suffix, feature, case in (
            ("و", "plural_masculine_construct_nominative", "nominative"),
            ("ي", "plural_masculine_construct_oblique", "oblique"),
        ):
            yield record(
                lemma + suffix, index, suffixes=((suffix, feature),),
                features={"number": "plural", "gender": "masculine", "case": case,
                          "construct_state": "true"},
                source="generated", confidence=0.88,
            )


def verb_records(index: int, lexeme: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    lemma = lexeme["lemma"]
    if lexeme["pos"] != "verb" or len(lemma) < 3:
        return
    for suffix, feature, person in (
        ("ت", "past_suffix", "1_or_2_or_3f"), ("نا", "past_suffix", "1p"),
        ("وا", "past_suffix", "3mp"), ("تم", "past_suffix", "2mp"),
        ("تن", "past_suffix", "2fp"),
    ):
        yield record(
            lemma + suffix, index, suffixes=((suffix, feature),),
            features={"aspect": "perfect", "person": person},
            source="generated", confidence=0.82,
        )
    if len(lemma) == 3:
        for prefix, person in (("ي", "3m"), ("ت", "2_or_3f"), ("ن", "1p"), ("أ", "1s")):
            form = prefix + lemma
            yield record(
                form, index, prefixes=((prefix, "imperfect_person"),),
                features={"aspect": "imperfect", "person": person},
                source="generated", confidence=0.78,
            )
            if prefix in {"ي", "ت"}:
                yield record(
                    form + "ون", index, prefixes=((prefix, "imperfect_person"),),
                    suffixes=(("ون", "plural_masculine_nominative"),),
                    features={"aspect": "imperfect", "person": person, "number": "plural"},
                    source="generated", confidence=0.76,
                )
                yield record(
                    "س" + form, index,
                    prefixes=(("س", "future"), (prefix, "imperfect_person")),
                    features={"aspect": "future", "person": person},
                    source="generated", confidence=0.77,
                )
                yield record(
                    "س" + form + "ون", index,
                    prefixes=(("س", "future"), (prefix, "imperfect_person")),
                    suffixes=(("ون", "plural_masculine_nominative"),),
                    features={"aspect": "future", "person": person, "number": "plural"},
                    source="generated", confidence=0.75,
                )


def clone(base: Mapping[str, Any], **changes: Any) -> dict[str, Any]:
    value = dict(base)
    value.update(changes)
    return value


def clitic_records(records: Sequence[dict[str, Any]], lexeme: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    for item in records:
        form, index, pos = item["form"], item["lexeme"], lexeme["pos"]
        item_features = item["features"]
        if pos in {"noun", "adjective", "verbal_noun", "proper_noun"}:
            if not form.startswith("ال"):
                features = dict(item_features) | {"definiteness": "definite"}
                yield record(
                    "ال" + form, index,
                    prefixes=(("ال", "definite"), *map(tuple, item["prefixes"])),
                    suffixes=tuple(map(tuple, item["suffixes"])), features=features,
                    source="generated", confidence=max(0.76, item["confidence"] - 0.025),
                )
                for surface, units in (
                    ("وال", (("و", "conjunction"), ("ال", "definite"))),
                    ("فال", (("ف", "conjunction"), ("ال", "definite"))),
                    ("بال", (("ب", "preposition"), ("ال", "definite"))),
                    ("كال", (("ك", "preposition"), ("ال", "definite"))),
                    ("لل", (("ل", "preposition"), ("ال", "definite"))),
                    ("وبال", (("و", "conjunction"), ("ب", "preposition"), ("ال", "definite"))),
                ):
                    yield record(
                        surface + form, index,
                        prefixes=(*units, *map(tuple, item["prefixes"])),
                        suffixes=tuple(map(tuple, item["suffixes"])), features=features,
                        source="generated", confidence=max(0.74, item["confidence"] - 0.04),
                    )
            for surface, units in (
                ("و", (("و", "conjunction"),)), ("ف", (("ف", "conjunction"),)),
                ("ب", (("ب", "preposition"),)), ("ل", (("ل", "preposition"),)),
            ):
                yield record(
                    surface + form, index,
                    prefixes=(*units, *map(tuple, item["prefixes"])),
                    suffixes=tuple(map(tuple, item["suffixes"])), features=item_features,
                    source="generated", confidence=max(0.72, item["confidence"] - 0.025),
                )
        elif pos in {"particle", "pronoun", "adverb"}:
            for surface, feature in (("و", "conjunction"), ("ف", "conjunction")):
                yield record(
                    surface + form, index,
                    prefixes=((surface, feature), *map(tuple, item["prefixes"])),
                    suffixes=tuple(map(tuple, item["suffixes"])), features=item_features,
                    source="generated", confidence=max(0.80, item["confidence"] - 0.02),
                )
        if form.startswith("ال"):
            tail = form[2:]
            for surface, units in (
                ("وال", (("و", "conjunction"), ("ال", "definite"))),
                ("فال", (("ف", "conjunction"), ("ال", "definite"))),
                ("بال", (("ب", "preposition"), ("ال", "definite"))),
                ("كال", (("ك", "preposition"), ("ال", "definite"))),
                ("لل", (("ل", "preposition"), ("ال", "definite"))),
                ("وبال", (("و", "conjunction"), ("ب", "preposition"), ("ال", "definite"))),
            ):
                yield record(
                    surface + tail, index, prefixes=units,
                    suffixes=tuple(map(tuple, item["suffixes"])), features=item_features,
                    source="generated", confidence=max(0.74, item["confidence"] - 0.02),
                )


def possessive_records(records: Sequence[dict[str, Any]], lexeme: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    if lexeme["pos"] not in {"noun", "adjective", "verbal_noun"}:
        return
    for item in records:
        if item["prefixes"] or item["suffixes"]:
            continue
        base = item["form"][:-1] + "ت" if item["form"].endswith("ة") else item["form"]
        for suffix, feature in (
            ("ها", "pronoun_feminine"), ("ه", "pronoun_masculine"),
            ("هم", "pronoun_masculine_plural"), ("هن", "pronoun_feminine_plural"),
            ("نا", "pronoun_first_plural"), ("ك", "pronoun_second"), ("ي", "pronoun_first"),
        ):
            yield record(
                base + suffix, item["lexeme"], suffixes=((suffix, feature),),
                features={"possessive": feature}, source="generated", confidence=0.91,
            )


def main() -> int:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    lexemes: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for index, raw in enumerate(payload["entries"]):
        lexeme = {
            "lemma": normalize(str(raw["lemma"])),
            "root": normalize(str(raw["root"])) if raw.get("root") else None,
            "pattern": str(raw["pattern"]) if raw.get("pattern") else None,
            "pos": str(raw["pos"]),
            "frequency": int(raw["frequency"]),
            "features": feature_map(raw.get("features", {})),
            "forms": [
                {"form": normalize(str(item["form"])), "features": feature_map(item.get("features", {}))}
                for item in raw.get("forms", ())
            ],
        }
        lexemes.append({key: value for key, value in lexeme.items() if key != "forms"})
        base = list(base_records(index, lexeme))
        productive = list(noun_records(index, lexeme)) + list(verb_records(index, lexeme))
        seed = base + productive
        generated = seed + list(clitic_records(seed, lexeme)) + list(possessive_records(base, lexeme))
        unique: dict[str, dict[str, Any]] = {}
        for item in generated:
            key = json.dumps(
                [item["form"], item["prefixes"], item["suffixes"], item["features"]],
                ensure_ascii=False, sort_keys=True,
            )
            current = unique.get(key)
            if current is None or item["confidence"] > current["confidence"]:
                unique[key] = item
        records.extend(unique.values())
    output = {"format": 1, "version": payload["version"], "lexemes": lexemes, "records": records}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(output, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    OUTPUT.write_bytes(serialized)
    COMPRESSED_OUTPUT.write_bytes(zlib.compress(serialized, level=9))
    print(
        f"wrote {len(lexemes)} lexemes and {len(records)} records to {OUTPUT} "
        f"({len(serialized)} bytes raw, {COMPRESSED_OUTPUT.stat().st_size} bytes zlib)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
