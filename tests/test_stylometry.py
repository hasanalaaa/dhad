"""V2 Phase 1 — deterministic stylometry and personal voice profiles."""

import json
import math

import pytest

from dhad import Dhad, Match, VoiceProfile, extract_fingerprint, personalize_matches
from dhad.stylometry import (
    FEATURES,
    PROFILE_SCHEMA_VERSION,
    FeatureStat,
    merge_profiles,
)

FORMAL = (
    "إن التخطيط المسبق يقلل من احتمالات الفشل في المشاريع الكبيرة، "
    "حيث تشير الدراسات إلى أن التحضير الجيد يرفع نسب النجاح. "
    "كما أن توثيق القرارات يسهل مراجعتها لاحقًا، "
    "غير أن الإفراط في التوثيق قد يبطئ سير العمل."
)
CASUAL = "شفت المباراة أمس؟ كانت رهيبة! جبنا هدفين، والحارس تألق بشكل خيالي!"


class TestFingerprint:
    def test_deterministic(self):
        assert extract_fingerprint(FORMAL) == extract_fingerprint(FORMAL)

    def test_closed_feature_vocabulary(self):
        fingerprint = extract_fingerprint(FORMAL)
        assert set(fingerprint.as_dict()) == set(FEATURES)

    def test_counts_and_basic_shape(self):
        fingerprint = extract_fingerprint(FORMAL)
        assert fingerprint.token_count > 20
        assert fingerprint.sentence_count >= 1
        values = fingerprint.as_dict()
        assert values["sentence_length_mean"] > 4
        assert 0.0 < values["type_token_ratio"] <= 1.0

    def test_question_and_exclamation_shares(self):
        values = extract_fingerprint(CASUAL).as_dict()
        assert values["question_share"] > 0.0
        assert values["exclamation_share"] > 0.0

    def test_arabic_comma_preference(self):
        arabic = extract_fingerprint("جاء زيد، ثم عمرو، ثم خالد.").as_dict()
        latin = extract_fingerprint("جاء زيد, ثم عمرو, ثم خالد.").as_dict()
        assert arabic["arabic_comma_share"] == 1.0
        assert latin["arabic_comma_share"] == 0.0

    def test_diacritics_density_detects_vocalized_text(self):
        plain = extract_fingerprint("ذهب الولد الى المدرسة").as_dict()
        vocalized = extract_fingerprint("ذَهَبَ الوَلَدُ إِلى المَدْرَسَةِ").as_dict()
        assert vocalized["diacritics_density"] > plain["diacritics_density"]

    def test_digit_style_preference(self):
        eastern = extract_fingerprint("عام ١٩٩٠ وعام ٢٠٢٠").as_dict()
        western = extract_fingerprint("عام 1990 وعام 2020").as_dict()
        assert eastern["arabic_digit_share"] == 1.0
        assert western["arabic_digit_share"] == 0.0

    def test_empty_text(self):
        fingerprint = extract_fingerprint("")
        assert fingerprint.token_count == 0
        assert fingerprint.sentence_count == 0


class TestFeatureStat:
    def test_welford_matches_direct_computation(self):
        samples = [3.0, 7.0, 7.0, 19.0]
        stat = FeatureStat()
        for value in samples:
            stat = stat.push(value)
        mean = sum(samples) / len(samples)
        variance = sum((value - mean) ** 2 for value in samples) / (len(samples) - 1)
        assert stat.count == 4
        assert math.isclose(stat.mean, mean)
        assert math.isclose(stat.variance, variance)

    def test_single_sample_has_zero_variance(self):
        assert FeatureStat().push(5.0).variance == 0.0


class TestVoiceProfile:
    def test_fit_and_reliability(self):
        empty = VoiceProfile()
        assert not empty.is_reliable
        profile = VoiceProfile.fit([FORMAL * 3, FORMAL * 3, FORMAL * 3])
        assert profile.sample_count == 3
        assert profile.token_count >= 300
        assert profile.is_reliable

    def test_update_is_immutable(self):
        base = VoiceProfile()
        updated = base.update(FORMAL)
        assert base.sample_count == 0
        assert updated.sample_count == 1
        assert updated is not base

    def test_blank_sample_is_ignored(self):
        profile = VoiceProfile().update("   \n\t ")
        assert profile.sample_count == 0

    def test_json_roundtrip(self):
        profile = VoiceProfile.fit([FORMAL, CASUAL, FORMAL * 2])
        restored = VoiceProfile.from_json(profile.to_json())
        assert restored == profile

    def test_json_rejects_wrong_version(self):
        payload = json.loads(VoiceProfile.fit([FORMAL]).to_json())
        payload["version"] = "999"
        with pytest.raises(ValueError):
            VoiceProfile.from_json(json.dumps(payload))

    def test_json_rejects_corrupt_stats(self):
        payload = json.loads(VoiceProfile.fit([FORMAL]).to_json())
        first = next(iter(payload["stats"]))
        payload["stats"][first]["count"] = -4
        with pytest.raises(ValueError):
            VoiceProfile.from_json(json.dumps(payload))

    def test_profile_stores_no_source_text(self):
        secret = "المعلومة السرية الفريدة تمامًا"
        payload = VoiceProfile.fit([f"{FORMAL} {secret}"]).to_json()
        assert secret not in payload
        assert "السرية" not in payload

    def test_merge_matches_sequential_learning(self):
        together = VoiceProfile.fit([FORMAL, CASUAL, FORMAL * 2, CASUAL * 2])
        merged = merge_profiles(
            VoiceProfile.fit([FORMAL, CASUAL]),
            VoiceProfile.fit([FORMAL * 2, CASUAL * 2]),
        )
        assert merged.sample_count == together.sample_count
        for (name_a, stat_a), (name_b, stat_b) in zip(merged.stats, together.stats):
            assert name_a == name_b
            assert math.isclose(stat_a.mean, stat_b.mean, abs_tol=1e-9)
            assert math.isclose(stat_a.m2, stat_b.m2, abs_tol=1e-6)


