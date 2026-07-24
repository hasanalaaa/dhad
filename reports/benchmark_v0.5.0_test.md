# Dhad Benchmark Report

- Dhad version: `0.5.0`
- Dataset: `dhad-controlled-gold-v1`
- Split: `test`
- Cases: **750**
- Words: **13226**

## Global metrics

| Metric | Value |
|---|---:|
| Span precision | 0.8400 |
| Span recall | 0.8137 |
| Span F0.5 | 0.8346 |
| Correction precision | 0.8400 |
| Correction recall | 0.8137 |
| Correction F0.5 | 0.8346 |
| Sentence exact accuracy | 0.7880 |
| Mean reciprocal rank | 1.0000 |
| False positives / 1000 words | 6.3511 |

## Domain slices

| Domain | Cases | Span P | Span R | F0.5 | FP/1000 |
|---|---:|---:|---:|---:|---:|
| academic | 167 | 1.0000 | 0.8690 | 0.9707 | 0.0000 |
| administrative | 83 | 1.0000 | 1.0000 | 1.0000 | 0.0000 |
| dialect | 167 | 0.8557 | 0.7981 | 0.8435 | 9.2777 |
| educational | 166 | 0.6989 | 0.7831 | 0.7143 | 9.4851 |
| journalism | 84 | 1.0000 | 0.8571 | 0.9677 | 0.0000 |
| social | 83 | 0.6989 | 0.7831 | 0.7143 | 20.1294 |

## Interpretation boundary

This is the controlled Phase-2 benchmark. It is independent from YAML rule examples, but it is template-generated and must not be advertised as real-world human-corpus accuracy.
