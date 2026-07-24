# Dhad Benchmark Report

- Dhad version: `0.9.0`
- Dataset: `dhad-controlled-gold-v1`
- Split: `test`
- Cases: **750**
- Words: **13226**

## Metrics

| Metric | v0.8.0 | v0.9.0 | Delta |
|---|---:|---:|---:|
| Span precision | 0.8602 | 0.8602 | +0.0000 |
| Span recall | 0.9539 | 0.9539 | +0.0000 |
| Span F0.5 | 0.8775 | 0.8775 | +0.0000 |
| FP/1000 Arabic words | 6.3511 | 6.3511 | +0.0000 |
| Sentence exact accuracy | 0.8627 | 0.8627 | +0.0000 |

## Interpretation

Phase 7 preserves the official controlled benchmark exactly. The hybrid layer only re-ranks low-confidence morphology candidates and emits a neural suggestion only under an extreme contextual threshold; it introduces no additional prediction in this test split.
