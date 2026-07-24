# Dhad browser neural pipeline

The browser layer is a private, candidate-constrained ranker. It is not a text
generator. Rust remains the authority that creates morphological candidates;
the neural model may select one candidate or abstain.

## Runtime contract

1. `app.js` obtains sentence parses and alternatives from `dhad-core-rs`.
2. `collectMorphologyRequests()` freezes source-anchored candidate groups.
3. `NeuralInferenceClient` sends up to 64 groups per message to a module Worker.
4. The Worker tokenizes the context and candidate descriptions, builds one
   contiguous batch, and runs ONNX Runtime Web once for the batch.
5. ONNX Runtime prefers the WebGPU execution provider and permits WASM SIMD as
   the fallback provider. Neural work never executes on the UI thread.
6. Mean-pooled embeddings produce cosine logits. Stable softmax, temperature,
   confidence, and margin gates run inside the Worker.
7. Both Worker runtime and UI client verify the selected index and candidate
   identity. A missing, forged, or mismatched identity is rejected.

The production manifest pins the upstream revision, exact byte count, and
SHA-256 of the INT8 model and local WordPiece vocabulary. Model downloads use
anonymous CORS requests; document text is never transmitted.

## Teacher/student data

`dhad.neural.student_dataset` converts scores from a higher-capacity teacher
into the `dhad-candidate-distillation-v1` JSONL contract. Teacher labels must
equal the complete Rust candidate set. Records use deterministic 80/10/10
splits and preserve low-confidence examples as abstentions. This supports
groupwise distillation and calibration without introducing an open vocabulary.

## Reproducibility

```sh
cd web_demo
npm install
npm run vendor:ort
npm test
cd ..
venv/bin/python tools/generate_browser_student_fixture.py
venv/bin/pytest -q tests/test_student_distillation.py
```

The tiny fixture is a genuine UINT8 activation-quantized ONNX graph used only
to prove browser Worker execution. It is generated and checked by ONNX; it is
not a mock and is never selected by the production application.
