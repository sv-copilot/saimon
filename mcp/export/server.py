"""server.py — export-mcp FastAPI application.

Provides output-formatting tools that convert raw content into
structured export formats (markdown, plain_text, json, html).
Every tool endpoint accepts a ResearchRequest envelope and returns
a ResearchResponse envelope.  Authentication is fail-closed.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request

from research_shared.audit import AuditLogger
from research_shared.auth import AuthConfig, AuthError, AuthValidator
from research_shared.envelope import ResearchRequest, ResearchResponse
from research_shared.lifespan import build_lifespan

# ---------------------------------------------------------------------------
# application factory
# ---------------------------------------------------------------------------

_lifespan = build_lifespan("export-mcp")
app = FastAPI(title="export-mcp", version="0.1.0", lifespan=_lifespan)

# ---------------------------------------------------------------------------
# auth (fail-closed)
# ---------------------------------------------------------------------------

_auth_config = AuthConfig.from_env()
_auth = AuthValidator(_auth_config)


def _require_auth(request: Request) -> None:
    """Fail-closed auth guard.  Called as a FastAPI dependency."""
    if _auth.has_api_key:
        key = _auth.extract_from_headers(dict(request.headers))
        try:
            _auth.validate(key)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc))


# ---------------------------------------------------------------------------
# format registry
# ---------------------------------------------------------------------------

_FORMATS: dict[str, dict[str, Any]] = {
    "markdown": {
        "name": "markdown",
        "description": "Rich markdown with headers, lists, emphasis, and links.",
        "options": ["include_title", "include_citations", "table_of_contents"],
    },
    "plain_text": {
        "name": "plain_text",
        "description": "Stripped-down plain text with markdown syntax removed.",
        "options": ["include_title", "include_citations", "line_width"],
    },
    "json": {
        "name": "json",
        "description": "Structured JSON with content, metadata, and citations.",
        "options": ["pretty_print", "include_metadata", "include_citations"],
    },
    "html": {
        "name": "html",
        "description": "HTML document with basic styling and semantic markup.",
        "options": ["include_title", "include_citations", "inline_css"],
    },
}


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, Any]:
    """Unauthenticated health check."""
    return {
        "status": "ok",
        "service": "export-mcp",
        "checks": {"backend": "stateless"},
    }


# ---------------------------------------------------------------------------
# tool listing
# ---------------------------------------------------------------------------

_TOOLS = [
    {
        "name": "export_content",
        "description": "Format raw content into a specified output format.",
        "parameters": {
            "content": "str (required)",
            "format": "str (required, one of: markdown, plain_text, json, html)",
            "include_title": "bool (optional)",
            "include_citations": "bool (optional)",
        },
    },
    {
        "name": "list_formats",
        "description": "List all available export formats with their options.",
        "parameters": {},
    },
    {
        "name": "get_format_schema",
        "description": "Get the parameter schema for a specific export format.",
        "parameters": {"format_name": "str (required)"},
    },
]


@app.get("/tools")
async def list_tools(request: Request) -> dict[str, Any]:
    """Return the tool manifest for this MCP."""
    _require_auth(request)
    return {"tools": _TOOLS}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _ok(
    trace_id: str,
    data: Any = None,
    citations: list[str] | None = None,
) -> ResearchResponse:
    return ResearchResponse(
        trace_id=trace_id,
        status="success",
        data=data,
        citations=citations,
    )


def _error(trace_id: str, message: str) -> ResearchResponse:
    return ResearchResponse(
        trace_id=trace_id,
        status="error",
        errors=[message],
    )


# ---------------------------------------------------------------------------
# format engines
# ---------------------------------------------------------------------------

def _format_markdown(content: str, options: dict[str, Any]) -> str:
    """Pass through markdown content, optionally prepending a title."""
    if options.get("include_title"):
        title = options.get("title", "Exported Content")
        return f"# {title}\n\n{content}"
    return content


def _format_plain_text(content: str, options: dict[str, Any]) -> str:
    """Strip markdown syntax to produce plain text."""
    import re

    text = content
    # Strip headers: # Text → Text
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Strip bold/italic: **text**, *text*, __text__, _text_
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
    text = re.sub(r"_{1,2}([^_]+)_{1,2}", r"\1", text)
    # Strip links: [text](url) → text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Strip inline code: `code`
    text = re.sub(r"`([^`]+)`", r"\1", text)

    line_width = options.get("line_width")
    if line_width and isinstance(line_width, int) and line_width > 0:
        lines = text.split("\n")
        wrapped: list[str] = []
        for line in lines:
            while len(line) > line_width:
                break_at = line.rfind(" ", 0, line_width)
                if break_at == -1:
                    break_at = line_width
                wrapped.append(line[:break_at])
                line = line[break_at:].lstrip()
            wrapped.append(line)
        text = "\n".join(wrapped)

    if options.get("include_title"):
        title = options.get("title", "Exported Content")
        text = f"{title}\n\n{text}"

    return text


def _format_json(content: str, options: dict[str, Any]) -> str:
    """Wrap content in structured JSON."""
    import json as json_mod

    result: dict[str, Any] = {"content": content, "format": "json"}

    if options.get("include_metadata"):
        result["metadata"] = {
            "word_count": len(content.split()),
            "char_count": len(content),
        }

    if options.get("pretty_print"):
        return json_mod.dumps(result, indent=2, ensure_ascii=False)
    return json_mod.dumps(result, ensure_ascii=False)


def _format_html(content: str, options: dict[str, Any]) -> str:
    """Convert markdown-ish content to HTML."""
    import re

    html_content = content
    # Headers: # Text → <h1>Text</h1>, ## Text → <h2>Text</h2>, etc.
    html_content = re.sub(
        r"^# (.+)$", r"<h1>\1</h1>", html_content, flags=re.MULTILINE
    )
    html_content = re.sub(
        r"^## (.+)$", r"<h2>\1</h2>", html_content, flags=re.MULTILINE
    )
    html_content = re.sub(
        r"^### (.+)$", r"<h3>\1</h3>", html_content, flags=re.MULTILINE
    )
    html_content = re.sub(
        r"^#### (.+)$", r"<h4>\1</h4>", html_content, flags=re.MULTILINE
    )
    # Bold: **text** → <strong>text</strong>
    html_content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html_content)
    # Italic: *text* → <em>text</em>
    html_content = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html_content)
    # Links: [text](url) → <a href="url">text</a>
    html_content = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', html_content
    )
    # Wrap paragraphs: blank lines → </p><p>
    paragraphs = html_content.split("\n\n")
    wrapped = [f"<p>{p.strip()}</p>" for p in paragraphs if p.strip()]
    body = "\n".join(wrapped)

    inline_css = options.get("inline_css", True)
    style = (
        "body { font-family: system-ui, sans-serif; max-width: 800px; "
        "margin: 0 auto; padding: 2rem; line-height: 1.6; }"
        if inline_css
        else ""
    )
    title_tag = ""
    if options.get("include_title"):
        title_text = options.get("title", "Exported Content")
        title_tag = f"<title>{title_text}</title>\n"
        body = f"<h1>{title_text}</h1>\n{body}"

    html = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"{title_tag}"
        f"<style>{style}</style>\n"
        "</head>\n<body>\n"
        f"{body}\n"
        "</body>\n</html>"
    )
    return html


# ---------------------------------------------------------------------------
# tool: export_content
# ---------------------------------------------------------------------------

@app.post("/tools/export_content")
async def export_content(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    content = payload.parameters.get("content")
    if not content:
        return _error(payload.trace_id, "Parameter 'content' is required.")

    fmt = payload.parameters.get("format")
    if not fmt:
        return _error(payload.trace_id, "Parameter 'format' is required.")

    fmt_schema = _FORMATS.get(fmt)
    if fmt_schema is None:
        supported = ", ".join(sorted(_FORMATS.keys()))
        return _error(
            payload.trace_id,
            f"Unknown format: {fmt!r}. Supported formats: {supported}.",
        )

    logger = AuditLogger(trace_id=payload.trace_id, service_name="export-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="export_content",
        format=fmt,
        content_length=len(content),
        sources_count=len(payload.sources),
    )

    # Gather options (format-specific)
    options: dict[str, Any] = {}
    for opt_key in fmt_schema.get("options", []):
        if opt_key in payload.parameters:
            options[opt_key] = payload.parameters[opt_key]

    # Derive citations
    citations = (
        [s.identifier for s in payload.sources] if payload.sources else []
    )

    # Format output
    formatters = {
        "markdown": _format_markdown,
        "plain_text": _format_plain_text,
        "json": _format_json,
        "html": _format_html,
    }
    formatter = formatters[fmt]
    output = formatter(content, options)

    resp = _ok(
        trace_id=payload.trace_id,
        data={
            "format": fmt,
            "content": output,
            "original_length": len(content),
            "output_length": len(output),
        },
        citations=citations,
    )
    logger.log_response(
        status=resp.status, citations_count=len(resp.citations or [])
    )
    return resp


# ---------------------------------------------------------------------------
# tool: list_formats
# ---------------------------------------------------------------------------

@app.post("/tools/list_formats")
async def list_formats(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    logger = AuditLogger(trace_id=payload.trace_id, service_name="export-mcp")
    logger.log_request(content_type=payload.content_type, tool="list_formats")

    formats = [
        {
            "name": name,
            "description": schema["description"],
            "options": schema["options"],
        }
        for name, schema in _FORMATS.items()
    ]

    resp = _ok(trace_id=payload.trace_id, data={"formats": formats})
    logger.log_response(status=resp.status)
    return resp


# ---------------------------------------------------------------------------
# tool: get_format_schema
# ---------------------------------------------------------------------------

@app.post("/tools/get_format_schema")
async def get_format_schema(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    format_name = payload.parameters.get("format_name")
    if not format_name:
        return _error(payload.trace_id, "Parameter 'format_name' is required.")

    logger = AuditLogger(trace_id=payload.trace_id, service_name="export-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="get_format_schema",
        format_name=format_name,
    )

    schema = _FORMATS.get(format_name)
    if schema is None:
        supported = ", ".join(sorted(_FORMATS.keys()))
        return _error(
            payload.trace_id,
            f"Unknown format: {format_name!r}. Supported formats: {supported}.",
        )

    resp = _ok(trace_id=payload.trace_id, data=schema)
    logger.log_response(status=resp.status)
    return resp
