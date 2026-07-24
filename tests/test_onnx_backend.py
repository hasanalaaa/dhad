"""Tests for the ONNX Runtime contextual backend.

These tests build a small but genuine ONNX sequence-classification graph and a
real HuggingFace fast tokenizer at runtime, then drive them through
``onnxruntime`` end to end. Nothing here is mocked: the backend loads real
weights, encodes real text, and runs a real forward pass. The suite is skipped
only when the optional ONNX stack is not installed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("onnxruntime")
pytest.importorskip("tokenizers")
onnx = pytest.importorskip("onnx")

import numpy as np  # noqa: E402
from onnx import TensorProto, helper, numpy_helper  # noqa: E402
from tokenizers import Tokenizer, models, pre_tokenizers  # noqa: E402

from dhad.morphology import default_analyzer  # noqa: E402
from dhad.neural import (  # noqa: E402
    HybridNeuralEngine,
    NeuralBackend,
    NeuralReport,
    OnnxBackend,
    onnx_backend_from_env,
)
from dhad.neural.types import NeuralCandidate, NeuralRequest, NeuralTask  # noqa: E402
from dhad.syntax import default_syntax_engine  # noqa: E402

LABELS = ("كتب|verb|كتب", "كتاب|noun|كتب")
_VOCAB_WORDS = ("كتب", "الطالب", "الدرس", "ثلاثة", "مفيدة", "كتاب")


def _build_model(path: Path, num_labels: int) -> None:
    """Write a tiny linear classifier that consumes int64 ids and int32 mask.

    The two inputs use different integer dtypes on purpose, so the backend's
    per-input dtype casting is exercised by a real graph.
    """

    input_ids = helper.make_tensor_value_info("input_ids", TensorProto.INT64, ["b", "s"])
    attention = helper.make_tensor_value_info("attention_mask", TensorProto.INT32, ["b", "s"])
    logits = helper.make_tensor_value_info("logits", TensorProto.FLOAT, ["b", num_labels])
    weight = numpy_helper.from_array(
        np.linspace(0.05, -0.05, num_labels, dtype=np.float32).reshape(1, num_labels), name="W"
    )
    bias = numpy_helper.from_array(
        np.linspace(0.0, 0.3, num_labels, dtype=np.float32), name="bias"
    )
    axes = numpy_helper.from_array(np.array([1], dtype=np.int64), name="axes")
    nodes = [
        helper.make_node("Cast", ["input_ids"], ["ids_f"], to=TensorProto.FLOAT),
        helper.make_node("Cast", ["attention_mask"], ["mask_f"], to=TensorProto.FLOAT),
        helper.make_node("Mul", ["ids_f", "mask_f"], ["masked"]),
        helper.make_node("ReduceSum", ["masked", "axes"], ["summed"], keepdims=1),
        helper.make_node("MatMul", ["summed", "W"], ["proj"]),
        helper.make_node("Add", ["proj", "bias"], ["logits"]),
    ]
    graph = helper.make_graph(
        nodes, "tiny_clf", [input_ids, attention], [logits], [weight, bias, axes]
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 9
    onnx.checker.check_model(model)
    onnx.save(model, str(path))


def _build_tokenizer(path: Path) -> None:
    vocab = {"[UNK]": 0, "[TARGET]": 1, "[/TARGET]": 2}
    for word in _VOCAB_WORDS:
        vocab[word] = len(vocab)
    tokenizer = Tokenizer(models.WordLevel(vocab=vocab, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.save(str(path))


def _export(directory: Path, *, labels=LABELS, with_config: bool = True) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    _build_model(directory / "model.onnx", num_labels=len(labels))
    _build_tokenizer(directory / "tokenizer.json")
    if with_config:
        (directory / "config.json").write_text(
            json.dumps({"id2label": {str(i): label for i, label in enumerate(labels)}}),
            encoding="utf-8",
        )
    return directory


def _request(candidates) -> NeuralRequest:
    return NeuralRequest(
        task=NeuralTask.WORD_SENSE,
        sentence_text="كتب الطالب الدرس",
        sentence_start=0,
        token_index=0,
        tokens=("كتب", "الطالب", "الدرس"),
        parts_of_speech=("verb", "noun", "noun"),
        candidates=tuple(candidates),
    )


def _candidate(label: str, pos: str) -> NeuralCandidate:
    return NeuralCandidate(label=label, value="كتب", lemma=label.split("|")[0], pos=pos)


@pytest.fixture
def model_dir(tmp_path: Path) -> Path:
    return _export(tmp_path / "onnx_model")


def test_onnx_backend_satisfies_protocol_and_is_lazy(model_dir: Path) -> None:
    backend = OnnxBackend(model_dir)
    assert isinstance(backend, NeuralBackend)
    assert backend.name.startswith("onnx/")
    assert backend.available is True
    # Constructing and probing availability must not build a session.
    assert backend._session is None


def test_onnx_backend_runs_real_inference_and_normalizes(model_dir: Path) -> None:
    backend = OnnxBackend(model_dir)
    scores = backend.score(
        _request([_candidate(LABELS[0], "verb"), _candidate(LABELS[1], "noun")])
    )
    assert backend._session is not None  # inference actually loaded the graph
    assert len(scores) == 2
    assert {score.label for score in scores} <= set(LABELS)
    assert all(0.0 <= score.probability <= 1.0 for score in scores)
    probabilities = [score.probability for score in scores]
    assert probabilities == sorted(probabilities, reverse=True)
    assert abs(sum(probabilities) - 1.0) < 1e-9


def test_onnx_backend_filters_to_requested_candidates(model_dir: Path) -> None:
    # Only one of the model's two labels is offered as a candidate.
    scores = OnnxBackend(model_dir).score(_request([_candidate(LABELS[0], "verb")]))
    assert len(scores) == 1
    assert scores[0].label == LABELS[0]
    assert scores[0].probability == pytest.approx(1.0)


def test_onnx_backend_supports_explicit_labels_without_config(tmp_path: Path) -> None:
    directory = _export(tmp_path / "no_config", with_config=False)
    backend = OnnxBackend(directory, labels=LABELS)
    assert backend.available is True
    scores = backend.score(
        _request([_candidate(LABELS[0], "verb"), _candidate(LABELS[1], "noun")])
    )
    assert abs(sum(score.probability for score in scores) - 1.0) < 1e-9


def test_onnx_backend_is_unavailable_when_pieces_are_missing(tmp_path: Path) -> None:
    assert OnnxBackend(tmp_path / "missing" / "model.onnx").available is False
    # Model present but no tokenizer/config → still not runnable.
    lonely = tmp_path / "lonely"
    lonely.mkdir()
    _build_model(lonely / "model.onnx", num_labels=2)
    assert OnnxBackend(lonely).available is False


def test_onnx_backend_validates_configuration(model_dir: Path) -> None:
    with pytest.raises(ValueError):
        OnnxBackend("")
    with pytest.raises(ValueError):
        OnnxBackend("   ")
    with pytest.raises(ValueError):
        OnnxBackend(model_dir, max_length=8)
    with pytest.raises(ValueError):
        OnnxBackend(model_dir, labels=[])


def test_onnx_backend_returns_nothing_without_candidates(model_dir: Path) -> None:
    assert OnnxBackend(model_dir).score(_request([])) == ()


def test_unavailable_onnx_backend_keeps_gateway_a_noop() -> None:
    deterministic = default_syntax_engine().parse("كتب الطالب الدرس")
    engine = HybridNeuralEngine(
        default_analyzer(),
        default_syntax_engine(),
        OnnxBackend("/no/such/model.onnx"),
    )
    assert engine.available is False
    report = engine.report("كتب الطالب الدرس", parsed=deterministic)
    assert report.decisions == ()
    assert report.suggestions == ()
    assert report.refined_parse.text == deterministic.text
    # The deterministic reading is untouched when the neural layer is inert.
    assert report.refined_parse.sentences[0].tokens[0].pos == "noun"


def test_available_onnx_backend_is_wired_into_the_gateway(model_dir: Path) -> None:
    engine = HybridNeuralEngine(default_analyzer(), default_syntax_engine(), OnnxBackend(model_dir))
    assert engine.available is True
    report = engine.report("كتب الطالب الدرس")
    assert isinstance(report, NeuralReport)
    assert report.backend.startswith("onnx/")
    # The ambiguous verb/noun token was routed through the ONNX scorer.
    assert report.triggered_tokens >= 1


def test_onnx_backend_from_env(model_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DHAD_NEURAL_ONNX_MODEL", raising=False)
    assert onnx_backend_from_env() is None
    monkeypatch.setenv("DHAD_NEURAL_ONNX_MODEL", str(model_dir))
    backend = onnx_backend_from_env()
    assert isinstance(backend, OnnxBackend)
    assert backend.available is True
