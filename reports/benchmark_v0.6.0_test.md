# Dhad Benchmark Report

- Dhad version: `0.6.0`
- Dataset: `dhad-controlled-gold-v1`
- Split: `test`
- Cases: **750**
- Words: **13226**

## Global metrics

| Metric | Value |
|---|---:|
| Span precision | 0.8497 |
| Span recall | 0.8764 |
| Span F0.5 | 0.8549 |
| Correction precision | 0.8497 |
| Correction recall | 0.8764 |
| Correction F0.5 | 0.8549 |
| Sentence exact accuracy | 0.8253 |
| Mean reciprocal rank | 1.0000 |
| False positives / 1000 words | 6.3511 |

## Delta from v0.5.0

| Metric | v0.5.0 | v0.6.0 | Delta |
|---|---:|---:|---:|
| Precision | 0.8400 | 0.8497 | +0.0097 |
| Recall | 0.8137 | 0.8764 | +0.0627 |
| F0.5 | 0.8346 | 0.8549 | +0.0203 |
| FP/1000 | 6.3511 | 6.3511 | +0.0000 |

## Domain slices

| Domain | Cases | Span P | Span R | F0.5 | FP/1000 |
|---|---:|---:|---:|---:|---:|
| academic | 167 | 1.0000 | 0.9643 | 0.9926 | 0.0000 |
| administrative | 83 | 1.0000 | 1.0000 | 1.0000 | 0.0000 |
| dialect | 167 | 0.8557 | 0.7981 | 0.8435 | 9.2777 |
| educational | 166 | 0.7255 | 0.8916 | 0.7536 | 9.4851 |
| journalism | 84 | 1.0000 | 0.9524 | 0.9901 | 0.0000 |
| social | 83 | 0.7255 | 0.8916 | 0.7536 | 20.1294 |

## Interpretation boundary

This is the controlled Phase-2 benchmark. It is independent from YAML rule examples, but it is template-generated and must not be advertised as real-world human-corpus accuracy.
