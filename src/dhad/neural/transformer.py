"""Optional HuggingFace production backend with lazy dependency loading."""

from __future__ import annotations

import importlib.util
from typing import Any

from .types import CandidateScore, NeuralRequest


class TransformerBackend:
    """Load a sequence-classification model that emits candidate labels.

    The model's ``id2label`` values must equal the labels supplied in each
    :class:`NeuralRequest`. Dependencies and weights are loaded only at first
    inference, so installing core Dhad never downloads a model.
    """

    def __init__(self, model_name_or_path: str, *, device: str = "cpu", max_length: int = 256):
        if not model_name_or_path.strip():
            raise ValueError("model_name_or_path cannot be empty")
        if max_length < 16:
            raise ValueError("max_length must be at least 16")
        self.model_name_or_path = model_name_or_path
        self.device = device
        self.max_length = max_length
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._torch: Any | None = None

    @property
    def name(self) -> str:
        return f"transformer/{self.model_name_or_path}"

    @property
    def available(self) -> bool:
        return (
            importlib.util.find_spec("torch") is not None
            and importlib.util.find_spec("transformers") is not None
        )

    def _load(self) -> None:
        if self._model is not None:
            return
        if not self.available:
            raise RuntimeError(
                "TransformerBackend requires optional dependencies 'torch' and 'transformers'"
            )
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name_or_path)
        self._model = AutoModelForSequenceClassification.from_pretrained(
            self.model_name_or_path
        ).to(self.device)
        self._model.eval()

    @staticmethod
    def _marked_text(request: NeuralRequest) -> str:
        values = list(request.tokens)
        values[request.token_index] = f"[TARGET] {values[request.token_index]} [/TARGET]"
        return " ".join(values)

    def score(self, request: NeuralRequest) -> tuple[CandidateScore, ...]:
        if not request.candidates:
            return ()
        self._load()
        assert self._tokenizer is not None and self._model is not None and self._torch is not None
        inputs = self._tokenizer(
            self._marked_text(request),
            return_tensors="pt",
            truncation=True,
            max_length=self.max_length,
        )
        inputs = {name: tensor.to(self.device) for name, tensor in inputs.items()}
        with self._torch.no_grad():
            logits = self._model(**inputs).logits[0]
            probabilities = self._torch.softmax(logits, dim=-1).detach().cpu().tolist()
        id2label = {int(key): str(value) for key, value in self._model.config.id2label.items()}
        allowed = {candidate.label for candidate in request.candidates}
        out = [
            CandidateScore(id2label[index], float(probability), float(logits[index].item()))
            for index, probability in enumerate(probabilities)
            if id2label.get(index) in allowed
        ]
        total = sum(item.probability for item in out)
        if total <= 0.0:
            return ()
        normalized = tuple(
            CandidateScore(item.label, item.probability / total, item.score, item.evidence)
            for item in out
        )
        return tuple(sorted(normalized, key=lambda item: (-item.probability, item.label)))
