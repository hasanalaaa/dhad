"""Optional ONNX Runtime production backend with lazy dependency loading.

This backend runs a real sequence-classification transformer exported to the
ONNX format through :mod:`onnxruntime`, using a HuggingFace *fast* tokenizer
(``tokenizer.json``) for encoding. It is the runtime-agnostic sibling of
:class:`dhad.neural.transformer.TransformerBackend`: it honours the exact same
:class:`~dhad.neural.backend.NeuralBackend` contract (marked target span →
logits → soft-max → filter to the request's candidate labels → renormalise),
so the confidence-gated :class:`~dhad.neural.gateway.HybridNeuralEngine` can
consume it as a drop-in scorer.

Design guarantees
-----------------
* **Zero import cost.** Neither ``onnxruntime`` nor ``tokenizers`` is imported
  until the first inference. Installing core Dhad never pulls a heavyweight
  runtime, and constructing the backend never touches the disk beyond cheap
  path resolution.
* **Honest availability.** :attr:`available` is ``True`` only when the runtime,
  a tokenizer, the ``model.onnx`` weights, and a label map can all be resolved
  in the current environment. When any piece is missing the backend reports
  itself unavailable and the hybrid engine transparently falls back to the
  deterministic pipeline — it never fabricates a score.
* **Model-driven I/O binding.** The feed dictionary is built from the graph's
  declared inputs (``input_ids`` / ``attention_mask`` / ``token_type_ids``),
  each cast to the exact tensor dtype the model expects, so int32 and int64
  exports both work without configuration.

Expected on-disk layout (matching an ``optimum`` ONNX export)::

    model_dir/
        model.onnx        # the exported classification graph
        tokenizer.json    # a HuggingFace fast tokenizer
        config.json       # carries ``id2label`` (unless labels are passed)
"""

from __future__ import annotations

import importlib.util
import json
import os
import threading
from pathlib import Path
from typing import Any, Mapping, Sequence

from .types import CandidateScore, NeuralRequest

_MODEL_FILENAME = "model.onnx"
_TOKENIZER_FILENAME = "tokenizer.json"
_CONFIG_FILENAME = "config.json"

_ONNX_TO_NUMPY = {
    "tensor(int64)": "int64",
    "tensor(int32)": "int32",
    "tensor(float)": "float32",
    "tensor(float16)": "float16",
    "tensor(double)": "float64",
}


