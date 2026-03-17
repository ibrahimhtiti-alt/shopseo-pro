# -*- coding: utf-8 -*-
"""Pydantic data models and custom exceptions for the SEO tool."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ResourceType(str, Enum):
    """Shopify resource types (German labels for UI display)."""

    PRODUCT = "Produkt"
    COLLECTION = "Kategorie"
    PAGE = "Statische Seite"


# ---------------------------------------------------------------------------
# SEO-related models
# ---------------------------------------------------------------------------

class ImageSEO(BaseModel):
    """SEO metadata for a single image."""

    image_id: int
    image_src: str = ""
    current_alt: str = ""
    suggested_alt: str = ""


class SEOData(BaseModel):
    """Aggregated SEO fields for any resource."""

    # No hard max_length — the AI sometimes exceeds limits.
    # Lengths are checked in the UI with visual badges instead.
    seo_title: str = ""
    meta_description: str = ""
    h1: str = ""
    h2_list: list[str] = Field(default_factory=list)
    body_html: str = ""
    images: list[ImageSEO] = Field(default_factory=list)


class SEOIssue(BaseModel):
    """A single SEO audit finding."""

    category: str
    severity: str  # "critical", "warning", "info"
    message: str
    suggestion: str = ""


class SEOAnalysis(BaseModel):
    """Full SEO audit result for a page or resource."""

    url: str = ""
    score: int = 0  # 0-100
    issues: list[SEOIssue] = Field(default_factory=list)
    warnings: list[SEOIssue] = Field(default_factory=list)
    passed: list[str] = Field(default_factory=list)
    keyword_density: dict[str, float] = Field(default_factory=dict)
    word_count: int = 0
    has_h1: bool = False
    h1_text: str = ""
    h2_texts: list[str] = Field(default_factory=list)
    missing_alt_images: int = 0
    total_images: int = 0
    internal_links: int = 0
    external_links: int = 0
    has_schema: bool = False
    has_canonical: bool = False
    has_og_tags: bool = False
    has_health_warning: bool = False
    # Keyword research results (from Google Suggest)
    suggested_keywords: dict[str, list[str]] = Field(default_factory=dict)
    # Keys: "primary", "longtail", "questions", "buying"


# ---------------------------------------------------------------------------
# Shopify resource models
# ---------------------------------------------------------------------------

def _extract_h2_list(body_html: str) -> list[str]:
    """Parse *body_html* and return a list of H2 texts."""
    if not body_html:
        return []
    from bs4 import BeautifulSoup  # noqa: WPS433 (local import keeps module light)

    soup = BeautifulSoup(body_html, "html.parser")
    return [h2.get_text(strip=True) for h2 in soup.find_all("h2")]


class ShopifyProduct(BaseModel):
    """Representation of a Shopify product with SEO-relevant fields."""

    id: int
    title: str
    handle: str
    body_html: str = ""
    vendor: str = ""
    product_type: str = ""
    tags: str = ""
    images: list[dict] = Field(default_factory=list)
    seo_title: str = ""
    meta_description: str = ""
    updated_at: str = ""
    status: str = "active"  # active, draft, archived
    total_inventory: int = 0  # Sum of all variant inventory quantities

    def to_seo_data(self) -> SEOData:
        """Extract the current SEO state from product fields."""
        image_seos: list[ImageSEO] = []
        for img in self.images:
            image_seos.append(
                ImageSEO(
                    image_id=img.get("id", 0),
                    image_src=img.get("src", ""),
                    current_alt=img.get("alt", "") or "",
                )
            )

        return SEOData(
            seo_title=self.seo_title or self.title,
            meta_description=self.meta_description,
            h1=self.title,
            h2_list=_extract_h2_list(self.body_html),
            body_html=self.body_html,
            images=image_seos,
        )


class ShopifyCollection(BaseModel):
    """Representation of a Shopify collection (custom or smart)."""

    id: int
    title: str
    handle: str
    body_html: str = ""
    collection_type: str = ""  # "custom" or "smart"
    image: Optional[dict] = None
    seo_title: str = ""
    meta_description: str = ""
    updated_at: str = ""

    def to_seo_data(self) -> SEOData:
        """Extract the current SEO state from collection fields."""
        images: list[ImageSEO] = []
        if self.image and isinstance(self.image, dict):
            images.append(
                ImageSEO(
                    image_id=self.image.get("id", 0),
                    image_src=self.image.get("src", ""),
                    current_alt=self.image.get("alt", "") or "",
                )
            )

        return SEOData(
            seo_title=self.seo_title or self.title,
            meta_description=self.meta_description,
            h1=self.title,
            h2_list=_extract_h2_list(self.body_html),
            body_html=self.body_html,
            images=images,
        )


class ShopifyPage(BaseModel):
    """Representation of a Shopify static page."""

    id: int
    title: str
    handle: str
    body_html: str = ""
    seo_title: str = ""
    meta_description: str = ""
    updated_at: str = ""

    def to_seo_data(self) -> SEOData:
        """Extract the current SEO state from page fields."""
        return SEOData(
            seo_title=self.seo_title or self.title,
            meta_description=self.meta_description,
            h1=self.title,
            h2_list=_extract_h2_list(self.body_html),
            body_html=self.body_html,
            images=[],
        )


# ---------------------------------------------------------------------------
# Comparison / tracking models
# ---------------------------------------------------------------------------

class SEOComparison(BaseModel):
    """Side-by-side comparison of current vs. suggested SEO data."""

    resource_type: ResourceType
    resource_id: int
    resource_title: str
    current: SEOData
    suggested: SEOData
    analysis: Optional[SEOAnalysis] = None


class RankingData(BaseModel):
    """A single ranking data point from Google Search Console."""

    url: str
    keyword: str
    position: float = 0.0
    clicks: int = 0
    impressions: int = 0
    ctr: float = 0.0
    date: str = ""


class BackupEntry(BaseModel):
    """Record of a change made to a Shopify resource (for rollback)."""

    id: int = 0
    resource_type: str
    resource_id: int
    timestamp: str = ""
    before_state: dict = Field(default_factory=dict)
    after_state: dict = Field(default_factory=dict)
    rolled_back: bool = False


class ComplianceWarning(BaseModel):
    """A regulatory compliance finding (e.g. TPD2 health warnings)."""

    category: str
    message: str
    found_terms: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Competitor & Ranking Intelligence models
# ---------------------------------------------------------------------------

class Competitor(BaseModel):
    """A tracked competitor domain."""

    id: str  # slug, e.g. "dampfplanet"
    name: str  # Display name
    domain: str  # e.g. "www.dampfplanet.de"
    added_date: str = ""


class CompetitorRanking(BaseModel):
    """A single competitor position data point."""

    competitor_id: str
    keyword: str
    position: float = 0.0
    url: str = ""  # The competitor page that ranks
    date: str = ""
    source: str = "manual"  # "manual", "google_cse", "serpapi"


class KeywordAlert(BaseModel):
    """Alert for significant keyword position changes."""

    keyword: str
    url: str = ""
    old_position: float
    new_position: float
    change: float  # positive = improved (moved up)
    date: str = ""
    alert_type: str = ""  # "winner", "loser", "new", "lost"


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class SEOToolError(Exception):
    """Base exception for the SEO tool."""


class ShopifyAuthError(SEOToolError):
    """Raised when Shopify authentication fails."""


class ShopifyConnectionError(SEOToolError):
    """Raised when a connection to Shopify cannot be established."""


class ShopifyRateLimitError(SEOToolError):
    """Raised when the Shopify API rate limit is exceeded."""


class ShopifyNotFoundError(SEOToolError):
    """Raised when a requested Shopify resource does not exist."""


class AIEngineError(SEOToolError):
    """Raised when the AI engine (Anthropic) returns an error."""


class AIParseError(AIEngineError):
    """Raised when the AI engine response cannot be parsed."""
