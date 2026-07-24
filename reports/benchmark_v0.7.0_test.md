# Dhad Benchmark Report

- Dhad version: `0.7.0`
- Dataset: `dhad-controlled-gold-v1`
- Split: `test`
- Cases: **750**
- Words: **13226**

## Global metrics

| Metric | v0.6.0 | v0.7.0 | Delta |
|---|---:|---:|---:|
| Span precision | 0.8497 | 0.8497 | +0.0000 |
| Span recall | 0.8764 | 0.8764 | +0.0000 |
| Span F0.5 | 0.8549 | 0.8549 | +0.0000 |
| FP/1000 Arabic words | 6.3511 | 6.3511 | +0.0000 |
| Sentence exact accuracy | 0.8253 | 0.8253 | +0.0000 |

## Phase-5 isolation guarantee

The same mechanical-scope report is produced with Phase 5 enabled or disabled. Subjective Phase-5 matches are categorized as `style`, carry `requires-approval`, and never safe-autofix. This controlled template corpus is a regression instrument, not a human style-utility evaluation.
