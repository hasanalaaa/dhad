"""Generate the tiny activation-quantized ONNX model used by browser integration tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper


REPOSITORY = Path(__file__).resolve().parents[1]
OUTPUT = REPOSITORY / "web_demo" / "neural" / "fixtures"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_model(path: Path) -> None:
    input_ids = helper.make_tensor_value_info(
        "input_ids", TensorProto.INT64, ["batch", "sequence"]
    )
    attention_mask = helper.make_tensor_value_info(
        "attention_mask", TensorProto.INT64, ["batch", "sequence"]
    )
    output = helper.make_tensor_value_info(
        "last_hidden_state", TensorProto.FLOAT, ["batch", "sequence", 1]
    )
    nodes = [
        helper.make_node("Cast", ["input_ids"], ["ids_float"], to=TensorProto.FLOAT),
        helper.make_node("QuantizeLinear", ["ids_float", "scale", "zero"], ["ids_quantized"]),
        helper.make_node(
            "DequantizeLinear", ["ids_quantized", "scale", "zero"], ["ids_dequantized"]
        ),
        helper.make_node("Cast", ["attention_mask"], ["mask_float"], to=TensorProto.FLOAT),
        helper.make_node("Mul", ["ids_dequantized", "mask_float"], ["masked"]),
        helper.make_node("Unsqueeze", ["masked", "axes"], ["last_hidden_state"]),
    ]
    initializers = [
        numpy_helper.from_array(np.array(0.25, dtype=np.float32), name="scale"),
        numpy_helper.from_array(np.array(0, dtype=np.uint8), name="zero"),
        numpy_helper.from_array(np.array([2], dtype=np.int64), name="axes"),
    ]
    graph = helper.make_graph(
        nodes,
        "dhad-browser-student-fixture",
        [input_ids, attention_mask],
        [output],
        initializer=initializers,
    )
    model = helper.make_model(
        graph,
        producer_name="dhad-phase3",
        opset_imports=[helper.make_opsetid("", 13)],
    )
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save_model(model, path)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    model_path = OUTPUT / "student-fixture.onnx"
    vocab_path = OUTPUT / "vocab.txt"
    manifest_path = OUTPUT / "manifest.json"
    build_model(model_path)
    vocab_path.write_text(
        "\n".join(
            [
                "[PAD]",
                "[UNK]",
                "[CLS]",
                "[SEP]",
                "كتب",
                "الطالب",
                "الدرس",
                "كتاب",
                "فعل",
                "اسم",
                "الجذر",
                "؛",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "format": 1,
        "id": "dhad-browser-student-fixture",
        "contract": "dhad-context-embedding-ranker-v1",
        "model": {
            "url": "student-fixture.onnx",
            "sha256": sha256(model_path),
            "expectedBytes": model_path.stat().st_size,
            "quantization": "uint8",
        },
        "tokenizer": {
            "type": "wordpiece",
            "url": "vocab.txt",
            "sha256": sha256(vocab_path),
            "lowercase": False,
        },
        "inputs": {"inputIds": "input_ids", "attentionMask": "attention_mask"},
        "output": {"name": "last_hidden_state"},
        "maxLength": 16,
        "thresholds": {"confidence": 0.999, "margin": 0.99, "temperature": 0.02},
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Generated {model_path.relative_to(REPOSITORY)} ({model_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
