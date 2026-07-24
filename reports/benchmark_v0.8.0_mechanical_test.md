# Dhad Mechanical-Scope Benchmark Report

- Dhad version: `0.8.0`
- Dataset: `dhad-controlled-gold-v1`
- Split: `test`
- Cases: **750**
- Words: **13226**

## Metrics

| Metric | v0.7.0 | v0.8.0 | Delta |
|---|---:|---:|---:|
| Span precision | 0.7551 | 0.7551 | +0.0000 |
| Span recall | 0.9120 | 0.9120 | +0.0000 |
| Span F0.5 | 0.7820 | 0.7820 | +0.0000 |
| FP/1000 Arabic words | 6.3511 | 6.3511 | +0.0000 |
| Sentence exact accuracy | 0.8627 | 0.8627 | +0.0000 |

## Interpretation

All spelling, grammar, and punctuation metrics are exactly unchanged from v0.7.0. Dialect suggestions remain a separate category and do not inflate mechanical false positives.
