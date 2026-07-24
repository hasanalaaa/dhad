"""Command line interface for analysis, APIs, benchmarks, and LSP serving."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import Dhad, DiacritizationMode, StyleProfile, Suppression, __version__
from .match import CATEGORIES

#: Rendered on bare invocation and at server start-up. Kept ≤ 78 columns and
#: written to stderr so piped/scripted stdout stays machine-parseable.
BANNER = rf"""
  ██████╗  ██╗  ██╗  █████╗  ██████╗
  ██╔══██╗ ██║  ██║ ██╔══██╗ ██╔══██╗      ض  DHAD ENGINE
  ██║  ██║ ███████║ ███████║ ██║  ██║      ─────────────────────────────
  ██║  ██║ ██╔══██║ ██╔══██║ ██║  ██║      deterministic-first · hybrid-neural
  ██████╔╝ ██║  ██║ ██║  ██║ ██████╔╝      arabic writing intelligence
  ╚═════╝  ╚═╝  ╚═╝ ╚═╝  ╚═╝ ╚═════╝
  ┌─ core ────────┬─ layers ────────────────────────────┬─ policy ──────────┐
  │ v{__version__:<12} │ rules·morph·syntax·style·neural·pii │ safe-autofix-only │
  └───────────────┴─────────────────────────────────────┴───────────────────┘
