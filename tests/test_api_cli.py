import json
import subprocess
import sys

import pytest

from dhad import Dhad


class TestDhadAPI:
    def test_check_finds_multiple_categories(self):
        checker = Dhad()
        text = "انا ذهبت الى المدرسه قبل ثلاثة سنوات, وكان اليوم جميلا"
        ids = {m.rule_id for m in checker.check(text)}
        assert "HAMZA_ANA" in ids
        assert "HAMZA_ILA" in ids
        assert "TAA_MADRASA" in ids
        assert "AGREEMENT_NUM_FEM_NOUN" in ids
        assert "PUNCT_LATIN_COMMA" in ids

    def test_correct_full_pipeline(self):
        checker = Dhad()
        assert checker.correct("ذهبت الى المدرسه") == "ذهبت إلى المدرسة"
        assert checker.correct("سأزورك انشاء الله") == "سأزورك إن شاء الله"
        assert checker.correct("عملت ثلاثة سنوات") == "عملت ثلاث سنوات"

    def test_safe_correction_does_not_rewrite_dialect_or_style(self):
        checker = Dhad()
        assert checker.correct("اكو كلام كلام") == "اكو كلام كلام"
        assert checker.correct("اكو كلام كلام", mode="all") == "يوجد كلام"

    def test_invalid_correction_mode(self):
        checker = Dhad()
        with pytest.raises(ValueError):
            checker.correct("نص", mode="unknown")

    def test_clean_text_untouched(self):
        checker = Dhad()
        clean = "ذهبتُ إلى المدرسة صباحًا والتقيت بالأستاذ"
        assert checker.correct(clean) == clean
        assert not [m for m in checker.check(clean) if m.severity == "error"]

    def test_category_filter(self):
        checker = Dhad(enabled_categories={"spelling"})
        text = "ذهبت الى السوق, واشتريت خبزًا"
        cats = {m.category for m in checker.check(text)}
        assert cats == {"spelling"}

    def test_no_overlapping_matches(self):
        checker = Dhad()
        ms = checker.check("انا انا ذهبت الى الى المدرسه")
        for a, b in zip(ms, ms[1:]):
            assert a.end <= b.offset


def run_cli(*args, stdin=None):
    return subprocess.run(
        [sys.executable, "-m", "dhad.cli", *args],
        capture_output=True,
        text=True,
        input=stdin,
    )


class TestCLI:
    def test_check_text(self):
        r = run_cli("check", "ذهبت الى المدرسه")
        assert r.returncode == 1  # errors found → exit 1 (CI-friendly)
        assert "إلى" in r.stdout

    def test_check_clean_exit_zero(self):
        r = run_cli("check", "ذهبت إلى المدرسة")
        assert r.returncode == 0
        assert "سليم" in r.stdout

    def test_check_json(self):
        r = run_cli("check", "--json", "ذهبت الى السوق")
        data = json.loads(r.stdout)
        assert data[0]["rule"] == "HAMZA_ILA"
        assert data[0]["replacements"] == ["إلى"]

    def test_fix_stdin(self):
        r = run_cli("fix", stdin="ذهبت الى المدرسه")
        assert r.stdout.strip() == "ذهبت إلى المدرسة"

    def test_fix_all_opt_in(self):
        safe = run_cli("fix", "اكو وقت")
        assert safe.stdout.strip() == "اكو وقت"
        broad = run_cli("fix", "--all", "اكو وقت")
        assert broad.stdout.strip() == "يوجد وقت"

    def test_rules_command(self):
        r = run_cli("rules")
        assert r.returncode == 0 and "قاعدة" in r.stdout
