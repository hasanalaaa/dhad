"""V2 Phase 2 — sweep-line overlap indexes, proven equivalent to the
historical quadratic reference implementations bit-for-bit."""

import random
import math

from dhad.match import Match, dedupe
from dhad.spans import DisjointSpanIndex, FrozenSpanIndex, filter_non_overlapping


def _random_spans(rng, count, universe=500, max_len=12):
    spans = []
    for _ in range(count):
        start = rng.randrange(universe)
        spans.append((start, start + rng.randrange(1, max_len)))
    return spans


def _brute_overlaps(spans, start, end):
    return any(start < b and a < end for a, b in spans)


class TestFrozenSpanIndex:
    def test_empty_index_never_overlaps(self):
        index = FrozenSpanIndex([])
        assert not index.overlaps(0, 10)
        assert len(index) == 0

    def test_exhaustive_equivalence_with_bruteforce(self):
        rng = random.Random(20260721)
        for trial in range(200):
            spans = _random_spans(rng, rng.randrange(0, 40))
            index = FrozenSpanIndex(spans)
            for _ in range(50):
                start = rng.randrange(520)
                end = start + rng.randrange(1, 15)
                assert index.overlaps(start, end) == _brute_overlaps(spans, start, end), (
                    trial,
                    spans,
                    (start, end),
                )

    def test_touching_spans_do_not_overlap(self):
        index = FrozenSpanIndex([(10, 20)])
        assert not index.overlaps(20, 25)
        assert not index.overlaps(0, 10)
        assert index.overlaps(19, 21)
        assert index.overlaps(0, 11)


class TestDisjointSpanIndex:
    def test_incremental_equivalence_with_bruteforce(self):
        rng = random.Random(4)
        for _trial in range(200):
            index = DisjointSpanIndex()
            stored: list[tuple[int, int]] = []
            for _ in range(60):
                start = rng.randrange(400)
                end = start + rng.randrange(1, 10)
                expected = _brute_overlaps(stored, start, end)
                assert index.overlaps(start, end) == expected
                if not expected:
                    index.add(start, end)
                    stored.append((start, end))
            assert len(index) == len(stored)

    def test_adversarial_insertions_keep_logarithmic_tree_depth(self):
        index = DisjointSpanIndex()
        count = 4096
        for start in reversed(range(0, count * 2, 2)):
            assert not index.overlaps(start, start + 1)
            index.add(start, start + 1)

        assert len(index) == count
        assert index.depth <= 2 * math.ceil(math.log2(count + 1))


def _reference_filter(candidates, accepted):
    """The exact pre-V2 quadratic per-layer filter."""

    return [
        candidate
        for candidate in candidates
        if not any(candidate.overlaps(existing) for existing in accepted)
    ]


def _reference_dedupe(matches):
    """The exact pre-V2 quadratic dedupe, kept verbatim as an oracle."""

    severity_rank = {"error": 3, "warning": 2, "hint": 1}
    ranked = sorted(
        matches,
        key=lambda item: (
            -item.priority,
            -item.confidence,
            -severity_rank[item.severity],
            -int(bool(item.replacements)),
            -item.length,
            item.offset,
            item.rule_id,
        ),
    )
    kept = []
    for candidate in ranked:
        if not any(candidate.overlaps(winner) for winner in kept):
            kept.append(candidate)
    return sorted(kept, key=lambda item: (item.offset, item.end, item.rule_id))


def _random_matches(rng, count):
    categories = ("spelling", "grammar", "style", "punctuation", "dialect")
    severities = ("error", "warning", "hint")
    matches = []
    for index in range(count):
        start = rng.randrange(300)
        matches.append(
            Match(
                rule_id=f"R{rng.randrange(40)}",
                category=rng.choice(categories),
                message="m",
                offset=start,
                length=rng.randrange(1, 9),
                replacements=["x"] if rng.random() < 0.5 else [],
                severity=rng.choice(severities),
                confidence=rng.choice((0.5, 0.7, 0.9, 1.0)),
                priority=rng.randrange(-2, 3),
            )
        )
    return matches


class TestPipelineEquivalence:
    def test_layer_filter_equivalent_to_reference(self):
        rng = random.Random(99)
        for _trial in range(100):
            accepted = _random_matches(rng, rng.randrange(0, 50))
            candidates = _random_matches(rng, rng.randrange(0, 50))
            assert filter_non_overlapping(candidates, accepted) == _reference_filter(
                candidates, accepted
            )

    def test_candidates_not_filtered_against_each_other(self):
        overlapping = [
            Match("A", "spelling", "m", 0, 5),
            Match("B", "spelling", "m", 3, 5),
        ]
        result = filter_non_overlapping(overlapping, [])
        assert result == overlapping

    def test_dedupe_equivalent_to_reference(self):
        rng = random.Random(1234)
        for _trial in range(120):
            matches = _random_matches(rng, rng.randrange(0, 80))
            assert dedupe(list(matches)) == _reference_dedupe(list(matches))

    def test_dedupe_dense_adversarial_case(self):
        rng = random.Random(7)
        matches = _random_matches(rng, 1500)
        assert dedupe(list(matches)) == _reference_dedupe(list(matches))
