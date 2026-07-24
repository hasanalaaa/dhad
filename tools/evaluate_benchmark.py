"""Run the independent Phase-2 benchmark and optionally persist reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dhad import Dhad, __version__  # noqa: E402
from dhad.evaluation import DEFAULT_BENCHMARK_DIR, evaluate_split  # noqa: E402


def render_markdown(payload: dict[str, Any]) -> str:
    span = payload["span"]
    correction = payload["correction"]
    lines = [
        "# Dhad Benchmark Report",
        "",
        f"- Dhad version: `{payload['dhad_version']}`",
        f"- Dataset: `{payload['dataset']}`",
        f"- Split: `{payload['split']}`",
        f"- Cases: **{payload['cases']}**",
        f"- Words: **{payload['words']}**",
        "",
        "## Global metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Span precision | {span['precision']:.4f} |",
        f"| Span recall | {span['recall']:.4f} |",
        f"| Span F0.5 | {span['f0.5']:.4f} |",
        f"| Correction precision | {correction['precision']:.4f} |",
        f"| Correction recall | {correction['recall']:.4f} |",
        f"| Correction F0.5 | {correction['f0.5']:.4f} |",
        f"| Sentence exact accuracy | {payload['sentence_exact_accuracy']:.4f} |",
        f"| Mean reciprocal rank | {payload['mean_reciprocal_rank']:.4f} |",
        f"| False positives / 1000 words | {payload['false_positives_per_1000_words']:.4f} |",
        "",
        "## Domain slices",
        "",
        "| Domain | Cases | Span P | Span R | F0.5 | FP/1000 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, metrics in payload["slices"]["domain"].items():
        domain_span = metrics["span"]
        lines.append(
            f"| {name} | {metrics['cases']} | {domain_span['precision']:.4f} | "
            f"{domain_span['recall']:.4f} | {domain_span['f0.5']:.4f} | "
            f"{metrics['false_positives_per_1000_words']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "This is the controlled Phase-2 benchmark. It is independent from YAML rule examples, "
            "but it is template-generated and must not be advertised as real-world human-corpus accuracy.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("train", "dev", "test"), default="test")
    parser.add_argument("--benchmark-dir", type=Path, default=DEFAULT_BENCHMARK_DIR)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-markdown", type=Path)
    parser.add_argument("--include-failures", action="store_true")
    parser.add_argument("--fail-under-f05", type=float)
    args = parser.parse_args(argv)

    report = evaluate_split(
        Dhad(),
        args.split,
        benchmark_dir=args.benchmark_dir,
        include_failures=args.include_failures,
    )
    payload = {"dhad_version": __version__, **report.to_dict()}
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(rendered + "\n", encoding="utf-8")
    if args.output_markdown:
        args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
        args.output_markdown.write_text(render_markdown(payload), encoding="utf-8")
    if args.fail_under_f05 is not None and report.span.fbeta(0.5) < args.fail_under_f05:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
