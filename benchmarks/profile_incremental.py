"""Terminal profiling for V2 Phase 2 — keystroke latency of incremental
sessions versus full passes.

Usage::

    python benchmarks/profile_incremental.py [--words 10000] [--edits 60]

Prints p50/p95/max for single-word mutations applied at random positions in
a large document, plus the full-pass baseline for the same document.
"""

from __future__ import annotations

import argparse
import random
import statistics
import time

from dhad import Dhad

SENTENCES = [
    "ذهبت الى المدرسه صباحا والتقيت بالمعلم الجديد في الساحة الكبيرة.",
    "انا احب القراءة كثيرا في المساء بعد انتهاء العمل الطويل.",
    "عملت ثلاثة سنوات في هذه الشركة قبل ان انتقل الى بغداد.",
    "كان الطقس جميلا والسماء صافية والهواء عليلا في ذلك الصباح.",
    "سأزورك انشاء الله في نهاية الاسبوع مع بقية الاصدقاء القدامى.",
    "هذا الكتاب مفيد جدا للطلاب الذين يدرسون اللغة العربية الفصحى.",
]

WORDS = ["اليوم", "غدا", "المدرسه", "الجميل", "كتاب", "الى", "انا", "المكتبه"]


def build_document(word_target: int, rng: random.Random) -> str:
    parts: list[str] = []
    words = 0
    while words < word_target:
        sentence = rng.choice(SENTENCES)
        parts.append(sentence)
        words += len(sentence.split())
    return " ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--words", type=int, default=10_000)
    parser.add_argument("--edits", type=int, default=60)
    parser.add_argument("--target-ms", type=float, default=15.0)
    args = parser.parse_args()

    rng = random.Random(20260721)
    document = build_document(args.words, rng)
    checker = Dhad()

    started = time.perf_counter()
    session = checker.session(document)
    load_ms = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    checker.check(document)
    full_ms = (time.perf_counter() - started) * 1000

    timings: list[float] = []
    for _ in range(args.edits):
        words = session.text.split(" ")
        index = rng.randrange(len(words))
        words[index] = rng.choice(WORDS)
        edited = " ".join(words)
        started = time.perf_counter()
        session.update(edited)
        timings.append((time.perf_counter() - started) * 1000)

    timings.sort()
    p50 = statistics.median(timings)
    p95 = timings[int(len(timings) * 0.95) - 1]
    word_count = len(document.split())

    print(f"document: {word_count} words / {len(document)} chars / {len(session.matches)} matches")
    print(f"initial load (full pass): {load_ms:8.1f} ms")
    print(f"full re-check baseline:   {full_ms:8.1f} ms")
    print(f"single-word mutation over {args.edits} edits:")
    print(f"  p50: {p50:6.2f} ms")
    print(f"  p95: {p95:6.2f} ms")
    print(f"  max: {timings[-1]:6.2f} ms")
    print(f"  speedup vs full pass (p50): {full_ms / p50:,.0f}x")
    ok = p50 < args.target_ms
    print(f"TARGET p50 < {args.target_ms:.0f} ms: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
