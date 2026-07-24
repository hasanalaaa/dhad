"""Candidate-constrained teacher/student dataset contract."""

from __future__ import annotations

import json

import pytest

from dhad.neural.student_dataset import build_student_example, write_student_jsonl
from dhad.neural.types import CandidateScore, NeuralCandidate, NeuralRequest, NeuralTask


def request() -> NeuralRequest:
    return NeuralRequest(
        task=NeuralTask.WORD_SENSE,
        sentence_text="كتب الطالب الدرس",
        sentence_start=0,
        token_index=0,
        tokens=("كتب", "الطالب", "الدرس"),
        parts_of_speech=("unknown", "noun", "noun"),
        candidates=(
            NeuralCandidate("كتب|verb|كتب", "كتب", "كتب", "verb", "كتب"),
            NeuralCandidate("كتاب|noun|كتب", "كتب", "كتاب", "noun", "كتب"),
        ),
    )


def scores(first: float = 0.9995) -> tuple[CandidateScore, ...]:
    return (
        CandidateScore("كتب|verb|كتب", first, 9.0),
        CandidateScore("كتاب|noun|كتب", 1.0 - first, 1.0),
    )


def test_student_example_contains_only_rust_candidates_and_teacher_distribution() -> None:
    example = build_student_example(request(), scores(), confidence_threshold=0.999)
    assert example.selected_index == 0
    assert example.candidate_ids == ("كتب|verb|كتب", "كتاب|noun|كتب")
    assert example.teacher_probabilities == pytest.approx((0.9995, 0.0005))
    assert example.split in {"train", "validation", "test"}
    payload = example.as_json()
    assert payload["candidates"][0]["id"] == example.candidate_ids[0]
    assert "generated_text" not in json.dumps(payload, ensure_ascii=False)


def test_student_example_rejects_teacher_labels_outside_the_candidate_set() -> None:
    unsafe = scores() + (CandidateScore("invented|word|-", 0.1, 4.0),)
    with pytest.raises(ValueError, match="outside the Rust candidate set"):
        build_student_example(request(), unsafe)


def test_student_example_abstains_when_teacher_does_not_clear_gate() -> None:
    example = build_student_example(request(), scores(0.7), confidence_threshold=0.999)
    assert example.selected_index is None


def test_student_split_is_stable_and_jsonl_is_atomic(tmp_path) -> None:
    first = build_student_example(request(), scores())
    second = build_student_example(request(), scores())
    assert first.example_id == second.example_id
    assert first.split == second.split
    destination = tmp_path / "student.jsonl"
    count = write_student_jsonl(destination, [first, second])
    assert count == 2
    records = [json.loads(line) for line in destination.read_text(encoding="utf-8").splitlines()]
    assert [record["example_id"] for record in records] == [first.example_id, second.example_id]
