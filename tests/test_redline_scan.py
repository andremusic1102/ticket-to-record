"""The guard has to be tested, or it is decoration.

Note how the offending strings are assembled at runtime rather than written out.
A test that hard-codes a credential-shaped literal would be caught by the very
scanner it is testing, on the commit that adds it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import redline_scan


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


class TestCredentials:
    def test_detects_google_key(self, tmp_path: Path) -> None:
        key = "AIza" + "B" * 35
        path = _write(tmp_path, "config.py", f'KEY = "{key}"')
        assert any("Google API key" in f for f in redline_scan.scan([path], []))

    def test_detects_github_token(self, tmp_path: Path) -> None:
        token = "gh" + "p_" + "C" * 36
        path = _write(tmp_path, "notes.md", f"token: {token}")
        assert any("GitHub token" in f for f in redline_scan.scan([path], []))

    def test_clean_file_passes(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "ok.py", "VALUE = 1\n")
        assert redline_scan.scan([path], []) == []


class TestContactDetails:
    def test_flags_real_looking_email(self, tmp_path: Path) -> None:
        address = "someone@" + "acme-industries.com"
        path = _write(tmp_path, "doc.md", f"Contact {address}")
        assert any("email address" in f for f in redline_scan.scan([path], []))

    def test_allows_example_domains(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "doc.md", "Contact someone@example.com")
        assert redline_scan.scan([path], []) == []

    def test_flags_phone_numbers(self, tmp_path: Path) -> None:
        number = "555-" + "123-" + "4567"
        path = _write(tmp_path, "doc.md", f"Call {number} for support.")
        assert any("phone" in f for f in redline_scan.scan([path], []))


class TestTermList:
    def test_matches_case_insensitively(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "doc.md", "Built while at Acme-Industries.")
        findings = redline_scan.scan([path], ["acme-industries"])
        assert any("red-line term" in f for f in findings)

    def test_reports_once_per_file(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "doc.md", "acme acme acme")
        findings = redline_scan.scan([path], ["acme"])
        assert len([f for f in findings if "red-line term" in f]) == 1

    def test_no_terms_means_no_term_findings(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "doc.md", "Built while at Acme-Industries.")
        assert redline_scan.scan([path], []) == []


class TestDataFiles:
    def test_flags_data_file_outside_examples(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "export.csv", "id,name\n1,a\n")
        assert any("data file outside examples/" in f for f in redline_scan.scan([path], []))


class TestMissingTermList:
    """A fresh clone has no term list. That machine must not report itself clean.

    These drive ``main`` rather than ``scan`` because the refusal is a decision
    about whether to run at all, not a finding about a file.
    """

    @pytest.fixture(autouse=True)
    def _no_terms(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(redline_scan, "TERMS_FILE", tmp_path / ".redline-terms")
        monkeypatch.delenv(redline_scan.ALLOW_MISSING_TERMS_ENV, raising=False)

    def test_refuses_without_term_list(self, tmp_path: Path) -> None:
        clean = _write(tmp_path, "ok.py", "VALUE = 1\n")
        assert redline_scan.main(["redline_scan.py", str(clean)]) == 1

    def test_runs_when_absence_is_declared(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(redline_scan.ALLOW_MISSING_TERMS_ENV, "1")
        clean = _write(tmp_path, "ok.py", "VALUE = 1\n")
        assert redline_scan.main(["redline_scan.py", str(clean)]) == 0

    def test_declared_absence_still_runs_layer_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(redline_scan.ALLOW_MISSING_TERMS_ENV, "1")
        key = "AIza" + "D" * 35
        dirty = _write(tmp_path, "config.py", f'KEY = "{key}"')
        assert redline_scan.main(["redline_scan.py", str(dirty)]) == 1

    def test_term_list_with_only_comments_is_not_a_list(self, tmp_path: Path) -> None:
        (tmp_path / ".redline-terms").write_text("# nothing yet\n", encoding="utf-8")
        clean = _write(tmp_path, "ok.py", "VALUE = 1\n")
        assert redline_scan.main(["redline_scan.py", str(clean)]) == 1
