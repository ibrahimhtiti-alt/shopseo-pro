# -*- coding: utf-8 -*-
"""Live page crawler and SEO analyzer using BeautifulSoup.

Crawls the public storefront URL and produces a detailed SEO analysis
covering title, meta description, headings, content quality, images,
links, schema markup, canonical tags, Open Graph tags, and TPD2
health-warning compliance.
"""

from __future__ import annotations

import copy
import json
import re
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

from models import SEOAnalysis, SEOIssue

# ---------------------------------------------------------------------------
# German stop words (filtered out during keyword-density analysis)
# ---------------------------------------------------------------------------

GERMAN_STOP_WORDS: set[str] = {
    "der", "die", "das", "und", "in", "von", "zu", "den", "mit", "ist",
    "für", "auf", "im", "dem", "nicht", "ein", "eine", "als", "auch", "es",
    "an", "werden", "aus", "er", "hat", "dass", "sie", "nach", "wird",
    "bei", "einer", "um", "am", "sind", "noch", "wie", "einem", "über",
    "so", "zum", "kann", "man", "war", "diese", "aber", "oder", "haben",
    "nur", "seiner", "ihre", "mehr", "sich", "des", "wir", "ich", "du",
    "was", "mein", "dein", "sein", "ihr", "uns", "euch", "dir", "mir",
    "hier", "dort", "wenn", "dann", "schon", "noch", "sehr", "alle",
    "alles", "jetzt", "vor", "nach", "bis", "durch", "gegen", "ohne",
    "unter", "zwischen",
}


# ---------------------------------------------------------------------------
# SEOAnalyzer
# ---------------------------------------------------------------------------

