"""Tests for export-mcp HTML formatter — lists, blockquotes, code blocks.

Slice SAIMON-HTML-EXPORT-1 (#62): the HTML formatter previously converted
headers/bold/italic/links but passed lists, blockquotes, and fenced code
blocks through as plain text (or wrapped them in <p>).  These tests pin the
expected block-level output.
"""


class TestFormatHtml:
    def _export_html(self, client, sample_trace_id, auth_headers, content, **params):
        response = client.post(
            "/tools/export_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "export",
                "parameters": {"content": content, "format": "html", **params},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["format"] == "html"
        return data["data"]["content"]

    def test_unordered_list(self, client, sample_trace_id, auth_headers):
        html = self._export_html(
            client, sample_trace_id, auth_headers, "- Item 1\n- Item 2"
        )
        assert "<ul><li>Item 1</li><li>Item 2</li></ul>" in html

    def test_blockquote(self, client, sample_trace_id, auth_headers):
        html = self._export_html(
            client, sample_trace_id, auth_headers, "> A blockquote."
        )
        assert "<blockquote>A blockquote.</blockquote>" in html

    def test_fenced_code_block(self, client, sample_trace_id, auth_headers):
        html = self._export_html(
            client,
            sample_trace_id,
            auth_headers,
            "```python\nprint('hello')\n```",
        )
        assert "<pre><code>print('hello')</code></pre>" in html

    def test_headers_still_convert(self, client, sample_trace_id, auth_headers):
        html = self._export_html(
            client, sample_trace_id, auth_headers, "# Heading\n## Sub"
        )
        assert "<h1>Heading</h1>" in html
        assert "<h2>Sub</h2>" in html

    def test_bold_italic_links_still_convert(
        self, client, sample_trace_id, auth_headers
    ):
        html = self._export_html(
            client,
            sample_trace_id,
            auth_headers,
            "**bold** and *italic* and [link](https://example.com)",
        )
        assert "<strong>bold</strong>" in html
        assert "<em>italic</em>" in html
        assert '<a href="https://example.com">link</a>' in html

    def test_code_block_not_split_or_mangled(
        self, client, sample_trace_id, auth_headers
    ):
        # Code containing markdown-ish tokens must survive untouched.
        code = "x = a ** b\nprint(x * 2)\n> not a quote"
        html = self._export_html(
            client, sample_trace_id, auth_headers, f"```python\n{code}\n```"
        )
        assert f"<pre><code>{code}</code></pre>" in html
        assert "<strong>" not in html
        assert "<em>" not in html

    def test_mixed_document(self, client, sample_trace_id, auth_headers):
        content = (
            "# Title\n\n"
            "A **bold** intro.\n\n"
            "- one\n"
            "- two\n\n"
            "> a quote\n\n"
            "```python\nprint('hi')\n```\n\n"
            "Fin."
        )
        html = self._export_html(client, sample_trace_id, auth_headers, content)
        assert "<h1>Title</h1>" in html
        assert "<strong>bold</strong>" in html
        assert "<ul><li>one</li><li>two</li></ul>" in html
        assert "<blockquote>a quote</blockquote>" in html
        assert "<pre><code>print('hi')</code></pre>" in html
