"""Hybrid contextual intelligence for Dhad."""

from .backend import NeuralBackend
from .distillation import (
    CandidateRule,
    DistillationPipeline,
    DistillationReport,
    extract_replacement,
)
from .gateway import HybridNeuralEngine, default_neural_engine
from .onnx_backend import OnnxBackend, onnx_backend_from_env
from .statistical import StatisticalContextBackend, default_statistical_backend
from .student_dataset import StudentExample, build_student_example, write_student_jsonl
from .transformer import TransformerBackend
from .types import (
    CandidateScore,
    NeuralCandidate,
    NeuralDecision,
    NeuralReport,
    NeuralRequest,
    NeuralTask,
)

__all__ = [
    "CandidateRule",
    "CandidateScore",
    "DistillationPipeline",
    "DistillationReport",
    "extract_replacement",
    "HybridNeuralEngine",
    "NeuralBackend",
    "NeuralCandidate",
    "NeuralDecision",
    "NeuralReport",
    "NeuralRequest",
    "NeuralTask",
    "OnnxBackend",
    "StatisticalContextBackend",
    "StudentExample",
    "TransformerBackend",
    "default_neural_engine",
    "default_statistical_backend",
    "build_student_example",
    "onnx_backend_from_env",
    "write_student_jsonl",
]
