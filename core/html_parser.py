"""
html_parser.py — Native Python HTML parser (no third-party libraries).
Extracts visible text content and absolute hyperlinks from raw HTML.
"""

import html.parser
import urllib.parse
import re


class _HTMLParser(html.parser.HTMLParser):
    """Internal SAX-style parser that accumulates text and links."""

    # Tags whose content blocks should be entirely skipped.
    # IMPORTANT: only include tags that have matching close tags (<script>…</script>).
    # Void elements like <meta>, <link>, <br>, <img> must NOT appear here because
    # html.parser only fires handle_starttag for them (no handle_endtag), which
    # would permanently increment _skip_depth without decrementing it.
    SKIP_TAGS = {"script", "style", "noscript", "object", "iframe", "svg", "canvas"}

    # Void elements have no closing tag — never put them in SKIP_TAGS.
    VOID_ELEMENTS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._links: list[str] = []
        self._text_parts: list[str] = []
        self._title: list[str] = []
        self._skip_depth = 0          # nesting depth inside skip tags
        self._in_title = False
        self._in_head  = False        # track <head> separately

    # ── Event handlers ─────────────────────────────────────────────────────

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()

        # Track <head> to suppress non-title head content
        if tag == "head":
            self._in_head = True
            return  # don't push onto SKIP_TAGS stack

        # Void elements: never modify _skip_depth
        if tag in self.VOID_ELEMENTS:
            if tag == "link" or tag == "meta":
                return  # no useful attrs for us; skip

        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return

        if tag == "title":
            self._in_title = True
            return

        if tag == "a":
            attr_dict = dict(attrs)
            href = attr_dict.get("href", "")
            if href:
                self._links.append(href)

    def handle_endtag(self, tag: str):
        tag = tag.lower()

        if tag == "head":
            self._in_head = False
            return

        if tag in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return

        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str):
        # Skip content inside script/style/etc.
        if self._skip_depth > 0:
            return
        # Inside <head>, only capture <title> text
        if self._in_head and not self._in_title:
            return

        stripped = data.strip()
        if stripped:
            if self._in_title:
                self._title.append(stripped)
            else:
                self._text_parts.append(stripped)

    # ── Accessors ──────────────────────────────────────────────────────────

    @property
    def title(self) -> str:
        return " ".join(self._title).strip()[:256]

    @property
    def text(self) -> str:
        return " ".join(self._text_parts)

    @property
    def links(self) -> list[str]:
        return self._links


def parse_html(html_content: str, base_url: str) -> tuple[str, str, list[str]]:
    """
    Parse raw HTML and return (title, clean_text, absolute_urls).

    Args:
        html_content: Raw HTML string.
        base_url: Base URL used to resolve relative hrefs.

    Returns:
        title        — Page title or empty string.
        clean_text   — Visible text content.
        absolute_urls — List of absolute http/https URLs found on the page.
    """
    parser = _HTMLParser()
    try:
        parser.feed(html_content)
    except Exception:
        pass  # Best-effort parsing

    # Resolve links to absolute URLs
    absolute_urls: list[str] = []
    seen: set[str] = set()
    for raw_link in parser.links:
        try:
            full = urllib.parse.urljoin(base_url, raw_link.strip())
            # Strip fragment
            full = urllib.parse.urldefrag(full)[0]
            if full.startswith(("http://", "https://")) and full not in seen:
                seen.add(full)
                absolute_urls.append(full)
        except Exception:
            continue

    return parser.title, parser.text, absolute_urls
