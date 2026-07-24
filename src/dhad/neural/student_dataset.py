"""Candidate-constrained records for distilling a teacher into the browser student."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .types import CandidateScore, NeuralRequest


@dataclass(frozen=True, slots=True)
class StudentExample:
    """One immutable groupwise-ranking example anchored to Rust candidates."""

    example_id: str
    split: str
    task: str
    sentence: str
    sentence_start: int
    token_index: int
    tokens: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    candidate_values: tuple[str, ...]
    candidate_lemmas: tuple[str, ...]
    candidate_parts_of_speech: tuple[str, ...]
    candidate_roots: tuple[str | None, ...]
    teacher_probabilities: tuple[float, ...]
    selected_index: int | None

    def as_json(self) -> dict[str, object]:
        """Return the stable JSONL representation consumed by student trainers."""

        return {
            "format": 1,
            "contract": "dhad-candidate-distillation-v1",
            "example_id": self.example_id,
            "split": self.split,
            "task": self.task,
            "sentence": self.sentence,
            "sentence_start": self.sentence_start,
            "token_index": self.token_index,
            "tokens": list(self.tokens),
            "candidates": [
                {
                    "id": candidate_id,
                    "value": value,
                    "lemma": lemma,
                    "pos": pos,
                    "root": root,
                    "teacher_probability": probability,
                }
                for candidate_id, value, lemma, pos, root, probability in zip(
                    self.candidate_ids,
                    self.candidate_values,
                    self.candidate_lemmas,
                    self.candidate_parts_of_speech,
                    self.candidate_roots,
                    self.teacher_probabilities,
                    strict=True,
                )
            ],
            "selected_index": self.selected_index,
        }


def _identity(request: NeuralRequest) -> str:
    payload = json.dumps(
        {
            "task": request.task.value,
            "sentence": request.sentence_text,
            "sentence_start": request.sentence_start,
            "token_index": request.token_index,
            "candidate_ids": [candidate.label for candidate in request.candidates],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _split(example_id: str) -> str:
    bucket = int(example_id[:8], 16) % 100
    if bucket < 80:
        return "train"
    if bucket < 90:
        return "validation"
    return "test"


def build_student_example(
    request: NeuralRequest,
    teacher_scores: tuple[CandidateScore, ...],
    *,
    confidence_threshold: float = 0.999,
) -> StudentExample:
    """Build a distillation row after proving labels equal the Rust candidate set."""

    if not 0.999 <= confidence_threshold <= 1.0:
        raise ValueError("confidence_threshold must be between 0.999 and 1")
    candidate_ids = tuple(candidate.label for candidate in request.candidates)
    if len(candidate_ids) < 2 or len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("student examples require at least two unique Rust candidates")
    scores: dict[str, CandidateScore] = {}
    allowed = set(candidate_ids)
    for score in teacher_scores:
        if score.label not in allowed:
            raise ValueError("teacher label is outside the Rust candidate set")
        if score.label in scores:
            raise ValueError("teacher returned a duplicate candidate label")
        scores[score.label] = score
    if set(scores) != allowed:
        raise ValueError("teacher must score every Rust candidate exactly once")
    raw = tuple(scores[label].probability for label in candidate_ids)
    total = sum(raw)
    if total <= 0.0:
        raise ValueError("teacher probability mass must be positive")
    probabilities = tuple(value / total for value in raw)
    selected_index = max(range(len(probabilities)), key=probabilities.__getitem__)
    if probabilities[selected_index] < confidence_threshold:
        selected_index = None
    example_id = _identity(request)
    return StudentExample(
        example_id=example_id,
        split=_split(example_id),
        task=request.task.value,
        sentence=request.sentence_text,
        sentence_start=request.sentence_start,
        token_index=request.token_index,
        tokens=request.tokens,
        candidate_ids=candidate_ids,
        candidate_values=tuple(candidate.value for candidate in request.candidates),
        candidate_lemmas=tuple(candidate.lemma for candidate in request.candidates),
        candidate_parts_of_speech=tuple(candidate.pos for candidate in request.candidates),
        candidate_roots=tuple(candidate.root for candidate in request.candidates),
        teacher_probabilities=probabilities,
        selected_index=selected_index,
    )


def write_student_jsonl(path: Path | str, examples: Iterable[StudentExample]) -> int:
    """Atomically write deterministic UTF-8 JSONL without partial datasets."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_name = stream.name
            for example in examples:
                stream.write(
                    json.dumps(example.as_json(), ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                )
                count += 1
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    return count
