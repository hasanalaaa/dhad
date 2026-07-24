"""Export the portable deterministic rule subset for the WASM engine.

Selects every ``literal`` rule with plain word-boundary semantics (no prefix
groups, no context window, no exceptions — the shapes the Rust scanner
reproduces exactly), and emits:

* ``web_demo/rules.json`` — the rule pack the browser engine loads.
* ``rust/dhad-core-rs/tests/data/rules_golden.jsonl`` — Python-oracle
  matches for a corpus of test texts, replayed by ``cargo test`` to prove
  the Rust scanner is byte-identical on this subset.

Regenerate after any rule change and commit both artifacts together::

    python tools/export_wasm_rules.py
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from dhad.match import dedupe
from dhad.rules import RULES_DIR, _compile

ROOT = Path(__file__).resolve().parents[1]
RULES_OUT = ROOT / "web_demo" / "rules.json"
GOLDEN_OUT = ROOT / "rust" / "dhad-core-rs" / "tests" / "data" / "rules_golden.jsonl"

GOLDEN_TEXTS = [
    "",
    "ذهبت الى المدرسه قبل ثلاثة سنوات.",
    "انا احب القراءة، لاكن الوقت ضيق.",
    "سأزورك انشاء الله غدا او بعده.",
    "هاذا كتابي وهاذه قصتي.",
    "قرأت الكتاب ثم ذهبت إلى البيت.",  # clean text: no matches expected
    "الى الى الى — تكرار متعمد.",
    "نص يخلط English مع الى العربيه.",
    "«الى» بين علامتي اقتباس, وبعدها فاصلة لاتينية.",
    "بالمدرسه لاحقة وسابقة مثل والمدرسه لا يلتقطها النمط المجرد.",
]


def portable_rules():
    """Yield ``(canonical_data, compiled_rule)`` for every portable rule."""

    for path in sorted(RULES_DIR.glob("*.yaml")):
        for raw in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            compiled = _compile(raw, source=str(path))
            if compiled.type != "literal" or compiled.has_prefix_group:
                continue
            if compiled.exceptions or compiled.context_before or compiled.context_after:
                continue
            if "default" not in compiled.profiles:
                continue
            yield raw["pattern"], compiled


def main() -> int:
    selected = list(portable_rules())
    payload = {
        "format": 1,
        "source": "dhad rule engine (literal subset)",
        "rule_count": len(selected),
        "rules": [
            {
                "id": rule.id,
                "pattern": pattern,
                "suggestions": list(rule.suggestions),
                "message": rule.message,
                "category": rule.category,
                "severity": rule.severity,
                "confidence": rule.confidence,
                "priority": rule.priority,
                "autofix": rule.autofix,
                "explanation": rule.explanation,
            }
            for pattern, rule in selected
        ],
    }
    RULES_OUT.parent.mkdir(parents=True, exist_ok=True)
    RULES_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    GOLDEN_OUT.parent.mkdir(parents=True, exist_ok=True)
    with GOLDEN_OUT.open("w", encoding="utf-8") as handle:
        for text in GOLDEN_TEXTS:
            raw = [match for _pattern, rule in selected for match in rule.apply(text)]
            record = {
                "text": text,
                "matches": [
                    [m.rule_id, m.offset, m.length, m.replacements[0] if m.replacements else ""]
                    for m in raw
                ],
                "resolved": [
                    [m.rule_id, m.offset, m.length]
                    for m in dedupe(list(raw))
                ],
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"exported {len(selected)} portable rules → {RULES_OUT}")
    print(f"golden corpus ({len(GOLDEN_TEXTS)} texts) → {GOLDEN_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
