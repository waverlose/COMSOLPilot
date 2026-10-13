"""Structured problem records backed by readable Markdown reference notes."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from mcp.server.fastmcp import FastMCP


_LOCK = threading.RLock()
_ID = re.compile(r"[0-9a-f]{12}")


def _directory() -> Path:
    path = Path(__file__).resolve().parents[2] / "workspace" / "knowledge_base" / "issues"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(issue_id: str) -> Path:
    if not _ID.fullmatch(issue_id):
        raise ValueError("Invalid issue ID")
    return _directory() / f"{issue_id}.json"


def _render(issue: dict) -> str:
    fields = (
        ("Status", issue["status"]),
        ("COMSOL version", issue.get("version") or "unknown"),
        ("Module", issue.get("module") or "unknown"),
        ("Tool", issue.get("tool") or "manual report"),
        ("First seen", issue["created_at"]),
        ("Source", issue.get("source_url") or "none"),
    )
    lines = [f"# {issue['title']}", "", f"Issue ID: `{issue['id']}`", ""]
    lines.extend(f"- {label}: {value}" for label, value in fields)
    lines.extend(("", "## Error", "", issue["error"], "", "## Cause", "",
                  issue.get("cause") or "Pending investigation", "",
                  "## Resolution", "", issue.get("resolution") or "Pending verification",
                  "", "## Verification", "",
                  issue.get("verification_note") or "Not verified", ""))
    return "\n".join(lines)


def _save(issue: dict) -> None:
    directory = _directory()
    directory.mkdir(parents=True, exist_ok=True)
    stem = directory / issue["id"]
    # Replace a complete temporary file so readers never see a half-written note.
    for suffix, content in ((".json", json.dumps(issue, ensure_ascii=False, indent=2)),
                            (".md", _render(issue))):
        temporary = directory / f".{issue['id']}{suffix}.tmp"
        temporary.write_text(content + "\n", encoding="utf-8")
        temporary.replace(stem.with_suffix(suffix))


def _load(issue_id: str) -> dict:
    return json.loads(_path(issue_id).read_text(encoding="utf-8"))


def record_issue(title: str, error: str, tool: str = "", version: str = "",
                 module: str = "") -> dict:
    if not title.strip() or not error.strip():
        return {"success": False, "error": "title and error are required"}
    with _LOCK:
        issue = {
            "id": uuid4().hex[:12],
            "title": title.strip()[:160],
            "error": error.strip()[:2000],
            "tool": tool.strip()[:100],
            "version": version.strip()[:30],
            "module": module.strip()[:100],
            "status": "unverified",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "cause": "",
            "resolution": "",
            "verification_note": "",
            "verification_tool": "",
            "source_url": "",
        }
        _save(issue)
    return {"success": True, "issue_id": issue["id"], "status": issue["status"],
            "note_path": str(_directory() / (issue["id"] + ".md"))}


def capture_tool_failure(tool: str, error: str) -> str | None:
    """Best-effort event capture; instrumentation must never break a tool call."""
    if tool.startswith(("knowledge_", "reference_")):
        return None
    try:
        from .session import pinned_version

        result = record_issue(f"{tool} failed", error or "Tool returned success: false",
                              tool=tool, version=pinned_version() or "")
        return result.get("issue_id")
    except Exception:
        return None


def _has_success_after(issue: dict, tool: str) -> bool:
    log_path = _directory().parents[1] / "logs" / "tool_calls.jsonl"
    if not log_path.is_file():
        return False
    created = datetime.fromisoformat(issue["created_at"])
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
            when = datetime.fromisoformat(event["ts"])
            if event.get("tool") == tool and event.get("status") == "ok" and when >= created:
                return True
        except (ValueError, KeyError, TypeError):
            continue
    return False


def update_issue(issue_id: str, cause: str, resolution: str, source_url: str = "",
                 verification_tool: str = "", verification_note: str = "",
                 version: str = "", module: str = "") -> dict:
    if not cause.strip() or not resolution.strip():
        return {"success": False, "error": "cause and resolution are required"}
    with _LOCK:
        try:
            issue = _load(issue_id)
        except (ValueError, FileNotFoundError):
            return {"success": False, "error": "Issue not found"}
        verified = bool(verification_tool.strip() and verification_note.strip()
                        and _has_success_after(issue, verification_tool.strip()))
        issue.update(cause=cause.strip()[:4000], resolution=resolution.strip()[:4000],
                     source_url=source_url.strip()[:500],
                     verification_tool=verification_tool.strip()[:100],
                     verification_note=verification_note.strip()[:2000],
                     status="verified" if verified else "unverified",
                     updated_at=datetime.now(timezone.utc).isoformat())
        if version.strip():
            issue["version"] = version.strip()[:30]
        if module.strip():
            issue["module"] = module.strip()[:100]
        _save(issue)
    response = {"success": True, "issue_id": issue_id, "status": issue["status"]}
    if verification_tool and not verified:
        response["verification_hint"] = "No successful call to that tool after this issue was recorded."
    return response


def list_issues(status: str = "unverified", limit: int = 20) -> list[dict]:
    issues = []
    with _LOCK:
        for path in _directory().glob("*.json"):
            try:
                issue = json.loads(path.read_text(encoding="utf-8"))
                if status in {"all", issue.get("status")}:
                    issues.append(issue)
            except (OSError, ValueError):
                continue
    issues.sort(key=lambda item: item["created_at"], reverse=True)
    return issues[:max(1, min(limit, 100))]


def search_issues(query: str, include_unverified: bool = False, limit: int = 5) -> list[dict]:
    query = query.casefold().strip()
    if not query:
        return []
    fields = ("title", "error", "cause", "resolution", "module", "tool")
    issues = list_issues("all" if include_unverified else "verified", limit=100)
    return [issue for issue in issues
            if any(query in str(issue.get(field, "")).casefold() for field in fields)][:max(1, min(limit, 20))]


def register_knowledge_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def knowledge_record_issue(title: str, error: str, version: str = "",
                               module: str = "") -> dict:
        """Record a modeling problem as an unverified reference note.

        Args:
            title: Short problem title
            error: Exact error or observed symptom
            version: COMSOL version, if known
            module: COMSOL module or physics interface, if known
        """
        return record_issue(title, error, version=version, module=module)

    @mcp.tool()
    def knowledge_list_issues(status: str = "unverified", limit: int = 20) -> dict:
        """List problem notes needing investigation or already verified.

        Args:
            status: unverified, verified, or all
            limit: Maximum number of notes
        """
        if status not in {"unverified", "verified", "all"}:
            return {"success": False, "error": "status must be unverified, verified, or all"}
        return {"success": True, "issues": list_issues(status, limit)}

    @mcp.tool()
    def knowledge_update_issue(issue_id: str, cause: str, resolution: str,
                               source_url: str = "", verification_tool: str = "",
                               verification_note: str = "", version: str = "",
                               module: str = "") -> dict:
        """Document a fix; verify it only when a later successful tool call supports it.

        Args:
            issue_id: ID returned when the problem was recorded
            cause: Root cause, with uncertainty stated explicitly
            resolution: Steps that fixed or may fix the problem
            source_url: Optional source consulted while investigating
            verification_tool: Tool that succeeded after this issue was recorded
            verification_note: What the successful call demonstrated
            version: COMSOL version if it was unknown when the failure occurred
            module: COMSOL module or physics interface involved
        """
        return update_issue(issue_id, cause, resolution, source_url,
                            verification_tool, verification_note, version, module)

    @mcp.tool()
    def knowledge_search(query: str, include_unverified: bool = False,
                         limit: int = 5) -> dict:
        """Find prior problem notes; only verified fixes are returned by default.

        Args:
            query: Error text, tool name, module, or symptom
            include_unverified: Include tentative notes when investigating
            limit: Maximum results
        """
        return {"success": True, "issues": search_issues(query, include_unverified, limit)}
