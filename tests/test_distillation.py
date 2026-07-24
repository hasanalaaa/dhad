"""V2 Phase 5 groundwork — the neural → YAML distillation pipeline."""

from pathlib import Path

import pytest
import yaml

from dhad.neural.distillation import (
    DistillationPipeline,
    extract_replacement,
)
from dhad.rules import RuleEngine, _compile


class TestExtraction:
    def test_single_word_replacement(self):
        assert extract_replacement("ذهبت الى البيت", "ذهبت إلى البيت") == ("الى", "إلى")

    def test_multiword_contiguous_replacement(self):
        got = extract_replacement("سأزورك انشاء الله غدا", "سأزورك إن شاء الله غدا")
        assert got == ("انشاء", "إن شاء")

    def test_identical_and_empty_are_rejected(self):
        assert extract_replacement("نص", "نص") is None
        assert extract_replacement("", "نص") is None

    def test_pure_insertion_is_rejected(self):
        assert extract_replacement("ذهبت البيت", "ذهبت الى البيت") is None

    def test_long_rewrites_are_rejected(self):
        original = "هذه جملة طويلة سيعاد صياغتها بالكامل الآن"
        rewritten = "أعيدت صياغة هذه العبارة القصيرة كليا هنا فعلا"
        assert extract_replacement(original, rewritten) is None

    def test_diacritics_only_difference_is_rejected(self):
        assert extract_replacement("ذهب الولد", "ذَهَبَ الولد") is None


class TestPipeline:
    def _fed_pipeline(self, times=3):
        pipeline = DistillationPipeline(min_support=3)
        for _ in range(times):
            assert pipeline.record("ذهبت الى البيت", "ذهبت إلى البيت")
        return pipeline

    def test_support_threshold_gates_emission(self):
        pipeline = self._fed_pipeline(times=2)
        report = pipeline.harvest()
        assert report.accepted == ()
        assert report.rejected_below_support == 1

    def test_candidate_emerges_with_support_and_verification(self):
        report = self._fed_pipeline(times=3).harvest()
        assert len(report.accepted) == 1
        candidate = report.accepted[0]
        assert candidate.pattern == "الى"
        assert candidate.suggestion == "إلى"
        assert candidate.support == 3
        assert candidate.rule_id.startswith("DISTILLED_")

    def test_emitted_rule_compiles_fires_and_stays_quarantined(self, tmp_path):
        report = self._fed_pipeline().harvest(output_dir=tmp_path / "drafts")
        assert len(report.written_files) == 1
        path = Path(report.written_files[0])
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(payload, list) and len(payload) == 1
        data = payload[0]
        assert data["autofix"] is False
        assert "quarantine" in data["tags"]
        rule = _compile(data, source=str(path))
        assert rule.apply("ذهبت الى البيت")
        assert not rule.apply("ذهبت إلى البيت")

    def test_drafts_stay_outside_engine_glob(self, tmp_path):
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        (rules_dir / "live.yaml").write_text(
            yaml.safe_dump(
                [
                    {
                        "id": "LIVE_RULE",
                        "category": "spelling",
                        "pattern": "خطاء",
                        "suggestion": "خطأ",
                        "message": "م",
                        "examples": {"bad": "هذا خطاء", "good": "هذا خطأ"},
                    }
                ],
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        report = self._fed_pipeline().harvest(output_dir=rules_dir / "drafts")
        assert report.written_files
        engine = RuleEngine(rules_dir)
        loaded_ids = {rule.id for rule in engine.rules}
        assert "LIVE_RULE" in loaded_ids
        assert not any(rule_id.startswith("DISTILLED_") for rule_id in loaded_ids)

    def test_ambiguous_records_are_counted(self):
        pipeline = DistillationPipeline(min_support=1)
        assert not pipeline.record("نص", "نص")
        report = pipeline.harvest()
        assert report.rejected_ambiguous == 1

    def test_state_roundtrip(self):
        pipeline = self._fed_pipeline(times=2)
        restored = DistillationPipeline.from_json(pipeline.to_json())
        assert restored.record("ذهبت الى البيت", "ذهبت إلى البيت")
        report = restored.harvest()
        assert len(report.accepted) == 1

    def test_invalid_min_support(self):
        with pytest.raises(ValueError):
            DistillationPipeline(min_support=0)
