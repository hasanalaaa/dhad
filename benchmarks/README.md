# Dhad benchmarks

- `seed_v0.jsonl`: tiny Phase-0 smoke regression suite.
- `datasets.yml`: machine-readable dataset/license registry.
- Packaged Phase-2 corpus: `src/dhad/data/benchmarks/gold_v1/`.
- Build reproducibly: `python tools/build_phase2_corpus.py`.
- Evaluate test split: `dhad benchmark --split test`.
- Persist reports: `python tools/evaluate_benchmark.py --split test --output-json reports/report.json --output-markdown reports/report.md`.

`dhad-controlled-gold-v1` is a controlled template corpus, not a natural human-reviewed corpus. Its results are for internal regression and architectural decisions, not broad public accuracy claims.
