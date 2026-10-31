"""The GitHub issue forms and PR template stay valid and complete."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
FORMS = ROOT / ".github" / "ISSUE_TEMPLATE"
FORM_FILES = ["bug_report.yml", "feature_request.yml", "knowledge_base_update.yml"]


@pytest.mark.parametrize("name", FORM_FILES)
def test_issue_form_is_valid(name):
    data = yaml.safe_load((FORMS / name).read_text(encoding="utf-8"))
    assert {"name", "description", "body"} <= data.keys()
    ids = [b["id"] for b in data["body"] if "id" in b]
    assert len(ids) == len(set(ids))
    for block in data["body"]:
        assert block["type"] in {"markdown", "input", "textarea", "dropdown", "checkboxes"}
        if block["type"] != "markdown":
            assert block["attributes"]["label"]


def test_config_disables_blank_issues_and_links_private_reporting():
    data = yaml.safe_load((FORMS / "config.yml").read_text(encoding="utf-8"))
    assert data["blank_issues_enabled"] is False
    urls = [c["url"] for c in data["contact_links"]]
    assert "https://github.com/mn567250/ekte/security/advisories/new" in urls


def test_pr_template_lists_all_languages():
    text = (ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
    for lang in ("en", "de", "es", "fr", "it", "nb", "pt", "zh-CN"):
        assert lang in text