"""


def print_banner(stream=None) -> None:
    """Emit the CLI identity banner to ``stream`` (stderr by default)."""

    print(BANNER, file=stream if stream is not None else sys.stderr)


def _read_input(args) -> str:
    if args.text is not None:
        return args.text
    if args.file:
        return Path(args.file).read_text(encoding="utf-8")
    return sys.stdin.read()


def _suppression_from_args(args) -> Suppression:
    return Suppression(
        ignore_document=getattr(args, "ignore_document", False),
        rule_ids=frozenset(getattr(args, "ignore_rule", []) or []),
        words=frozenset(getattr(args, "ignore_word", []) or []),
        lines=frozenset(getattr(args, "ignore_line", []) or []),
    )


def _add_local_controls(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", action="append", default=[], help="فعّل ملف قواعد محدد")
    parser.add_argument("--ignore-rule", action="append", default=[], help="تجاهل معرّف قاعدة")
    parser.add_argument("--ignore-word", action="append", default=[], help="تجاهل كلمة محليًا")
    parser.add_argument(
        "--ignore-line", action="append", type=int, default=[], help="تجاهل سطر (1-based)"
    )
    parser.add_argument("--ignore-document", action="store_true", help="تجاهل المستند كاملًا")


def _print_matches(text: str, matches, as_json: bool) -> None:
    if as_json:
        payload = [
            {
                "rule": match.rule_id,
                "category": match.category,
                "severity": match.severity,
                "message": match.message,
                "offset": match.offset,
                "length": match.length,
                "text": text[match.offset : match.end],
                "replacements": match.replacements,
                "explanation": match.explanation,
                "confidence": match.confidence,
                "priority": match.priority,
                "tags": list(match.tags),
                "references": list(match.references),
                "profiles": list(match.profiles),
                "autofix": match.autofix,
            }
            for match in matches
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if not matches:
        print("✓ لا ملاحظات — النص سليم")
        return
    for match in matches:
        fragment = text[match.offset : match.end].replace("\n", " ")
        replacements = " | ".join(match.replacements) if match.replacements else "—"
        category = CATEGORIES[match.category]
        print(f"[{category}] «{fragment}» → {replacements}")
        print(f"   {match.message} (ثقة {match.confidence:.0%})")
        if match.explanation:
            print(f"   💡 {match.explanation}")
    print(f"\nالمجموع: {len(matches)} ملاحظة")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dhad", description="ضاد — المساعد الكتابي العربي")
    parser.add_argument("--version", action="version", version=f"dhad {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_check = sub.add_parser("check", help="افحص نصًا واعرض الملاحظات")
    p_check.add_argument("text", nargs="?", help="النص (أو استخدم --file أو stdin)")
    p_check.add_argument("--file", "-f", help="ملف نصي للفحص")
    p_check.add_argument("--json", action="store_true", help="إخراج JSON")
    p_check.add_argument(
        "--diacritics",
        choices=tuple(mode.value for mode in DiacritizationMode),
        help="أضف اقتراحات تشكيل صريحة وغير تلقائية",
    )
    _add_local_controls(p_check)

    p_fix = sub.add_parser("fix", help="طبّق التصحيحات تلقائيًا")
    p_fix.add_argument("text", nargs="?")
    p_fix.add_argument("--file", "-f")
    fix_modes = p_fix.add_mutually_exclusive_group()
    fix_modes.add_argument("--all", action="store_true", help="طبّق الاقتراحات غير الآمنة أيضًا")
    fix_modes.add_argument(
        "--dialects",
        action="store_true",
        help="طبّق تحويلات اللهجات إلى الفصحى فقط",
    )
    _add_local_controls(p_fix)

    sub.add_parser("rules", help="اعرض عدد القواعد المحملة")

    p_analyze = sub.add_parser("analyze", help="حلّل كلمة صرفيًا")
    p_analyze.add_argument("token", help="الكلمة العربية")
    p_analyze.add_argument("--json", action="store_true", help="إخراج JSON")
    p_analyze.add_argument("--min-confidence", type=float, default=0.0)

    p_parse = sub.add_parser("parse", help="حلّل جملة نحويًا واعرض الإعراب المرشح")
    p_parse.add_argument("text", nargs="?", help="النص (أو استخدم --file أو stdin)")
    p_parse.add_argument("--file", "-f", help="ملف نصي للتحليل")
    p_parse.add_argument("--json", action="store_true", help="إخراج JSON")
    p_parse.add_argument(
        "--msa",
        action="store_true",
        help="حوّل اللهجة إلى الفصحى صراحة قبل التحليل النحوي",
    )

    p_dialect = sub.add_parser("dialect", help="حدّد اللهجة واعرض تحويلًا مقترحًا إلى الفصحى")
    p_dialect.add_argument("text", nargs="?", help="النص (أو استخدم --file أو stdin)")
    p_dialect.add_argument("--file", "-f", help="ملف نصي للتحليل")
    p_dialect.add_argument("--json", action="store_true", help="إخراج JSON")

    p_style = sub.add_parser("style", help="حلّل الوضوح والأسلوب والنبرة")
    p_style.add_argument("text", nargs="?", help="النص (أو استخدم --file أو stdin)")
    p_style.add_argument("--file", "-f", help="ملف نصي للتحليل")
    p_style.add_argument("--json", action="store_true", help="إخراج JSON")
    p_style.add_argument(
        "--style-profile",
        choices=tuple(profile.value for profile in StyleProfile),
        default=StyleProfile.GENERAL.value,
        help="ملف الأسلوب المستهدف",
    )

    p_neural = sub.add_parser("neural", help="اعرض قرارات فك الالتباس والاقتراحات السياقية")
    p_neural.add_argument("text", nargs="?", help="النص (أو استخدم --file أو stdin)")
    p_neural.add_argument("--file", "-f", help="ملف نصي للتحليل")
    p_neural.add_argument("--json", action="store_true", help="إخراج JSON")

    p_diacritize = sub.add_parser("diacritize", help="شكّل النص صراحة اعتمادًا على الصرف والإعراب")
    p_diacritize.add_argument("text", nargs="?", help="النص (أو استخدم --file أو stdin)")
    p_diacritize.add_argument("--file", "-f", help="ملف نصي للتشكيل")
    p_diacritize.add_argument(
        "--mode",
        choices=tuple(mode.value for mode in DiacritizationMode),
        default=DiacritizationMode.FULL.value,
        help="full للتشكيل الكامل، endings للأواخر، core لبنية الكلمة",
    )
    p_diacritize.add_argument("--json", action="store_true", help="إخراج JSON قابل للتدقيق")

    p_semantics = sub.add_parser("semantics", help="حلّل اتساق المستند والدلالة المحافظة")
    p_semantics.add_argument("text", nargs="?", help="النص (أو استخدم --file أو stdin)")
    p_semantics.add_argument("--file", "-f", help="ملف نصي للتحليل")
    p_semantics.add_argument("--json", action="store_true", help="إخراج JSON")

    p_benchmark = sub.add_parser("benchmark", help="شغّل معيار Phase 2 المستقل")
    p_benchmark.add_argument("--split", choices=("train", "dev", "test"), default="test")
    p_benchmark.add_argument("--benchmark-dir", type=Path)
    p_benchmark.add_argument("--json", action="store_true", help="إخراج التقرير الكامل بصيغة JSON")
    p_benchmark.add_argument("--fail-under-f05", type=float)
    p_benchmark.add_argument(
        "--scope",
        choices=("all", "mechanical", "style", "dialect", "neural", "semantics", "diacritics"),
        default="all",
        help="نطاق الفئات: الكل أو الميكانيكي أو الأسلوب فقط",
    )

    p_serve = sub.add_parser("serve", help="شغّل خادم REST والواجهة المحلية")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8010)
    p_serve.add_argument("--no-web", action="store_true", help="شغّل API فقط دون ملفات الواجهة")
    p_serve.add_argument(
        "--no-sync", action="store_true", help="عطّل نقطة WebSocket للتحرير التعاوني"
    )

    sub.add_parser("lsp", help="شغّل خادم LSP 3.17 عبر stdin/stdout")

    p_desktop = sub.add_parser("desktop", help="شغّل ضاد كتطبيق سطح مكتب محلي")
    p_desktop.add_argument("--port", type=int, default=0)
    p_desktop.add_argument(
        "--backend",
        choices=("auto", "webview", "chromium", "browser", "server"),
        default="auto",
    )
    p_desktop.add_argument("--browser-binary")

    args = parser.parse_args(argv)
    if args.command in {"check", "fix"}:
        profiles = args.profile or ["default"]
        checker = Dhad(profiles=profiles)
        text = _read_input(args)
        suppression = _suppression_from_args(args)
        if args.command == "check":
            matches = checker.check(text, suppression=suppression, diacritics_mode=args.diacritics)
            _print_matches(text, matches, args.json)
            return 1 if any(match.severity == "error" for match in matches) else 0
        mode = "all" if args.all else "dialects" if args.dialects else "safe"
        print(checker.correct(text, mode=mode, suppression=suppression))
        return 0

    if args.command == "rules":
        checker = Dhad()
        print(f"القواعد المحملة: {checker.rule_count} قاعدة YAML + الفحوص المدمجة")
        return 0

    if args.command == "analyze":
        checker = Dhad()
        analyses = checker.analyze_word(args.token, min_confidence=args.min_confidence)
        payload = [
            {
                "token": item.token,
                "normalized": item.normalized,
                "stem": item.stem,
                "lemma": item.lemma,
                "root": item.root,
                "pattern": item.pattern,
                "pos": item.pos,
                "prefixes": [segment.surface for segment in item.prefixes],
                "suffixes": [segment.surface for segment in item.suffixes],
                "infixes": [segment.surface for segment in item.infixes],
                "features": dict(item.features),
                "confidence": item.confidence,
                "source": item.source,
            }
            for item in analyses
        ]
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif not payload:
            print("لا توجد قراءة صرفية موثوقة.")
        else:
            for index, item in enumerate(payload, start=1):
                print(
                    f"{index}. {item['lemma']} | الجذر={item['root'] or '—'} | "
                    f"الوزن={item['pattern'] or '—'} | الثقة={item['confidence']:.0%}"
                )
                print(
                    f"   السابقة={'+'.join(item['prefixes']) or '—'} | "
                    f"الجذع={item['stem']} | اللاحقة={'+'.join(item['suffixes']) or '—'}"
                )
        return 0

    if args.command == "parse":
        checker = Dhad()
        text = _read_input(args)
        parsed = checker.parse(text, dialect_to_msa=args.msa)
        payload = []
        for sentence in parsed.sentences:
            payload.append(
                {
                    "text": sentence.text,
                    "start": sentence.start,
                    "end": sentence.end,
                    "confidence": sentence.confidence,
                    "tokens": [
                        {
                            "text": token.text,
                            "start": token.start,
                            "end": token.end,
                            "pos": token.pos,
                            "lemma": token.analysis.lemma if token.analysis else None,
                            "root": token.analysis.root if token.analysis else None,
                            "features": dict(token.analysis.features) if token.analysis else {},
                            "confidence": token.confidence,
                        }
                        for token in sentence.tokens
                    ],
                    "relations": [
                        {
                            "type": relation.relation.value,
                            "head": relation.head_index,
                            "dependent": relation.dependent_index,
                            "governor": relation.governor,
                            "confidence": relation.confidence,
                            "explanation": relation.explanation,
                        }
                        for relation in sentence.relations
                    ],
                    "irab": [
                        {
                            "token": candidate.token_index,
                            "role": candidate.role,
                            "case_or_mood": candidate.case_or_mood,
                            "marker": candidate.marker,
                            "governor": candidate.governor,
                            "confidence": candidate.confidence,
                            "explanation": candidate.explanation,
                        }
                        for candidate in sentence.irab
                    ],
                }
            )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            for sentence_index, sentence in enumerate(payload, start=1):
                print(f"الجملة {sentence_index} — الثقة {sentence['confidence']:.0%}")
                for token, candidate in zip(sentence["tokens"], sentence["irab"]):
                    print(
                        f"  {token['text']}: {candidate['role']} | "
                        f"{candidate['case_or_mood']} | ثقة {candidate['confidence']:.0%}"
                    )
        return 0

    if args.command == "dialect":
        checker = Dhad()
        text = _read_input(args)
        report = checker.dialect_report(text)
        payload = {
            "primary": report.identification.primary.value,
            "confidence": report.identification.confidence,
            "scores": {label.value: score for label, score in report.identification.scores},
            "evidence": [
                {
                    "dialects": [label.value for label in item.dialects],
                    "text": item.text,
                    "offset": item.offset,
                    "length": item.length,
                    "weight": item.weight,
                    "rule": item.rule_id,
                }
                for item in report.identification.evidence
            ],
            "converted_text": report.converted_text,
            "conversions": [
                {
                    "rule": item.rule_id,
                    "dialects": [label.value for label in item.dialects],
                    "source": item.source,
                    "replacement": item.replacement,
                    "offset": item.offset,
                    "length": item.length,
                    "confidence": item.confidence,
                    "contextual": item.contextual,
                    "morphology_validated": item.morphology_validated,
                    "syntax_validated": item.syntax_validated,
                }
                for item in report.conversions
            ],
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(
                f"اللهجة المرجحة: {report.identification.primary.value} "
                f"(ثقة {report.identification.confidence:.0%})"
            )
            print(f"الفصحى المقترحة: {report.converted_text}")
            _print_matches(
                text, checker.dialects.check_text(text) if checker.dialects else [], False
            )
        return 0

    if args.command == "style":
        checker = Dhad(style_profile=args.style_profile)
        text = _read_input(args)
        report = checker.style_report(text)
        payload = {
            "profile": report.profile.value,
            "tone": {
                "primary": report.tone.primary.value,
                "confidence": report.tone.confidence,
                "scores": {label.value: score for label, score in report.tone.scores},
                "evidence": [
                    {
                        "tone": item.tone.value,
                        "text": item.text,
                        "offset": item.offset,
                        "length": item.length,
                        "weight": item.weight,
                        "reason": item.reason,
                    }
                    for item in report.tone.evidence
                ],
            },
            "readability": {
                "words": report.readability.words,
                "sentences": report.readability.sentences,
                "average_words_per_sentence": report.readability.average_words_per_sentence,
                "average_characters_per_word": report.readability.average_characters_per_word,
                "long_word_ratio": report.readability.long_word_ratio,
                "lexical_density": report.readability.lexical_density,
                "nominalization_ratio": report.readability.nominalization_ratio,
                "repeated_word_ratio": report.readability.repeated_word_ratio,
                "clarity_score": report.readability.clarity_score,
                "band": report.readability.band,
            },
            "matches": [
                {
                    "rule": match.rule_id,
                    "message": match.message,
                    "offset": match.offset,
                    "length": match.length,
                    "text": text[match.offset : match.end],
                    "replacements": match.replacements,
                    "confidence": match.confidence,
                    "autofix": match.autofix,
                    "tags": list(match.tags),
                }
                for match in report.matches
            ],
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"النبرة: {report.tone.primary.value} (ثقة {report.tone.confidence:.0%})")
            print(
                f"مؤشر الوضوح: {report.readability.clarity_score:.1f}/100 "
                f"— {report.readability.band}"
            )
            _print_matches(text, report.matches, False)
        return 0

    if args.command == "neural":
        checker = Dhad()
        text = _read_input(args)
        report = checker.neural_report(text)
        payload = {
            "backend": report.backend,
            "triggered_tokens": report.triggered_tokens,
            "skipped_high_confidence": report.skipped_high_confidence,
            "decisions": [
                {
                    "task": item.task.value,
                    "token": item.token,
                    "offset": item.offset,
                    "length": item.length,
                    "selected_label": item.selected_label,
                    "confidence": item.confidence,
                    "margin": item.margin,
                    "changed": item.changed,
                    "evidence": list(item.evidence),
                }
                for item in report.decisions
            ],
            "suggestions": [
                {
                    "rule": item.rule_id,
                    "category": item.category,
                    "offset": item.offset,
                    "length": item.length,
                    "text": text[item.offset : item.end],
                    "replacements": item.replacements,
                    "confidence": item.confidence,
                    "autofix": item.autofix,
                }
                for item in report.suggestions
            ],
            "refined_sentences": [
                {
                    "text": sentence.text,
                    "confidence": sentence.confidence,
                    "tokens": [
                        {
                            "text": token.text,
                            "pos": token.pos,
                            "lemma": token.analysis.lemma if token.analysis else None,
                            "root": token.analysis.root if token.analysis else None,
                            "confidence": token.confidence,
                        }
                        for token in sentence.tokens
                    ],
                }
                for sentence in report.refined_parse.sentences
            ],
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"المحرك: {report.backend}")
            print(f"مواضع الغموض المفحوصة: {report.triggered_tokens}")
            for item in report.decisions:
                print(
                    f"- {item.token}: {item.selected_label} "
                    f"(ثقة {item.confidence:.0%}, هامش {item.margin:.0%})"
                )
            _print_matches(text, report.suggestions, False)
        return 0

    if args.command == "diacritize":
        checker = Dhad()
        text = _read_input(args)
        result = checker.diacritize(text, mode=args.mode)
        if args.json:
            payload = {
                "mode": result.mode.value,
                "text": result.text,
                "confidence": result.confidence,
                "tokens": [
                    {
                        "source": item.source,
                        "output": item.output,
                        "offset": item.start,
                        "length": item.end - item.start,
                        "lemma": item.lemma,
                        "role": item.role,
                        "case_or_mood": item.case_or_mood,
                        "confidence": item.confidence,
                        "core_confidence": item.core_confidence,
                        "ending_confidence": item.ending_confidence,
                        "provenance": list(item.provenance),
                    }
                    for item in result.tokens
                ],
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(result.text)
        return 0

    if args.command == "semantics":
        checker = Dhad()
        text = _read_input(args)
        report = checker.semantic_report(text)
        if args.json:
            payload = {
                "numeral_style": report.numeral_style,
                "sentences_examined": report.sentences_examined,
                "choices": [
                    {
                        "group": item.group_id,
                        "preferred": item.preferred,
                        "first_offset": item.first_offset,
                        "occurrences": item.occurrences,
                    }
                    for item in report.choices
                ],
                "matches": [
                    {
                        "rule": item.rule_id,
                        "category": item.category,
                        "offset": item.offset,
                        "length": item.length,
                        "text": text[item.offset : item.end],
                        "replacements": item.replacements,
                        "confidence": item.confidence,
                        "autofix": item.autofix,
                        "message": item.message,
                    }
                    for item in report.matches
                ],
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            _print_matches(text, report.matches, False)
        return 0

    if args.command == "benchmark":
        from .evaluation import BENCHMARK_SCOPES, DEFAULT_BENCHMARK_DIR, evaluate_split

        benchmark_dir = args.benchmark_dir or DEFAULT_BENCHMARK_DIR
        report = evaluate_split(
            Dhad(),
            args.split,
            benchmark_dir=benchmark_dir,
            categories=BENCHMARK_SCOPES[args.scope],
        )
        payload = report.to_dict()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"المعيار: {report.dataset} / {report.split} / {args.scope}")
            print(f"الحالات: {report.cases} | الكلمات: {report.words}")
            print(
                f"Span P={report.span.precision:.3f} R={report.span.recall:.3f} "
                f"F0.5={report.span.fbeta(0.5):.3f}"
            )
            print(f"FP/1000 كلمة: {report.false_positives_per_1000_words:.3f}")
            print(f"MRR للاقتراحات: {report.mean_reciprocal_rank:.3f}")
        if args.fail_under_f05 is not None and report.span.fbeta(0.5) < args.fail_under_f05:
            return 1
        return 0

    if args.command == "serve":
        import uvicorn
        from .server import create_app

        print_banner()
        uvicorn.run(
            create_app(serve_web=not args.no_web, serve_sync=not args.no_sync),
            host=args.host,
            port=args.port,
        )
        return 0

    if args.command == "desktop":
        from .desktop import main as desktop_main

        forwarded = ["--port", str(args.port), "--backend", args.backend]
        if args.browser_binary:
            forwarded.extend(["--browser-binary", args.browser_binary])
        return desktop_main(forwarded)

    if args.command == "lsp":
        from .lsp.server import serve_stdio

        return serve_stdio()

    print_banner()
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
