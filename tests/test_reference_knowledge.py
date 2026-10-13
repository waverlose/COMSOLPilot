"""Focused tests for source citations and verified problem records."""

import json
from datetime import datetime, timezone
from pathlib import Path

from src.tools import knowledge, reference, telemetry


def test_local_manual_search_keeps_version_and_section(tmp_path, monkeypatch):
    monkeypatch.setattr(reference, "_database_path", lambda: tmp_path / "references.sqlite3")
    manual = tmp_path / "heat.html"
    manual.write_text("<html><title>Heat Transfer</title><body><h2>Boundary Conditions</h2>"
                      "<p>Temperature boundary selects a surface.</p></body></html>",
                      encoding="utf-8")

    indexed = reference.index_document(str(manual), "6.3", "Heat Transfer",
                                       "https://doc.comsol.com/6.3/heat")
    assert indexed["success"] is True
    matches = reference.search_manuals("Temperature", "6.3", "Heat Transfer")
    assert matches[0]["section"] == "Boundary Conditions"
    assert matches[0]["source_url"] == "https://doc.comsol.com/6.3/heat"
    assert reference.search_manuals("Temperature", "6.2") == []


def test_chinese_manual_substring_search(tmp_path, monkeypatch):
    monkeypatch.setattr(reference, "_database_path", lambda: tmp_path / "references.sqlite3")
    manual = tmp_path / "solver.txt"
    manual.write_text("这个非线性稳态模型的收敛性需要检查初始值。", encoding="utf-8")
    assert reference.index_document(str(manual), "6.3")["success"]
    assert reference.search_manuals("收敛", "6.3")


def test_image_only_pdf_is_not_reported_as_indexed(tmp_path, monkeypatch):
    monkeypatch.setattr(reference, "_database_path", lambda: tmp_path / "references.sqlite3")
    from pypdf import PdfWriter

    path = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with path.open("wb") as handle:
        writer.write(handle)
    result = reference.index_document(str(path), "6.3")
    assert result["success"] is False
    assert "OCR" in result["error"]


def test_official_article_parser_and_filters():
    page = """<div class="card-box kb-entry kb-list">
    <a href="/support/knowledgebase/1262"><h3>Improve transient convergence</h3></a>
    <span>Applies to: Heat Transfer Module</span>
    <span>Applies to versions: 6.3</span>
    <p>Check initial conditions.</p><hr /></div>"""
    parser = reference._KnowledgeBaseHTML()
    parser.feed(page)
    assert parser.results[0]["url"] == "https://cn.comsol.com/support/knowledgebase/1262"
    assert parser.results[0]["excerpt"] == "Check initial conditions."
    assert parser.results[0]["version"] == "6.3"
    assert parser.results[0]["module"] == "Heat Transfer Module"


def test_issue_stays_unverified_until_later_success(tmp_path, monkeypatch):
    issues = tmp_path / "workspace" / "knowledge_base" / "issues"
    monkeypatch.setattr(knowledge, "_directory", lambda: issues)
    created = knowledge.record_issue("solve failed", "Singular matrix", "study_solve", "6.3")
    issue_id = created["issue_id"]
    assert created["status"] == "unverified"
    assert "Singular matrix" in (issues / f"{issue_id}.md").read_text(encoding="utf-8")

    pending = knowledge.update_issue(issue_id, "Missing boundary condition", "Add fixed value",
                                     verification_tool="study_solve", verification_note="Converged")
    assert pending["status"] == "unverified"
    assert knowledge.search_issues("Singular matrix") == []

    logs = tmp_path / "workspace" / "logs"
    logs.mkdir(parents=True)
    event = {"ts": datetime.now(timezone.utc).isoformat(), "tool": "study_solve", "status": "ok"}
    (logs / "tool_calls.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
    verified = knowledge.update_issue(issue_id, "Missing boundary condition", "Add fixed value",
                                      verification_tool="study_solve", verification_note="Converged")
    assert verified["status"] == "verified"
    assert knowledge.search_issues("Singular matrix")[0]["id"] == issue_id


def test_failed_tool_creates_reference_note(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge, "_directory", lambda: tmp_path / "knowledge_base" / "issues")
    monkeypatch.setattr(telemetry, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(telemetry, "ensure_banner", lambda: None)
    monkeypatch.setattr(telemetry, "push_comsol_message", lambda message: True)
    monkeypatch.setattr(telemetry, "_tracked_models", lambda: set())
    monkeypatch.setattr(telemetry, "_request_autosave", lambda force=False: None)
    monkeypatch.setattr("src.tools.session.pinned_version", lambda: "6.3")

    class Tool:
        fn = staticmethod(lambda: {"success": False, "error": "No domain selected"})

    class Manager:
        _tools = {"geometry_create": Tool()}

    class Server:
        _tool_manager = Manager()

    assert telemetry.install_observability(Server()) == 1
    result = Manager._tools["geometry_create"].fn()
    issue_id = result["knowledge_issue_id"]
    assert (tmp_path / "knowledge_base" / "issues" / f"{issue_id}.json").exists()
    log = (tmp_path / "workspace" / "logs" / "tool_calls.jsonl").read_text(encoding="utf-8")
    assert json.loads(log)["knowledge_issue_id"] == issue_id