class SEOAnalyzer:
    """Crawl a public storefront page and return a structured SEO audit."""

    def __init__(self, storefront_url: str, timeout: int = 20) -> None:
        self.storefront_url: str = storefront_url.rstrip("/")
        self.timeout: int = timeout
        self.session: requests.Session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; SEOAnalyzer/1.0)",
        })

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def analyze_page(self, handle: str, resource_type: str) -> SEOAnalysis:
        """Fetch *handle* from the storefront and run a full SEO audit.

        Parameters
        ----------
        handle:
            The URL handle/slug of the resource (e.g. ``"mein-produkt"``).
        resource_type:
            One of ``"Produkt"``, ``"Kategorie"``, or ``"Statische Seite"``.

        Returns
        -------
        SEOAnalysis
            Populated analysis model including score, issues, and metrics.
        """
        # Build the full URL based on resource type
        path_map: dict[str, str] = {
            "Produkt": f"/products/{handle}",
            "Kategorie": f"/collections/{handle}",
            "Statische Seite": f"/pages/{handle}",
        }
        path = path_map.get(resource_type, f"/pages/{handle}")
        url = f"{self.storefront_url}{path}"

        # Fetch HTML
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            html = response.text
        except requests.RequestException as exc:
            return SEOAnalysis(
                url=url,
                score=0,
                issues=[
                    SEOIssue(
                        category="Netzwerk",
                        severity="critical",
                        message=f"Seite konnte nicht geladen werden: {exc}",
                        suggestion="Prüfen Sie die URL und die Internetverbindung.",
                    ),
                ],
            )

        soup = BeautifulSoup(html, "lxml")

        # Store resource type for keyword analysis
        rt_map = {"Produkt": "product", "Kategorie": "collection", "Statische Seite": "page"}
        self._current_resource_type = rt_map.get(resource_type, "product")

        # Run all checks
        all_issues: list[SEOIssue] = []
        all_warnings: list[SEOIssue] = []
        all_passed: list[str] = []

        # Title
        title_issues = self._check_title(soup)
        for issue in title_issues:
            if issue.severity == "critical":
                all_issues.append(issue)
            elif issue.severity == "warning":
                all_warnings.append(issue)

        # Meta description
        meta_issues = self._check_meta_description(soup)
        for issue in meta_issues:
            if issue.severity == "critical":
                all_issues.append(issue)
            elif issue.severity == "warning":
                all_warnings.append(issue)

        # Headings
        heading_issues, has_h1, h1_text, h2_texts = self._check_headings(soup)
        for issue in heading_issues:
            if issue.severity == "critical":
                all_issues.append(issue)
            elif issue.severity == "warning":
                all_warnings.append(issue)

        # Content length
        content_issues, word_count = self._check_content_length(soup, resource_type)
        for issue in content_issues:
            if issue.severity == "critical":
                all_issues.append(issue)
            elif issue.severity == "warning":
                all_warnings.append(issue)

        # Keyword density
        keyword_density = self._analyze_keywords(soup)

        # Images
        image_issues, missing_alt, total_images = self._check_images(soup)
        for issue in image_issues:
            if issue.severity == "critical":
                all_issues.append(issue)
            elif issue.severity == "warning":
                all_warnings.append(issue)

        # Links
        link_issues, internal_links, external_links = self._check_links(soup, url)
        for issue in link_issues:
            if issue.severity == "critical":
                all_issues.append(issue)
            elif issue.severity == "warning":
                all_warnings.append(issue)

        # Schema markup
        schema_issues, has_schema = self._check_schema(soup)
        for issue in schema_issues:
            if issue.severity == "critical":
                all_issues.append(issue)
            elif issue.severity == "warning":
                all_warnings.append(issue)

        # Canonical
        canonical_issues, has_canonical = self._check_canonical(soup)
        for issue in canonical_issues:
            if issue.severity == "critical":
                all_issues.append(issue)
            elif issue.severity == "warning":
                all_warnings.append(issue)

        # Open Graph tags
        og_issues, has_og_tags = self._check_og_tags(soup)
        for issue in og_issues:
            if issue.severity == "critical":
                all_issues.append(issue)
            elif issue.severity == "warning":
                all_warnings.append(issue)

        # TPD2 health warning
        health_issues, has_health_warning = self._check_health_warning(
            soup, resource_type,
        )
        for issue in health_issues:
            if issue.severity == "critical":
                all_issues.append(issue)
            elif issue.severity == "warning":
                all_warnings.append(issue)
            elif issue.severity == "info":
                all_warnings.append(issue)

        # Robots meta
        robots_issues = self._check_robots_meta(soup)
        for issue in robots_issues:
            if issue.severity == "critical":
                all_issues.append(issue)
            elif issue.severity == "warning":
                all_warnings.append(issue)

        # Build passed list from checks that produced no issues
        if not title_issues:
            all_passed.append("Titel-Tag vorhanden und optimale Länge")
        if not meta_issues:
            all_passed.append("Meta-Beschreibung vorhanden und optimale Länge")
        if not heading_issues:
            all_passed.append("Überschriftenstruktur korrekt (eine H1)")
        if not content_issues:
            all_passed.append(f"Ausreichend Inhalt ({word_count} Wörter)")
        if not image_issues and total_images > 0:
            all_passed.append(f"Alle {total_images} Bilder haben Alt-Texte")
        if not link_issues:
            all_passed.append("Interne Verlinkung vorhanden")
        if not schema_issues:
            all_passed.append("Schema-Markup (JSON-LD) vorhanden")
        if not canonical_issues:
            all_passed.append("Canonical-Tag vorhanden")
        if not og_issues:
            all_passed.append("Open-Graph-Tags vorhanden")
        if not health_issues:
            all_passed.append("TPD2-Gesundheitswarnung vorhanden")
        if not robots_issues:
            all_passed.append("Robots-Meta erlaubt Indexierung")

        # Calculate score
        score = self._calculate_score(all_issues, all_warnings, all_passed)

        return SEOAnalysis(
            url=url,
            score=score,
            issues=all_issues,
            warnings=all_warnings,
            passed=all_passed,
            keyword_density=keyword_density,
            word_count=word_count,
            has_h1=has_h1,
            h1_text=h1_text,
            h2_texts=h2_texts,
            missing_alt_images=missing_alt,
            total_images=total_images,
            internal_links=internal_links,
            external_links=external_links,
            has_schema=has_schema,
            has_canonical=has_canonical,
            has_og_tags=has_og_tags,
            has_health_warning=has_health_warning,
        )

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_title(self, soup: BeautifulSoup) -> list[SEOIssue]:
        issues: list[SEOIssue] = []
        title_tag = soup.find("title")

        if not title_tag or not title_tag.string:
            issues.append(SEOIssue(
                category="Titel",
                severity="critical",
                message="Titel-Tag fehlt",
                suggestion="Fügen Sie einen aussagekräftigen <title> hinzu (30-60 Zeichen).",
            ))
            return issues

        title_text = title_tag.string.strip()
        length = len(title_text)

        if length > 60:
            issues.append(SEOIssue(
                category="Titel",
                severity="warning",
                message=f"Titel-Tag zu lang ({length} Zeichen, max. 60)",
                suggestion="Kürzen Sie den Titel auf maximal 60 Zeichen.",
            ))
        elif length < 30:
            issues.append(SEOIssue(
                category="Titel",
                severity="warning",
                message=f"Titel-Tag zu kurz ({length} Zeichen, min. 30)",
                suggestion="Erweitern Sie den Titel auf mindestens 30 Zeichen.",
            ))

        return issues

    def _check_meta_description(self, soup: BeautifulSoup) -> list[SEOIssue]:
        issues: list[SEOIssue] = []
        meta = soup.find("meta", attrs={"name": "description"})

        if not meta or not meta.get("content"):
            issues.append(SEOIssue(
                category="Meta-Beschreibung",
                severity="critical",
                message="Meta-Beschreibung fehlt",
                suggestion="Fügen Sie eine Meta-Beschreibung hinzu (70-160 Zeichen).",
            ))
            return issues

        content = meta["content"].strip()
        length = len(content)

        if length > 160:
            issues.append(SEOIssue(
                category="Meta-Beschreibung",
                severity="warning",
                message=f"Meta-Beschreibung zu lang ({length} Zeichen, max. 160)",
                suggestion="Kürzen Sie die Beschreibung auf maximal 160 Zeichen.",
            ))
        elif length < 70:
            issues.append(SEOIssue(
                category="Meta-Beschreibung",
                severity="warning",
                message=f"Meta-Beschreibung zu kurz ({length} Zeichen, min. 70)",
                suggestion="Erweitern Sie die Beschreibung auf mindestens 70 Zeichen.",
            ))

        return issues

    def _check_headings(
        self, soup: BeautifulSoup,
    ) -> tuple[list[SEOIssue], bool, str, list[str]]:
        issues: list[SEOIssue] = []
        h1_tags = soup.find_all("h1")
        h1_count = len(h1_tags)
        has_h1 = h1_count > 0
        h1_text = h1_tags[0].get_text(strip=True) if has_h1 else ""

        if h1_count == 0:
            issues.append(SEOIssue(
                category="Überschriften",
                severity="critical",
                message="Keine H1-Überschrift gefunden",
                suggestion="Fügen Sie genau eine H1-Überschrift mit dem Haupt-Keyword hinzu.",
            ))
        elif h1_count > 1:
            issues.append(SEOIssue(
                category="Überschriften",
                severity="warning",
                message=f"Mehrere H1-Überschriften gefunden ({h1_count})",
                suggestion="Verwenden Sie nur eine einzige H1-Überschrift pro Seite.",
            ))

        h2_texts = [h2.get_text(strip=True) for h2 in soup.find_all("h2")]

        return issues, has_h1, h1_text, h2_texts

    def _check_content_length(
        self, soup: BeautifulSoup, resource_type: str = "Produkt",
    ) -> tuple[list[SEOIssue], int]:
        issues: list[SEOIssue] = []

        # Extract visible text (skip script and style) on a COPY to avoid
        # mutating the original soup used by subsequent checks.
        soup_copy = copy.copy(soup)
        for tag in soup_copy(["script", "style", "noscript"]):
            tag.decompose()

        text = soup_copy.get_text(separator=" ", strip=True)
        words = text.split()
        word_count = len(words)

        # Resource-type-specific thresholds
        thresholds = {
            "Produkt": {"critical": 50, "warning": 150, "target": 300},
            "Kategorie": {"critical": 30, "warning": 80, "target": 150},
            "Statische Seite": {"critical": 50, "warning": 100, "target": 200},
        }
        t = thresholds.get(resource_type, thresholds["Produkt"])

        if word_count < t["critical"]:
            issues.append(SEOIssue(
                category="Inhalt",
                severity="critical",
                message=f"Sehr wenig Inhalt: Nur {word_count} Wörter (empfohlen: {t['target']}+)",
                suggestion=f"Erstelle ausführlichere Inhalte mit mindestens {t['target']} Wörtern.",
            ))
        elif word_count < t["warning"]:
            issues.append(SEOIssue(
                category="Inhalt",
                severity="warning",
                message=f"Dünn-Content: Nur {word_count} Wörter (empfohlen: {t['target']}+)",
                suggestion=f"Erweitere den Inhalt auf mindestens {t['target']} Wörter.",
            ))

        return issues, word_count

    def _analyze_keywords(self, soup: BeautifulSoup) -> dict[str, float]:
        """Return the top-10 keywords with density (%), focused on main content."""
        from keyword_research import extract_main_content_keywords

        # Use improved extraction that focuses on main content only
        resource_type_str = getattr(self, "_current_resource_type", "product")
        return extract_main_content_keywords(soup, resource_type_str)

    def _check_images(
        self, soup: BeautifulSoup,
    ) -> tuple[list[SEOIssue], int, int]:
        issues: list[SEOIssue] = []
        images = soup.find_all("img")
        total = len(images)
        missing = 0

        for img in images:
            alt = img.get("alt")
            if alt is None or alt.strip() == "":
                missing += 1

        if missing > 0:
            issues.append(SEOIssue(
                category="Bilder",
                severity="warning",
                message=f"{missing} von {total} Bildern ohne Alt-Text",
                suggestion="Fügen Sie beschreibende Alt-Texte für alle Bilder hinzu.",
            ))

        return issues, missing, total

    def _check_links(
        self, soup: BeautifulSoup, url: str,
    ) -> tuple[list[SEOIssue], int, int]:
        issues: list[SEOIssue] = []
        parsed_base = urlparse(url)
        base_domain = parsed_base.netloc

        anchors = soup.find_all("a", href=True)
        internal_count = 0
        external_count = 0

        for a in anchors:
            href = a["href"].strip()
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue

            absolute = urljoin(url, href)
            parsed = urlparse(absolute)

            if parsed.netloc == base_domain:
                internal_count += 1
            else:
                external_count += 1

        if internal_count == 0:
            issues.append(SEOIssue(
                category="Links",
                severity="warning",
                message="Keine internen Links gefunden",
                suggestion="Fügen Sie interne Links zu verwandten Produkten oder Kategorien hinzu.",
            ))

        return issues, internal_count, external_count

    def _check_schema(
        self, soup: BeautifulSoup,
    ) -> tuple[list[SEOIssue], bool]:
        issues: list[SEOIssue] = []
        ld_scripts = soup.find_all("script", attrs={"type": "application/ld+json"})

        has_schema = False
        for script in ld_scripts:
            try:
                data = json.loads(script.string or "")
                if isinstance(data, dict) and "@type" in data:
                    has_schema = True
                    break
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "@type" in item:
                            has_schema = True
                            break
                if has_schema:
                    break
            except (json.JSONDecodeError, TypeError):
                continue

        if not has_schema:
            issues.append(SEOIssue(
                category="Schema",
                severity="warning",
                message="Kein strukturiertes Schema-Markup (JSON-LD) gefunden",
                suggestion="Fügen Sie JSON-LD-Schema-Markup hinzu (z. B. Product, BreadcrumbList).",
            ))

        return issues, has_schema

    def _check_canonical(
        self, soup: BeautifulSoup,
    ) -> tuple[list[SEOIssue], bool]:
        issues: list[SEOIssue] = []
        canonical = soup.find("link", attrs={"rel": "canonical"})
        has_canonical = canonical is not None

        if not has_canonical:
            issues.append(SEOIssue(
                category="Canonical",
                severity="warning",
                message="Kein Canonical-Tag gefunden",
                suggestion="Fügen Sie ein <link rel=\"canonical\"> hinzu, um Duplicate Content zu vermeiden.",
            ))

        return issues, has_canonical

    def _check_og_tags(
        self, soup: BeautifulSoup,
    ) -> tuple[list[SEOIssue], bool]:
        issues: list[SEOIssue] = []
        og_title = soup.find("meta", attrs={"property": "og:title"})
        og_desc = soup.find("meta", attrs={"property": "og:description"})
        og_image = soup.find("meta", attrs={"property": "og:image"})

        missing_tags: list[str] = []
        if not og_title:
            missing_tags.append("og:title")
        if not og_desc:
            missing_tags.append("og:description")
        if not og_image:
            missing_tags.append("og:image")

        has_og_tags = len(missing_tags) == 0

        if missing_tags:
            issues.append(SEOIssue(
                category="Open Graph",
                severity="warning",
                message=f"Fehlende Open-Graph-Tags: {', '.join(missing_tags)}",
                suggestion="Fügen Sie die fehlenden OG-Tags für eine bessere Social-Media-Darstellung hinzu.",
            ))

        return issues, has_og_tags

    def _check_health_warning(
        self, soup: BeautifulSoup, resource_type: str,
    ) -> tuple[list[SEOIssue], bool]:
        """Check for TPD2 nicotine health warning on the page."""
        issues: list[SEOIssue] = []
        page_text = soup.get_text(separator=" ", strip=True).lower()

        # Check for the mandatory TPD2 warning phrases
        has_nikotin = bool(re.search(
            r"dieses\s+produkt\s+enthält\s+nikotin", page_text, re.IGNORECASE,
        ))
        has_abhaengig = bool(re.search(
            r"abhängig\s+macht", page_text, re.IGNORECASE,
        ))

        has_health_warning = has_nikotin and has_abhaengig

        if not has_health_warning:
            if resource_type == "Produkt":
                issues.append(SEOIssue(
                    category="TPD2-Compliance",
                    severity="critical",
                    message="TPD2-Gesundheitswarnung fehlt!",
                    suggestion=(
                        "Fügen Sie den gesetzlich vorgeschriebenen Hinweis hinzu: "
                        "\"Dieses Produkt enthält Nikotin: einen Stoff, "
                        "der sehr stark abhängig macht.\""
                    ),
                ))
            else:
                issues.append(SEOIssue(
                    category="TPD2-Compliance",
                    severity="info",
                    message="TPD2-Gesundheitswarnung nicht auf dieser Seite gefunden",
                    suggestion=(
                        "Prüfen Sie, ob eine Gesundheitswarnung auf dieser "
                        "Seitenart erforderlich ist."
                    ),
                ))

        return issues, has_health_warning

    def _check_robots_meta(self, soup: BeautifulSoup) -> list[SEOIssue]:
        issues: list[SEOIssue] = []
        robots_meta = soup.find("meta", attrs={"name": "robots"})

        if robots_meta:
            content = (robots_meta.get("content") or "").lower()
            if "noindex" in content:
                issues.append(SEOIssue(
                    category="Robots",
                    severity="critical",
                    message="Seite ist auf 'noindex' gesetzt — wird nicht von Google indexiert",
                    suggestion="Entfernen Sie 'noindex' aus dem Robots-Meta-Tag.",
                ))
            if "nofollow" in content:
                issues.append(SEOIssue(
                    category="Robots",
                    severity="warning",
                    message="Seite ist auf 'nofollow' gesetzt — Links werden nicht verfolgt",
                    suggestion="Entfernen Sie 'nofollow', damit Google den internen Links folgen kann.",
                ))

        return issues

    # ------------------------------------------------------------------
    # Score calculation
    # ------------------------------------------------------------------

    def _calculate_score(
        self,
        issues: list[SEOIssue],
        warnings: list[SEOIssue],
        passed: list[str],
    ) -> int:
        """Weighted score: start at 100, -15 per critical, -5 per warning."""
        score = 100
        score -= len(issues) * 15
        score -= len(warnings) * 5
        return max(0, min(100, score))
