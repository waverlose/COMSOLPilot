"""Search user-indexed COMSOL manuals and the official support knowledge base."""

from __future__ import annotations

import re
import sqlite3
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from mcp.server.fastmcp import FastMCP


def _database_path() -> Path:
    path = Path(__file__).resolve().parents[2] / "workspace" / "knowledge_base" / "references.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_database_path(), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS manuals USING fts5(
        title, body, source_path UNINDEXED, source_url UNINDEXED,
        version UNINDEXED, module UNINDEXED, section UNINDEXED, page UNINDEXED
    )""")
    return connection


class _ManualHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.sections: list[tuple[str, str]] = []
        self._section = "Introduction"
        self._parts: list[str] = []
        self._skip = 0
        self._heading = False
        self._title = False

    def _flush(self) -> None:
        body = " ".join(" ".join(self._parts).split())
        if body:
            self.sections.append((self._section, body))
        self._parts = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "nav"}:
            self._skip += 1
        elif not self._skip:
            if tag == "title":
                self._title = True
            elif tag in {"h1", "h2", "h3"}:
                self._flush()
                self._heading = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "nav"} and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._title = False
        elif tag in {"h1", "h2", "h3"}:
            self._heading = False

    def handle_data(self, data: str) -> None:
        if self._skip or not data.strip():
            return
        if self._title:
            self.title += data.strip()
        elif self._heading:
            self._section = data.strip()
        else:
            self._parts.append(data)

    def finish(self) -> list[tuple[str, str]]:
        self._flush()
        return self.sections


def index_document(path: str, version: str, module: str = "COMSOL Multiphysics",
                   source_url: str = "") -> dict:
    """Index one locally held manual; source_url is a citation supplied by the user."""
    document = Path(path).expanduser().resolve()
    if not document.is_file() or document.suffix.lower() not in {".pdf", ".html", ".htm", ".txt", ".md"}:
        return {"success": False, "error": "Path must be an existing PDF, HTML, TXT or Markdown file."}
    if not re.fullmatch(r"\d+\.\d+", version.strip()):
        return {"success": False, "error": "version must look like 6.2 or 6.3"}
    if source_url and not re.fullmatch(r"https://(?:[\w-]+\.)?comsol\.com/\S+", source_url):
        return {"success": False, "error": "source_url must point to an official comsol.com page"}
    try:
        if document.suffix.lower() == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError:
                return {"success": False, "error": "PDF indexing requires pypdf (pip install pypdf)."}
            reader = PdfReader(str(document))
            chunks = [(f"Page {number}", page.extract_text() or "", number)
                      for number, page in enumerate(reader.pages, start=1)]
        elif document.suffix.lower() in {".html", ".htm"}:
            parser = _ManualHTML()
            parser.feed(document.read_text(encoding="utf-8", errors="replace"))
            chunks = [(section, body, None) for section, body in parser.finish()]
        else:
            body = document.read_text(encoding="utf-8", errors="replace")
            chunks = [(document.stem, body[i:i + 6000], None)
                      for i in range(0, len(body), 6000)]
    except Exception as exc:
        return {"success": False, "error": f"Could not read document: {str(exc)[:200]}"}
    rows = [(document.stem, body[offset:offset + 6000], str(document), source_url,
             version.strip(), module.strip(), section, page)
            for section, body, page in chunks for offset in range(0, len(body), 6000)
            if body[offset:offset + 6000].strip()]
    if not rows:
        return {"success": False, "error": "No searchable text found; scanned PDFs need OCR first."}
    with _connect() as connection:
        connection.execute("DELETE FROM manuals WHERE source_path = ?", (str(document),))
        connection.executemany("INSERT INTO manuals VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return {"success": True, "path": str(document), "indexed_sections": len(rows),
            "version": version, "module": module}


def search_manuals(query: str, version: str = "", module: str = "", limit: int = 5) -> list[dict]:
    terms = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
    if not terms:
        return []
    match = " OR ".join('"' + term.replace('"', '') + '"' for term in terms[:8])
    filters = " AND (? = '' OR version = ?) AND (? = '' OR module LIKE ?)"
    params = (match, version, version, module, f"%{module}%", limit)
    with _connect() as connection:
        rows = connection.execute(
            "SELECT title, source_path, source_url, version, module, section, page, "
            "snippet(manuals, 1, '', '', '...', 24) AS excerpt FROM manuals "
            "WHERE manuals MATCH ?" + filters + " ORDER BY rank LIMIT ?", params).fetchall()
        if not rows:
            rows = connection.execute(
                "SELECT title, source_path, source_url, version, module, section, page, "
                "substr(body, 1, 320) AS excerpt FROM manuals "
                "WHERE (body LIKE ? OR title LIKE ?)" + filters + " LIMIT ?",
                (f"%{query}%", f"%{query}%", version, version, module,
                 f"%{module}%", limit)).fetchall()
    return [dict(row) for row in rows]


class _KnowledgeBaseHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict] = []
        self._depth = 0
        self._article: dict | None = None
        self._field = ""
        self._link = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "div" and "kb-list" in (attributes.get("class") or "").split():
            self._depth = 1
        elif self._depth and tag == "div":
            self._depth += 1
        if not self._depth:
            return
        if tag == "a" and re.fullmatch(r"/support/knowledgebase/\d+", attributes.get("href") or ""):
            self._flush()
            self._link = attributes["href"] or ""
            self._article = {"source": "COMSOL support knowledge base", "url":
                             "https://cn.comsol.com" + self._link, "title": "",
                             "excerpt": "", "version": "", "module": ""}
        elif tag in {"h3", "p", "span"} and self._article is not None:
            self._field = {"h3": "title", "p": "excerpt", "span": "metadata"}[tag]
        elif tag == "hr":
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._depth:
            self._depth -= 1
            if not self._depth:
                self._flush()
        if tag in {"h3", "p", "span"}:
            self._field = ""

    def handle_data(self, data: str) -> None:
        if self._article is None or not self._field:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self._field == "metadata":
            metadata = self._article.setdefault("_metadata", [])
            metadata.append(text)
        else:
            self._article[self._field] += (" " if self._article[self._field] else "") + text

    def _flush(self) -> None:
        if self._article and self._article["title"]:
            metadata = " ".join(self._article.pop("_metadata", []))
            version = re.search(r"(?:适用版本|Applies to versions?):\s*(.*?)(?=适用于|解决方法编号|$)", metadata)
            module = re.search(r"(?:适用于|Applies to):\s*(.*?)(?=适用版本|Applies to versions?:|解决方法编号|$)", metadata)
            self._article["version"] = version.group(1).strip() if version else ""
            self._article["module"] = module.group(1).strip() if module else ""
            self._article["excerpt"] = self._article["excerpt"][:350]
            self.results.append(self._article)
        self._article = None
        self._field = ""


def search_official_kb(query: str, version: str = "", module: str = "", limit: int = 5) -> list[dict]:
    url = "https://cn.comsol.com/support/knowledgebase?" + urlencode({"s": query})
    request = Request(url, headers={"User-Agent": "COMSOLPilot/0.2 (documentation search)"})
    with urlopen(request, timeout=8) as response:
        page = response.read(2_000_000).decode("utf-8", errors="replace")
    parser = _KnowledgeBaseHTML()
    parser.feed(page)
    parser._flush()
    results = []
    for item in parser.results:
        applies = item["version"]
        if version and applies and "所有版本" not in applies and "all versions" not in applies.lower() and version not in applies:
            continue
        if module and item["module"] and module.casefold() not in item["module"].casefold():
            continue
        results.append(item)
    return results[:limit]


def register_reference_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def reference_index_document(path: str, version: str,
                                 module: str = "COMSOL Multiphysics",
                                 source_url: str = "") -> dict:
        """Index a local COMSOL manual for private, version-aware search.

        Args:
            path: Absolute path to a locally held PDF, HTML, TXT or Markdown manual
            version: COMSOL version, for example 6.2
            module: COMSOL module or physics interface named by this manual
            source_url: Optional official comsol.com URL for citations
        """
        return index_document(path, version, module, source_url)

    @mcp.tool()
    def reference_search(query: str, version: str = "", module: str = "",
                         include_online: bool = True, limit: int = 5) -> dict:
        """Search indexed manuals and COMSOL's official support articles; cite returned sources.

        Args:
            query: Search terms or error text
            version: Optional exact COMSOL version, for example 6.2
            module: Optional COMSOL module filter
            include_online: Also query COMSOL's official support knowledge base
            limit: Maximum results per source, from 1 to 10
        """
        if not query.strip():
            return {"success": False, "error": "query is required"}
        limit = max(1, min(limit, 10))
        result = {"success": True, "manuals": search_manuals(query, version, module, limit),
                  "official_articles": []}
        if include_online:
            try:
                result["official_articles"] = search_official_kb(query, version, module, limit)
            except Exception as exc:
                result["online_error"] = str(exc)[:200]
        return result