class OnnxBackend:
    """Score contextual candidates with an ONNX sequence-classification model.

    The model's ``id2label`` values must match the ``label`` field of the
    candidates supplied in each :class:`NeuralRequest`; any model label that is
    not among a request's candidates is ignored, and the surviving
    probabilities are renormalised so they sum to one.

    Parameters
    ----------
    model_path:
        Either a directory containing ``model.onnx`` (plus ``tokenizer.json``
        and ``config.json``) or a direct path to an ``.onnx`` file. When a file
        is given, ``tokenizer.json`` and ``config.json`` are looked up beside it
        unless overridden.
    tokenizer_path:
        Explicit path to a fast-tokenizer ``tokenizer.json`` (or a directory
        containing one). Defaults to the sibling/child of ``model_path``.
    labels:
        Explicit ordered label list. When given it overrides ``config.json`` and
        maps position ``i`` to ``labels[i]``.
    providers:
        ONNX Runtime execution providers. Defaults to CPU-only, which is the
        correct, reproducible choice for a proof-reading service.
    max_length:
        Maximum token window fed to the model (must be at least 16).
    """

    def __init__(
        self,
        model_path: str | os.PathLike[str],
        *,
        tokenizer_path: str | os.PathLike[str] | None = None,
        labels: Sequence[str] | None = None,
        providers: Sequence[str] | None = None,
        max_length: int = 256,
    ) -> None:
        if not str(model_path).strip():
            raise ValueError("model_path cannot be empty")
        if max_length < 16:
            raise ValueError("max_length must be at least 16")
        if labels is not None:
            labels = tuple(str(label) for label in labels)
            if not labels:
                raise ValueError("labels, when provided, cannot be empty")

        self.model_path = str(model_path)
        self.max_length = int(max_length)
        self.providers = tuple(providers) if providers is not None else ("CPUExecutionProvider",)

        source = Path(model_path)
        if source.is_dir():
            self._model_file = source / _MODEL_FILENAME
            self._config_file = source / _CONFIG_FILENAME
            default_tokenizer = source / _TOKENIZER_FILENAME
        else:
            self._model_file = source
            self._config_file = source.with_name(_CONFIG_FILENAME)
            default_tokenizer = source.with_name(_TOKENIZER_FILENAME)
        self._tokenizer_path = Path(tokenizer_path) if tokenizer_path is not None else default_tokenizer
        self._explicit_labels = labels

        self._lock = threading.Lock()
        self._session: Any | None = None
        self._tokenizer: Any | None = None
        self._transformers_tokenizer = False
        self._id2label: dict[int, str] = {}
        self._input_dtypes: dict[str, str] = {}

    # ------------------------------------------------------------------ meta

    @property
    def name(self) -> str:
        return f"onnx/{self.model_path}"

    @property
    def available(self) -> bool:
        """Whether a real inference can run in the current environment.

        This never raises and never loads the model: it only checks that the
        runtime, a tokenizer implementation, the weights file, a resolvable
        tokenizer, and a label source are all present.
        """

        if importlib.util.find_spec("onnxruntime") is None:
            return False
        if not self._model_file.is_file():
            return False
        if not self._tokenizer_available():
            return False
        if self._explicit_labels is None and not self._config_file.is_file():
            return False
        return True

    def _tokenizer_available(self) -> bool:
        if self._tokenizer_path.is_file() and importlib.util.find_spec("tokenizers") is not None:
            return True
        # A directory export can still be loaded through transformers' AutoTokenizer.
        directory = self._tokenizer_path if self._tokenizer_path.is_dir() else self._tokenizer_path.parent
        return (
            directory.is_dir()
            and (directory / _TOKENIZER_FILENAME).is_file()
            and (
                importlib.util.find_spec("tokenizers") is not None
                or importlib.util.find_spec("transformers") is not None
            )
        )

    # --------------------------------------------------------------- loading

    def _load(self) -> None:
        if self._session is not None:
            return
        with self._lock:
            if self._session is not None:
                return
            if importlib.util.find_spec("onnxruntime") is None:
                raise RuntimeError("OnnxBackend requires the optional dependency 'onnxruntime'")
            if not self._model_file.is_file():
                raise RuntimeError(f"ONNX model file not found: {self._model_file}")

            import onnxruntime as ort

            session = ort.InferenceSession(
                str(self._model_file), providers=list(self.providers)
            )
            self._input_dtypes = {
                spec.name: _ONNX_TO_NUMPY.get(spec.type, "int64")
                for spec in session.get_inputs()
            }
            self._tokenizer, self._transformers_tokenizer = self._build_tokenizer()
            self._id2label = self._resolve_labels()
            if not self._id2label:
                raise RuntimeError(
                    "OnnxBackend could not resolve an id2label map; pass labels= or "
                    "provide a config.json with an 'id2label' field"
                )
            self._session = session

    def _build_tokenizer(self) -> tuple[Any, bool]:
        if self._tokenizer_path.is_file() and importlib.util.find_spec("tokenizers") is not None:
            from tokenizers import Tokenizer

            tokenizer = Tokenizer.from_file(str(self._tokenizer_path))
            tokenizer.enable_truncation(max_length=self.max_length)
            return tokenizer, False

        directory = self._tokenizer_path if self._tokenizer_path.is_dir() else self._tokenizer_path.parent
        if importlib.util.find_spec("tokenizers") is not None and (
            directory / _TOKENIZER_FILENAME
        ).is_file():
            from tokenizers import Tokenizer

            tokenizer = Tokenizer.from_file(str(directory / _TOKENIZER_FILENAME))
            tokenizer.enable_truncation(max_length=self.max_length)
            return tokenizer, False

        if importlib.util.find_spec("transformers") is not None:
            from transformers import AutoTokenizer

            return AutoTokenizer.from_pretrained(str(directory)), True

        raise RuntimeError(
            "OnnxBackend requires 'tokenizers' (a tokenizer.json) or 'transformers'"
        )

    def _resolve_labels(self) -> dict[int, str]:
        if self._explicit_labels is not None:
            return {index: label for index, label in enumerate(self._explicit_labels)}
        if not self._config_file.is_file():
            return {}
        payload = json.loads(self._config_file.read_text(encoding="utf-8"))
        raw = payload.get("id2label")
        if not isinstance(raw, Mapping):
            return {}
        resolved: dict[int, str] = {}
        for key, value in raw.items():
            try:
                resolved[int(key)] = str(value)
            except (TypeError, ValueError):
                continue
        return resolved

    # --------------------------------------------------------------- scoring

    @staticmethod
    def _marked_text(request: NeuralRequest) -> str:
        values = list(request.tokens)
        target = values[request.token_index]
        values[request.token_index] = f"[TARGET] {target} [/TARGET]"
        return " ".join(values)

    def _encode(self, text: str) -> dict[str, Any]:
        import numpy as np

        if self._transformers_tokenizer:
            encoded = self._tokenizer(
                text,
                truncation=True,
                max_length=self.max_length,
                return_tensors="np",
            )
            return {name: np.asarray(tensor) for name, tensor in encoded.items()}

        encoding = self._tokenizer.encode(text)
        ids = list(encoding.ids)[: self.max_length]
        mask = list(encoding.attention_mask)[: self.max_length]
        type_ids = list(getattr(encoding, "type_ids", []) or [0] * len(ids))[: self.max_length]
        return {
            "input_ids": np.asarray([ids]),
            "attention_mask": np.asarray([mask]),
            "token_type_ids": np.asarray([type_ids]),
        }

    def score(self, request: NeuralRequest) -> tuple[CandidateScore, ...]:
        if not request.candidates:
            return ()
        self._load()

        import numpy as np

        encoded = self._encode(self._marked_text(request))
        feeds = {
            name: encoded[name].astype(dtype)
            for name, dtype in self._input_dtypes.items()
            if name in encoded
        }
        if not feeds:
            # The graph declares no input this tokenizer can satisfy.
            return ()

        outputs = self._session.run(None, feeds)
        logits = np.asarray(outputs[0], dtype=np.float64)
        if logits.ndim == 2:
            logits = logits[0]
        elif logits.ndim != 1:
            logits = logits.reshape(-1)

        probabilities = _stable_softmax(logits)
        allowed = {candidate.label for candidate in request.candidates}
        surviving = [
            CandidateScore(self._id2label[index], float(probabilities[index]), float(logits[index]))
            for index in range(len(probabilities))
            if index in self._id2label and self._id2label[index] in allowed
        ]
        total = sum(item.probability for item in surviving)
        if total <= 0.0:
            return ()
        normalized = tuple(
            CandidateScore(item.label, item.probability / total, item.score, item.evidence)
            for item in surviving
        )
        return tuple(sorted(normalized, key=lambda item: (-item.probability, item.label)))


def _stable_softmax(logits: Any) -> Any:
    import numpy as np

    array = np.asarray(logits, dtype=np.float64)
    if array.size == 0:
        return array
    shifted = array - array.max()
    exponents = np.exp(shifted)
    return exponents / exponents.sum()


def onnx_backend_from_env(
    env_var: str = "DHAD_NEURAL_ONNX_MODEL", **kwargs: Any
) -> OnnxBackend | None:
    """Build an :class:`OnnxBackend` from an environment variable, or ``None``.

    This is an explicit, opt-in escape hatch for deployments that ship an ONNX
    disambiguation model: set ``DHAD_NEURAL_ONNX_MODEL`` to the export
    directory and pass ``backend=onnx_backend_from_env()`` when constructing a
    :class:`~dhad.neural.gateway.HybridNeuralEngine`. The default engine keeps
    using the auditable statistical backend, so importing Dhad or reading the
    variable never changes behaviour on its own.
    """

    path = os.environ.get(env_var)
    if not path:
        return None
    return OnnxBackend(path, **kwargs)
