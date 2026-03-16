# -*- coding: utf-8 -*-
"""HTML sanitization and validation for Shopify content."""

import re
from html.parser import HTMLParser

import nh3


class _TagBalanceChecker(HTMLParser):
    """Lightweight HTML parser that tracks open/close tag balance."""

    VOID_ELEMENTS = frozenset(
        {
            "area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr",
        }
    )

    def __init__(self) -> None:
        super().__init__()
        self.errors: list[str] = []
        self._stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in self.VOID_ELEMENTS:
            self._stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.VOID_ELEMENTS:
            return
        if not self._stack:
            self.errors.append(f"Unerwartetes schließendes Tag: </{tag}>")
            return
        if self._stack[-1] == tag:
            self._stack.pop()
        else:
            self.errors.append(
                f"Unerwartetes schließendes Tag: </{tag}> (erwartet: </{self._stack[-1]}>)"
            )

    def get_result(self) -> tuple[bool, list[str]]:
        for tag in reversed(self._stack):
            self.errors.append(f"Nicht geschlossenes Tag: <{tag}>")
        return (len(self.errors) == 0, self.errors)


class HTMLSanitizer:
    """HTML validation, sanitization, and safety checks for Shopify content."""

    ALLOWED_TAGS: set[str] = {
        "p", "h1", "h2", "h3", "h4", "h5", "h6",
        "ul", "ol", "li",
        "a", "strong", "em", "b", "i", "br",
        "img", "span", "div",
        "table", "tr", "td", "th", "thead", "tbody",
        "blockquote", "hr", "sup", "sub",
        # Semantische HTML5-Tags für besseres SEO
        "section", "article", "aside", "nav",
        "details", "summary",
        "figure", "figcaption",
        "mark", "time", "code", "pre",
    }

    # NOTE: "rel" is handled internally by nh3 and must NOT be in attributes.
    # Use link_rel parameter instead.
    ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
        "a": {"href", "title", "target"},
        "img": {"src", "alt", "title", "width", "height", "loading", "decoding"},
        "time": {"datetime"},
        "*": {"class", "id"},
    }

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def sanitize(self, html: str) -> str:
        """Remove disallowed tags/attributes using *nh3*."""
        if not html:
            return ""
        return nh3.clean(
            html,
            tags=self.ALLOWED_TAGS,
            attributes=self.ALLOWED_ATTRIBUTES,
        )

    def validate_html(self, html: str) -> tuple[bool, list[str]]:
        """Check for balanced tags. Returns *(is_valid, errors)*."""
        if not html:
            return (True, [])
        checker = _TagBalanceChecker()
        checker.feed(html)
        return checker.get_result()

    def check_liquid_syntax(self, html: str) -> tuple[bool, list[str]]:
        """Detect Liquid template syntax (``{{ }}`` / ``{% %}``)."""
        if not html:
            return (False, [])
        patterns = re.findall(r"\{\{.*?\}\}|\{%.*?%\}", html)
        return (bool(patterns), patterns)

    def check_max_length(self, html: str, max_kb: int = 50) -> tuple[bool, str]:
        """Return *(is_over_limit, message)* based on UTF-8 byte size."""
        if not html:
            return (False, "")
        size = len(html.encode("utf-8"))
        limit = max_kb * 1024
        if size > limit:
            return (
                True,
                f"HTML-Inhalt ist zu groß: {size / 1024:.1f} KB "
                f"(Maximum: {max_kb} KB).",
            )
        return (False, "")

    def preserve_health_warning(
        self, old_html: str, new_html: str
    ) -> tuple[bool, str]:
        """Ensure the legally required TPD2 health warning is not removed."""
        if not old_html:
            return (True, "")

        lower_old = old_html.lower()
        lower_new = new_html.lower() if new_html else ""

        has_warning_old = (
            "dieses produkt enthält nikotin" in lower_old
            or "enthält nikotin" in lower_old
        )
        has_warning_new = (
            "dieses produkt enthält nikotin" in lower_new
            or "enthält nikotin" in lower_new
        )

        if has_warning_old and not has_warning_new:
            return (
                False,
                "TPD2-Gesundheitswarnung wurde entfernt! "
                "Dies ist gesetzlich vorgeschrieben.",
            )
        return (True, "")

    # ------------------------------------------------------------------
    # Combined entry point
    # ------------------------------------------------------------------

    def full_check(
        self, html: str, old_html: str = ""
    ) -> tuple[str, list[str]]:
        """Run every check and return *(sanitized_html, warnings)*.

        This is the main entry point called by ``app.py``.
        """
        warnings: list[str] = []

        if not html:
            return ("", warnings)

        # 1. Sanitize
        sanitized = self.sanitize(html)

        # 2. Validate tag balance
        is_valid, validation_errors = self.validate_html(sanitized)
        if not is_valid:
            warnings.extend(validation_errors)

        # 3. Liquid syntax detection – strip and warn
        has_liquid, liquid_patterns = self.check_liquid_syntax(sanitized)
        if has_liquid:
            warnings.append(
                f"Liquid-Syntax erkannt und entfernt: {', '.join(liquid_patterns)}"
            )
            sanitized = re.sub(r"\{\{.*?\}\}|\{%.*?%\}", "", sanitized)

        # 4. Size check
        is_over, size_msg = self.check_max_length(sanitized)
        if is_over:
            warnings.append(size_msg)

        # 5. TPD2 health warning
        if old_html:
            preserved, health_msg = self.preserve_health_warning(
                old_html, sanitized
            )
            if not preserved:
                warnings.append(health_msg)

        return (sanitized, warnings)
