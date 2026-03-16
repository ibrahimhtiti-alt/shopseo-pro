# -*- coding: utf-8 -*-
"""Advanced keyword research module for Google SEO.

Uses multiple free data sources:
1. Google Suggest API (with alphabet expansion + Shopping mode)
2. Smart seed keyword generation from product data
3. Intent-based keyword categorization
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Simple in-memory cache for Google Suggest results (avoids duplicate API calls)
# ---------------------------------------------------------------------------

_suggest_cache: dict[str, list[str]] = {}
_CACHE_MAX_SIZE = 500  # Max cached queries to prevent memory bloat


def _cache_key(query: str, shopping: bool) -> str:
    """Generate a cache key for a suggest query."""
    return f"{query.lower().strip()}|{'shop' if shopping else 'web'}"


def _get_cached(key: str) -> list[str] | None:
    """Return cached result or None."""
    return _suggest_cache.get(key)


def _set_cache(key: str, results: list[str]) -> None:
    """Store result in cache, evicting oldest if full."""
    if len(_suggest_cache) >= _CACHE_MAX_SIZE:
        # Remove first 100 entries (oldest)
        keys_to_remove = list(_suggest_cache.keys())[:100]
        for k in keys_to_remove:
            del _suggest_cache[k]
    _suggest_cache[key] = results

# ---------------------------------------------------------------------------
# German stop words
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

# Vape-specific noise words (appear on every page but aren't product-relevant)
VAPE_NOISE_WORDS: set[str] = {
    "warenkorb", "kasse", "menü", "suche", "anmelden", "registrieren",
    "newsletter", "agb", "impressum", "datenschutz", "widerrufsrecht",
    "versand", "zahlung", "kontakt", "footer", "header", "navigation",
    "cookie", "cookies", "akzeptieren", "einstellungen", "schließen",
    "mehr", "weniger", "zurück", "weiter", "seite", "startseite",
    "glücksrad", "rabatt", "gutschein", "code", "bestellung", "bestellen",
    "menge", "stück", "verfügbar", "lieferzeit", "werktage",
}


# ===========================================================================
# 1. Google Suggest API (with Shopping mode + relevance scores)
# ===========================================================================

def get_google_suggestions(
    query: str,
    language: str = "de",
    country: str = "DE",
    shopping: bool = False,
    max_results: int = 10,
) -> list[str]:
    """Fetch autocomplete suggestions from Google Suggest API.

    Parameters
    ----------
    query : str
        The seed keyword.
    shopping : bool
        If True, use Google Shopping suggestions (ds=sh) — more relevant
        for e-commerce product keywords.
    """
    # Check cache first
    ck = _cache_key(query, shopping)
    cached = _get_cached(ck)
    if cached is not None:
        logger.debug("Cache-Hit für '%s' (shopping=%s)", query, shopping)
        return cached[:max_results]

    url = "https://suggestqueries.google.com/complete/search"
    params = {
        "client": "chrome",  # Returns JSON with relevance scores
        "hl": language,
        "gl": country,
        "q": query,
    }
    if shopping:
        params["ds"] = "sh"  # Google Shopping suggestions

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=5)
        resp.raise_for_status()
        data = json.loads(resp.text)
        suggestions = data[1] if len(data) > 1 else []
        result = [s for s in suggestions if s.lower() != query.lower()][:max_results]
        _set_cache(ck, result)
        return result
    except Exception as exc:
        logger.warning("Google Suggest Fehler für '%s': %s", query, exc)
        return []


def _google_alphabet_expansion(
    seed: str,
    letters: str = "abcdefghijklmnopqrstuvwxyz",
    shopping: bool = False,
) -> list[str]:
    """Expand a seed keyword with every letter of the alphabet.

    'elfbar a' → suggestions, 'elfbar b' → suggestions, etc.
    This discovers keywords that simple autocomplete misses.
    """
    all_suggestions: list[str] = []
    for char in letters:
        suggestions = get_google_suggestions(f"{seed} {char}", shopping=shopping)
        all_suggestions.extend(suggestions)
        time.sleep(0.15)  # Rate limiting
    return all_suggestions


# ===========================================================================
# 3. Smart Seed Keyword Generation
# ===========================================================================

# German transactional modifiers (high purchase intent)
_TRANSACTIONAL_DE = [
    "kaufen", "bestellen", "online kaufen", "günstig",
    "preis", "angebot", "shop",
]

# German informational modifiers
_INFORMATIONAL_DE = [
    "test", "erfahrung", "bewertung", "vergleich",
    "alternative", "vs", "unterschied",
]

# German question prefixes
_QUESTION_PREFIXES_DE = [
    "was ist", "wie funktioniert", "wie lange hält",
    "welche", "ist", "wie viel",
]


def _generate_seed_keywords(
    product_name: str,
    brand: str = "",
    category: str = "",
    tags: str = "",
) -> list[str]:
    """Generate smart seed keywords from product data.

    Combines product name, brand, category, and tags into diverse
    seed queries that cover different search intents.
    """
    seeds: list[str] = []

    name = product_name.strip()
    brand = brand.strip()
    category = category.strip()

    # 1. Direct product name (full + shortened)
    if name:
        seeds.append(name)
        parts = name.split()
        if len(parts) > 2:
            seeds.append(" ".join(parts[:2]))  # e.g., "ELFBAR 600"
        if len(parts) > 3:
            seeds.append(" ".join(parts[:3]))  # e.g., "ELFBAR 600 V2"

    # 2. Brand alone + brand combinations
    if brand:
        seeds.append(brand)
        if category:
            seeds.append(f"{brand} {category}")

    # 3. Category alone
    if category:
        seeds.append(category)

    # 4. Transactional seeds (purchase intent)
    main = name if name else brand
    if main:
        short_main = " ".join(main.split()[:2])
        for mod in _TRANSACTIONAL_DE[:3]:
            seeds.append(f"{short_main} {mod}")

    # 5. Informational seeds
    if main:
        short_main = " ".join(main.split()[:2])
        for mod in _INFORMATIONAL_DE[:2]:
            seeds.append(f"{short_main} {mod}")

    # 6. Question seeds
    if main:
        short_main = " ".join(main.split()[:2])
        for q in _QUESTION_PREFIXES_DE[:2]:
            seeds.append(f"{q} {short_main}")

    # 7. Tags (if useful)
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if len(t.strip()) > 2]
        for tag in tag_list[:3]:
            if tag.lower() not in (brand.lower(), category.lower()):
                seeds.append(tag)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for s in seeds:
        s_lower = s.lower().strip()
        if s_lower and s_lower not in seen and len(s_lower) > 2:
            seen.add(s_lower)
            unique.append(s)

    return unique


# ===========================================================================
# 4. Intent-based Keyword Categorization
# ===========================================================================

_QUESTION_WORDS = {"was", "wie", "welche", "welcher", "wo", "warum", "wann", "ist", "kann"}

_BUYING_WORDS = {
    "kaufen", "bestellen", "preis", "günstig", "billig", "shop",
    "online", "lieferung", "versand", "angebot", "deal",
}

_RESEARCH_WORDS = {
    "test", "erfahrung", "erfahrungen", "bewertung", "bewertungen",
    "vergleich", "review", "alternative", "vs", "unterschied",
    "empfehlung", "ratgeber",
}


def _categorize_keyword(kw: str) -> str:
    """Classify a keyword by search intent."""
    kw_lower = kw.lower().strip()
    if not kw_lower:
        return "primary"
    words = set(kw_lower.split())
    first_word = kw_lower.split()[0]

    if first_word in _QUESTION_WORDS or kw_lower.endswith("?"):
        return "questions"
    if words & _BUYING_WORDS:
        return "buying"
    if words & _RESEARCH_WORDS:
        return "research"
    if len(kw.split()) >= 4:
        return "longtail"
    return "primary"


# ===========================================================================
# 5. Main Research Function
# ===========================================================================

def research_keywords(
    product_name: str,
    brand: str = "",
    category: str = "",
    tags: str = "",
) -> dict[str, list[str]]:
    """Run comprehensive keyword research for a product/category.

    Combines Google Suggest, Google Shopping Suggest, alphabet expansion,
    and smart seed generation to find the best Google SEO keywords.

    Returns
    -------
    dict with keys:
        - "buying": Purchase-intent keywords (highest priority for sales)
        - "primary": Main product keywords
        - "longtail": Long-tail keyword phrases
        - "questions": Question-based keywords
        - "research": Research/comparison keywords
        - "seeds_used": Which seed keywords were used (for transparency)
    """
    # Guard: empty input → return empty result immediately
    if not product_name.strip() and not brand.strip() and not category.strip():
        logger.warning("Keyword-Recherche abgebrochen: Keine Eingabedaten.")
        return {
            "buying": [], "primary": [], "longtail": [],
            "questions": [], "research": [], "seeds_used": [],
        }

    # Step 1: Generate smart seeds from product data
    seeds = _generate_seed_keywords(product_name, brand, category, tags)
    logger.info("Keyword-Recherche mit %d Seeds: %s", len(seeds), seeds[:5])

    all_seen: set[str] = set()
    categorized: dict[str, list[str]] = {
        "buying": [],
        "primary": [],
        "longtail": [],
        "questions": [],
        "research": [],
    }

    def _add_unique(kw: str, cat: str) -> None:
        kw_lower = kw.lower().strip()
        if kw_lower and kw_lower not in all_seen:
            all_seen.add(kw_lower)
            categorized[cat].append(kw)

    # Step 2: Google Suggest (normal + Shopping mode) for top seeds
    for seed in seeds[:5]:
        # Normal Google suggestions
        for s in get_google_suggestions(seed, shopping=False):
            _add_unique(s, _categorize_keyword(s))

        # Google Shopping suggestions (e-commerce focused)
        for s in get_google_suggestions(seed, shopping=True):
            _add_unique(s, _categorize_keyword(s))

        time.sleep(0.1)

    # Step 3: Alphabet expansion for the main seed (most important)
    main_seed = " ".join(product_name.split()[:2]) if product_name else brand
    if main_seed:
        # Full alphabet expansion for maximum keyword discovery
        for s in _google_alphabet_expansion(main_seed, shopping=False):
            _add_unique(s, _categorize_keyword(s))

    # Step 4: Generate buying keywords if we don't have enough
    if len(categorized["buying"]) < 3 and main_seed:
        for suffix in ["kaufen", "bestellen", "günstig kaufen", "online"]:
            for s in get_google_suggestions(f"{main_seed} {suffix}"):
                _add_unique(s, "buying")
            time.sleep(0.1)

    # Step 5: Generate question keywords if we don't have enough
    if len(categorized["questions"]) < 2 and main_seed:
        for prefix in ["wie", "was ist", "welche"]:
            for s in get_google_suggestions(f"{prefix} {main_seed}"):
                _add_unique(s, "questions")
            time.sleep(0.1)

    # Trim to reasonable sizes
    result = {
        "buying": categorized["buying"][:10],
        "primary": categorized["primary"][:10],
        "longtail": categorized["longtail"][:8],
        "questions": categorized["questions"][:6],
        "research": categorized["research"][:6],
        "seeds_used": seeds[:8],
    }

    total = sum(len(v) for k, v in result.items() if k != "seeds_used")
    logger.info("Keyword-Recherche abgeschlossen: %d Keywords gefunden", total)
    return result


# ===========================================================================
# 6. On-page keyword extraction (main content only)
# ===========================================================================

def extract_main_content_keywords(
    soup: BeautifulSoup,
    resource_type: str = "product",
) -> dict[str, float]:
    """Extract keywords from the MAIN CONTENT area only (not nav/footer)."""
    main_content = _find_main_content(soup, resource_type)

    if main_content is None:
        main_content = copy.copy(soup)
        for tag in main_content.find_all(
            ["nav", "header", "footer", "script", "style", "noscript"]
        ):
            tag.decompose()
        for selector in [
            ".site-header", ".site-footer", ".site-nav",
            "#shopify-section-header", "#shopify-section-footer",
            ".announcement-bar", ".drawer", ".modal",
            "[data-section-type='header']", "[data-section-type='footer']",
        ]:
            for el in main_content.select(selector):
                el.decompose()

    text = main_content.get_text(separator=" ", strip=True).lower()
    text = re.sub(r"[^\w\säöüß]", "", text)
    words = text.split()

    if not words:
        return {}

    total = len(words)
    freq: dict[str, int] = {}
    for word in words:
        if len(word) < 3:
            continue
        if word in GERMAN_STOP_WORDS:
            continue
        if word in VAPE_NOISE_WORDS:
            continue
        if word.isdigit():
            continue
        freq[word] = freq.get(word, 0) + 1

    sorted_keywords = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:10]
    return {kw: round(count / total * 100, 2) for kw, count in sorted_keywords}


def _find_main_content(
    soup: BeautifulSoup,
    resource_type: str,
) -> Optional[BeautifulSoup]:
    """Try to locate the main content container in a Shopify theme."""
    if resource_type == "product":
        selectors = [
            ".product-single", ".product__description",
            ".product-description", "[data-product-description]",
            ".product__content", ".rte", "#product-description",
            "article.product", ".product-template",
        ]
    elif resource_type == "collection":
        selectors = [
            ".collection-description", ".collection__description",
            ".rte", "[data-collection-description]", ".collection-template",
        ]
    else:
        selectors = [
            ".page-content", ".page__content", ".rte",
            "article", ".shopify-section--page", "[data-page-content]",
        ]

    selectors.extend(["main", "[role='main']", "#MainContent", "#main-content"])

    for selector in selectors:
        found = soup.select_one(selector)
        if found and len(found.get_text(strip=True)) > 50:
            return found

    return None
