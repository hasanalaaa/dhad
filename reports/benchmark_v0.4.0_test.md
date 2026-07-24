# Dhad Benchmark Report

- Dhad version: `0.4.0`
- Dataset: `dhad-controlled-gold-v1`
- Split: `test`
- Cases: **750**
- Words: **13226**

## Global metrics

| Metric | Value |
|---|---:|
| Span precision | 0.8303 |
| Span recall | 0.7583 |
| Span F0.5 | 0.8148 |
| Correction precision | 0.8303 |
| Correction recall | 0.7583 |
| Correction F0.5 | 0.8148 |
| Sentence exact accuracy | 0.7547 |
| Mean reciprocal rank | 1.0000 |
| False positives / 1000 words | 6.3511 |

## Domain slices

| Domain | Cases | Span P | Span R | F0.5 | FP/1000 |
|---|---:|---:|---:|---:|---:|
| academic | 167 | 1.0000 | 0.7738 | 0.9448 | 0.0000 |
| administrative | 83 | 1.0000 | 1.0000 | 1.0000 | 0.0000 |
| dialect | 167 | 0.8557 | 0.7981 | 0.8435 | 9.2777 |
| educational | 166 | 0.6744 | 0.6988 | 0.6792 | 9.4851 |
| journalism | 84 | 1.0000 | 0.7619 | 0.9412 | 0.0000 |
| social | 83 | 0.6744 | 0.6988 | 0.6792 | 20.1294 |

## Interpretation boundary

This is the controlled Phase-2 benchmark. It is independent from YAML rule examples, but it is template-generated and must not be advertised as real-world human-corpus accuracy.
