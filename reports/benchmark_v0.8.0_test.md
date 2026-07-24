# Dhad Benchmark Report

- Dhad version: `0.8.0`
- Dataset: `dhad-controlled-gold-v1`
- Split: `test`
- Cases: **750**
- Words: **13226**

## Metrics

| Metric | v0.7.0 | v0.8.0 | Delta |
|---|---:|---:|---:|
| Span precision | 0.8497 | 0.8602 | +0.0105 |
| Span recall | 0.8764 | 0.9539 | +0.0775 |
| Span F0.5 | 0.8549 | 0.8775 | +0.0225 |
| FP/1000 Arabic words | 6.3511 | 6.3511 | +0.0000 |
| Sentence exact accuracy | 0.8253 | 0.8627 | +0.0373 |

## Interpretation

The all-category gain comes from Phase-6 dialect coverage. False positives did not increase. The corpus is controlled and template-generated; it is a regression instrument, not a native-speaker accuracy claim.