class TestComparison:
    def _profile(self):
        return VoiceProfile.fit([FORMAL * 3, FORMAL * 3, (FORMAL + " ") * 4])

    def test_own_style_scores_closer_than_foreign(self):
        profile = self._profile()
        own = profile.compare(FORMAL * 2)
        foreign = profile.compare(CASUAL * 4)
        assert own.drift_score < foreign.drift_score
        assert own.alignment > foreign.alignment

    def test_scores_are_bounded(self):
        report = self._profile().compare(CASUAL * 5)
        assert 0.0 <= report.drift_score < 1.0
        for deviation in report.deviations:
            assert 0.0 <= deviation.score < 1.0

    def test_deviations_carry_explanations(self):
        report = self._profile().compare(CASUAL * 4)
        top = report.top_deviations(3)
        assert len(top) == 3
        assert all(item.explanation for item in top)

    def test_short_sample_marked_unreliable(self):
        report = self._profile().compare("نص قصير")
        assert not report.reliable

    def test_empty_profile_produces_zero_drift(self):
        report = VoiceProfile().compare(FORMAL)
        assert report.drift_score == 0.0
        assert not report.reliable


class TestPersonalization:
    def _matches(self):
        return [
            Match("SPELL_X", "spelling", "خطأ إملائي", 0, 3, ["بديل"]),
            Match("STYLE_X", "style", "ملاحظة أسلوبية", 5, 4, severity="hint"),
            Match("GRAM_X", "grammar", "خطأ نحوي", 12, 3),
        ]

    def test_non_style_matches_untouched_and_none_dropped(self):
        profile = VoiceProfile.fit([FORMAL * 3, FORMAL * 3, FORMAL * 3])
        matches = self._matches()
        result = personalize_matches(matches, profile, text=FORMAL * 2)
        assert len(result) == len(matches)
        assert result[0] == matches[0]
        assert result[2] == matches[2]

    def test_style_matches_gain_voice_tag(self):
        profile = VoiceProfile.fit([FORMAL * 3, FORMAL * 3, FORMAL * 3])
        result = personalize_matches(self._matches(), profile, text=FORMAL * 2)
        style = result[1]
        assert any(tag.startswith("voice:") for tag in style.tags)

    def test_unreliable_profile_changes_nothing(self):
        profile = VoiceProfile.fit([FORMAL])
        matches = self._matches()
        assert personalize_matches(matches, profile, text=CASUAL) == matches

    def test_requires_report_or_text(self):
        with pytest.raises(ValueError):
            personalize_matches(self._matches(), VoiceProfile())


class TestDhadIntegration:
    def test_learn_voice_masks_pii(self):
        checker = Dhad()
        text = FORMAL + " راسلني على test@example.com أو 07701234567."
        profile = checker.learn_voice([text, text, text])
        assert profile.sample_count == 3
        payload = profile.to_json()
        assert "example.com" not in payload
        assert "07701234567" not in payload

    def test_voice_report_roundtrip(self):
        checker = Dhad()
        profile = checker.learn_voice([FORMAL * 3, FORMAL * 3, FORMAL * 3])
        report = checker.voice_report(FORMAL * 2, profile)
        assert report.reliable
        assert report.drift_score < 0.5

    def test_check_behavior_unchanged_by_stylometry_import(self):
        checker = Dhad()
        ids = {m.rule_id for m in checker.check("ذهبت الى المدرسه")}
        assert "HAMZA_ILA" in ids
        assert checker.correct("ذهبت الى المدرسه") == "ذهبت إلى المدرسة"

    def test_schema_version_exported(self):
        assert PROFILE_SCHEMA_VERSION == "1"
