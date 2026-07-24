"""Lightweight auditable n-gram classifier used by the default hybrid layer."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from ..text import NormalizationMode, normalize
from .types import CandidateScore, NeuralRequest, NeuralTask

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "neural"
DEFAULT_MODEL_PATH = DATA_DIR / "context_model.json"
MODEL_SCHEMA_PATH = DATA_DIR / "context_model.schema.json"


def _validate(payload: Mapping[str, Any]) -> None:
    schema = json.loads(MODEL_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload), key=lambda error: list(error.path)
    )
    if errors:
        details = "; ".join(error.message for error in errors[:5])
        raise ValueError(f"Neural context model validation failed: {details}")


def _softmax(values: list[float], temperature: float) -> list[float]:
    if not values:
        return []
    scaled = [value / temperature for value in values]
    maximum = max(scaled)
    exponents = [math.exp(value - maximum) for value in scaled]
    total = sum(exponents)
    return [value / total for value in exponents]


class StatisticalContextBackend:
    """Sparse linear n-gram model with deterministic, inspectable weights."""

    def __init__(self, path: Path | str = DEFAULT_MODEL_PATH):
        self.path = Path(path)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        _validate(payload)
        self.version = str(payload["version"])
        self.temperature = float(payload.get("temperature", 1.0))
        self.window = int(payload.get("window", 2))
        self._tasks: Mapping[str, Any] = payload["tasks"]

    @property
    def name(self) -> str:
        return f"statistical-ngram/{self.version}"

    @property
    def available(self) -> bool:
        return True

    @staticmethod
    def _surface(value: str) -> str:
        return normalize(value, NormalizationMode.LOOKUP)

    def _features(self, request: NeuralRequest, candidate_pos: str) -> frozenset[str]:
        index = request.token_index
        tokens = tuple(self._surface(value) for value in request.tokens)
        pos = request.parts_of_speech
        features: set[str] = {f"candidate_pos:{candidate_pos}"}
        if index == 0:
            features.add("bos")
        if index + 1 == len(tokens):
            features.add("eos")
        for distance in range(1, self.window + 1):
            left = index - distance
            right = index + distance
            if left >= 0:
                features.add(f"left{distance}:{tokens[left]}")
                features.add(f"left_pos{distance}:{pos[left]}")
            if right < len(tokens):
                features.add(f"right{distance}:{tokens[right]}")
                features.add(f"right_pos{distance}:{pos[right]}")
        if index + 1 < len(tokens) and tokens[index + 1].startswith("ال"):
            features.add("next_definite")
        if (
            candidate_pos == "verb"
            and index + 1 < len(pos)
            and pos[index + 1]
            in {
                "noun",
                "proper_noun",
                "pronoun",
            }
        ):
            features.add("candidate_verb_before_nominal")
        if candidate_pos in {"noun", "proper_noun", "verbal_noun"} and index + 1 < len(pos):
            if pos[index + 1] == "adjective":
                features.add("candidate_noun_before_adjective")
        return frozenset(features)

    def _entry(self, request: NeuralRequest) -> Mapping[str, Any] | None:
        task = self._tasks.get(request.task.value, {})
        return task.get(self._surface(request.token))

    def candidate_labels(self, task: NeuralTask, token: str) -> tuple[str, ...]:
        """Return configured labels for a token/task without exposing weights."""

        entry = self._tasks.get(task.value, {}).get(self._surface(token))
        if entry is None:
            return ()
        return tuple(entry["candidates"])

    def score(self, request: NeuralRequest) -> tuple[CandidateScore, ...]:
        if not request.candidates:
            return ()
        entry = self._entry(request)
        if entry is None:
            return ()
        configurations = entry["candidates"]
        raw_scores: list[float] = []
        evidence_by_candidate: list[tuple[str, ...]] = []
        labels: list[str] = []
        for candidate in request.candidates:
            config = configurations.get(candidate.label)
            if config is None:
                raw_scores.append(float("-inf"))
                evidence_by_candidate.append(())
                labels.append(candidate.label)
                continue
            score = float(config.get("bias", 0.0)) + float(candidate.prior)
            features = self._features(request, candidate.pos)
            evidence: list[str] = []
            for feature, weight in config.get("weights", {}).items():
                if feature in features:
                    numeric = float(weight)
                    score += numeric
                    evidence.append(f"{feature}:{numeric:+.3f}")
            raw_scores.append(score)
            evidence_by_candidate.append(tuple(evidence))
            labels.append(candidate.label)
        finite = [value for value in raw_scores if math.isfinite(value)]
        if not finite:
            return ()
        floor = min(finite) - 30.0
        probabilities = _softmax(
            [value if math.isfinite(value) else floor for value in raw_scores], self.temperature
        )
        scored = tuple(
            CandidateScore(label, probability, raw, evidence)
            for label, probability, raw, evidence in zip(
                labels, probabilities, raw_scores, evidence_by_candidate
            )
        )
        return tuple(sorted(scored, key=lambda item: (-item.probability, item.label)))


@lru_cache(maxsize=1)
def default_statistical_backend() -> StatisticalContextBackend:
    """Return the process-wide packaged sparse context model."""

    return StatisticalContextBackend()
