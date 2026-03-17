# -*- coding: utf-8 -*-
"""ShopSEO Pro — KI-gestützte SEO-Optimierung für Shopify-Stores."""

from __future__ import annotations

import hashlib
import json
import os
import logging
import time
from typing import Optional

import pandas as pd
import streamlit as st

from config import AppConfig
from models import (
    ResourceType,
    SEOData,
    SEOAnalysis,
    SEOComparison,
    ImageSEO,
    ComplianceWarning,
    RankingData,
    BackupEntry,
    ShopifyProduct,
    ShopifyCollection,
    ShopifyPage,
)
from shopify_client import ShopifyClient
from seo_analyzer import SEOAnalyzer
from ai_engine import SEOEngine
from ranking_tracker import RankingTracker
from backup_store import BackupStore
from html_sanitizer import HTMLSanitizer

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="ShopSEO Pro",
    page_icon="\U0001f680",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS for improved UI
# ---------------------------------------------------------------------------

def _load_css() -> None:
    """Load external CSS file for styling."""
    from pathlib import Path
    css_path = Path(__file__).resolve().parent / "styles.css"
    if css_path.exists():
        css_text = css_path.read_text(encoding="utf-8")
        st.markdown(f"<style>{css_text}</style>", unsafe_allow_html=True)
    else:
        logging.warning("styles.css not found — using default Streamlit styling.")

_load_css()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ADMIN_USER = os.environ.get("ADMIN_USERNAME", "")
_ADMIN_PASS_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "")

_USING_DEFAULT_CREDENTIALS = not _ADMIN_USER or not _ADMIN_PASS_HASH

if _USING_DEFAULT_CREDENTIALS:
    logging.warning(
        "ADMIN_USERNAME / ADMIN_PASSWORD_HASH nicht in .env gesetzt. "
        "Login ist deaktiviert bis Credentials konfiguriert sind."
    )

_TITLE_MAX = 60
_DESC_MAX = 160

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _char_count_badge(text: str, max_len: int) -> str:
    """Return a coloured Markdown badge showing character count vs limit."""
    length = len(text) if text else 0
    colour = "green" if length <= max_len else "red"
    return f":{colour}[{length}/{max_len} Zeichen]"


def _build_page_url(config: AppConfig, resource_type: ResourceType, handle: str) -> str:
    """Build the public storefront URL for a given resource."""
    base = config.get_storefront_url()
    path_map = {
        ResourceType.PRODUCT: f"/products/{handle}",
        ResourceType.COLLECTION: f"/collections/{handle}",
        ResourceType.PAGE: f"/pages/{handle}",
    }
    return base + path_map.get(resource_type, f"/pages/{handle}")


def _score_colour(score: int) -> str:
    """Return a CSS-friendly colour string for a score value."""
    if score >= 80:
        return "green"
    if score >= 50:
        return "orange"
    return "red"


def _score_css_class(score: int) -> str:
    """Return CSS class name for score box."""
    if score >= 80:
        return "score-good"
    if score >= 50:
        return "score-mid"
    return "score-bad"


def _get_shopify_client() -> ShopifyClient | None:
    cfg = st.session_state.get("config")
    if cfg is None:
        return None
    return ShopifyClient(cfg)


def _get_ranking_tracker() -> RankingTracker | None:
    cfg: AppConfig | None = st.session_state.get("config")
    if cfg is None:
        return None
    if "ranking_tracker" not in st.session_state:
        st.session_state["ranking_tracker"] = RankingTracker(
            site_url=cfg.get_storefront_url(),
            credentials_path=cfg.google_credentials_path,
        )
    return st.session_state["ranking_tracker"]


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


_MAX_LOGIN_ATTEMPTS = 5
_LOGIN_LOCKOUT_SECONDS = 60
_SESSION_MAX_AGE_SECONDS = 86400  # 24 hours


def _show_login() -> None:
    """Render a simple login form with rate limiting."""
    col_empty1, col_login, col_empty2 = st.columns([1, 2, 1])
    with col_login:
        st.markdown(
            '<div class="login-container">'
            '<div class="login-logo">ShopSEO Pro</div>'
            '<div class="login-subtitle">KI-gestützte SEO-Optimierung</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        if _USING_DEFAULT_CREDENTIALS:
            st.error(
                "⛔ Login deaktiviert. Setze `ADMIN_USERNAME` und "
                "`ADMIN_PASSWORD_HASH` in der `.env`-Datei um den Zugang zu aktivieren."
            )
            st.info(
                "**Passwort-Hash erzeugen:**\n"
                "```python\nimport hashlib\n"
                "print(hashlib.sha256('dein-passwort'.encode()).hexdigest())\n```"
            )
            return

        # Rate limiting: check for lockout
        attempts = st.session_state.get("_login_attempts", 0)
        lockout_until = st.session_state.get("_login_lockout_until", 0)
        now = time.time()

        if now < lockout_until:
            remaining = int(lockout_until - now)
            st.error(
                f"⏳ Zu viele Fehlversuche. Bitte warte {remaining} Sekunden."
            )
            return

        with st.form("login_form"):
            username = st.text_input("Benutzername")
            password = st.text_input("Passwort", type="password")
            submitted = st.form_submit_button("Anmelden", use_container_width=True)

        if submitted:
            pass_hash = hashlib.sha256(password.encode()).hexdigest()
            if username == _ADMIN_USER and pass_hash == _ADMIN_PASS_HASH:
                st.session_state["authenticated"] = True
                st.session_state["_auth_time"] = time.time()
                st.session_state["_login_attempts"] = 0
                st.rerun()
            else:
                attempts += 1
                st.session_state["_login_attempts"] = attempts
                if attempts >= _MAX_LOGIN_ATTEMPTS:
                    st.session_state["_login_lockout_until"] = now + _LOGIN_LOCKOUT_SECONDS
                    st.error(
                        f"⛔ {_MAX_LOGIN_ATTEMPTS} Fehlversuche — "
                        f"Login für {_LOGIN_LOCKOUT_SECONDS}s gesperrt."
                    )
                else:
                    remaining = _MAX_LOGIN_ATTEMPTS - attempts
                    st.error(
                        f"Benutzername oder Passwort falsch. "
                        f"({remaining} Versuche übrig)"
                    )


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------


def _render_sidebar() -> None:
    """Render the configuration sidebar."""
    st.sidebar.markdown(
        '<p class="config-label">Konfiguration</p>',
        unsafe_allow_html=True,
    )

    # Load existing config
    saved = AppConfig.load_from_env()
    defaults = {
        "store_url": saved.shopify_store_url if saved else "",
        "access_token": saved.shopify_access_token if saved else "",
        "anthropic_key": saved.anthropic_api_key if saved else "",
        "storefront_url": saved.storefront_url if saved else "",
        "google_creds": saved.google_credentials_path if saved else "",
        "ai_provider": saved.ai_provider if saved else "anthropic",
    }

    with st.sidebar.expander("Shopify-Verbindung", expanded=not st.session_state.get("connection_ok")):
        store_url = st.text_input("Shopify Store URL", value=defaults["store_url"], key="sb_store_url")
        access_token = st.text_input(
            "Shopify Access Token", value=defaults["access_token"], type="password", key="sb_token"
        )
        storefront_url = st.text_input(
            "Storefront URL (optional)", value=defaults["storefront_url"], key="sb_storefront"
        )

    with st.sidebar.expander("KI-Einstellungen", expanded=False):
        ai_provider = st.selectbox(
            "KI-Provider",
            options=["anthropic", "openrouter"],
            index=0 if defaults.get("ai_provider", "anthropic") == "anthropic" else 1,
            format_func=lambda x: "Anthropic (direkt)" if x == "anthropic" else "OpenRouter (viele Modelle)",
            key="sb_provider",
        )

        api_key_label = "Anthropic API Key" if ai_provider == "anthropic" else "OpenRouter API Key"
        anthropic_key = st.text_input(
            api_key_label, value=defaults["anthropic_key"], type="password", key="sb_api_key"
        )

        # Model-Auswahl
        available = SEOEngine.AVAILABLE_MODELS.get(ai_provider, {})
        model_names = list(available.keys())
        selected_model_name = st.selectbox("KI-Modell", options=model_names, index=0, key="sb_model")
        selected_model_id = available.get(selected_model_name, "")
        st.session_state["ai_provider"] = ai_provider
        st.session_state["ai_model_id"] = selected_model_id
        st.session_state["ai_model_name"] = selected_model_name

    with st.sidebar.expander("Google Search Console", expanded=False):
        google_creds = st.text_input(
            "Google Credentials Pfad", value=defaults["google_creds"], key="sb_gcreds"
        )

    # Build config if all required fields are present
    if store_url and access_token and anthropic_key:
        cfg = AppConfig(
            shopify_store_url=store_url,
            shopify_access_token=access_token,
            anthropic_api_key=anthropic_key,
            storefront_url=storefront_url,
            google_credentials_path=google_creds,
            ai_provider=ai_provider,
        )
        st.session_state["config"] = cfg
    else:
        st.session_state["config"] = None

    st.sidebar.markdown("---")

    col_save, col_test = st.sidebar.columns(2)

    with col_save:
        if st.button("Speichern", use_container_width=True, key="sb_save"):
            cfg = st.session_state.get("config")
            if cfg:
                try:
                    cfg.save_to_env()
                    st.sidebar.success("Gespeichert!")
                except Exception as exc:
                    st.sidebar.error(f"Fehler: {exc}")
            else:
                st.sidebar.warning("Pflichtfelder fehlen.")

    with col_test:
        if st.button("Testen", use_container_width=True, key="sb_test"):
            cfg = st.session_state.get("config")
            if not cfg:
                st.sidebar.warning("Pflichtfelder fehlen.")
            else:
                # Shopify
                client = ShopifyClient(cfg)
                ok, msg = client.test_connection()
                if ok:
                    st.sidebar.success(f"Shopify: {msg}")
                    st.session_state["connection_ok"] = True
                else:
                    st.sidebar.error(f"Shopify: {msg}")
                    st.session_state["connection_ok"] = False

                # Search Console
                if cfg.google_credentials_path:
                    tracker = RankingTracker(
                        site_url=cfg.get_storefront_url(),
                        credentials_path=cfg.google_credentials_path,
                    )
                    gsc_ok, gsc_msg = tracker.connect()
                    if gsc_ok:
                        st.sidebar.success(f"GSC: {gsc_msg}")
                        st.session_state["gsc_connected"] = True
                    else:
                        st.sidebar.error(f"GSC: {gsc_msg}")
                        st.session_state["gsc_connected"] = False
                else:
                    st.session_state["gsc_connected"] = False

    # Connection status
    st.sidebar.markdown("---")
    status_col1, status_col2 = st.sidebar.columns(2)
    with status_col1:
        if st.session_state.get("connection_ok"):
            st.markdown(
                '<span class="status-dot status-dot-green"></span>'
                '<span class="status-label">Shopify</span>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<span class="status-dot status-dot-red"></span>'
                '<span class="status-label">Shopify</span>',
                unsafe_allow_html=True,
            )
    with status_col2:
        if st.session_state.get("gsc_connected"):
            st.markdown(
                '<span class="status-dot status-dot-green"></span>'
                '<span class="status-label">GSC</span>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<span class="status-dot status-dot-gray"></span>'
                '<span class="status-label">GSC</span>',
                unsafe_allow_html=True,
            )

    # Logout
    st.sidebar.markdown("---")
    if st.sidebar.button("Abmelden", use_container_width=True, key="sb_logout"):
        st.session_state["authenticated"] = False
        st.rerun()


# ---------------------------------------------------------------------------
# Tab 1 — SEO Optimierung
# ---------------------------------------------------------------------------


def _load_items(resource_type: ResourceType) -> list[dict]:
    """Load the item list for the chosen resource type from Shopify."""
    client = _get_shopify_client()
    if client is None:
        return []

    try:
        if resource_type == ResourceType.PRODUCT:
            items = client.list_products()
            return [
                {
                    "id": p.id,
                    "title": p.title,
                    "handle": p.handle,
                    "status": getattr(p, "status", "active"),
                    "total_inventory": getattr(p, "total_inventory", 0),
                }
                for p in items
            ]
        elif resource_type == ResourceType.COLLECTION:
            items = client.list_collections()
            return [
                {
                    "id": c.id,
                    "title": c.title,
                    "handle": c.handle,
                    "collection_type": c.collection_type,
                }
                for c in items
            ]
        else:
            items = client.list_pages()
            return [{"id": p.id, "title": p.title, "handle": p.handle} for p in items]
    except Exception as exc:
        st.error(f"Fehler beim Laden der Ressourcen: {exc}")
        return []


def _render_score_box(score: int) -> None:
    """Render a large, coloured score box."""
    css_class = _score_css_class(score)
    label = "Gut" if score >= 80 else ("Mittel" if score >= 50 else "Kritisch")
    st.markdown(
        f'<div class="score-box {css_class}">'
        f'{score}<span style="font-size:1rem;font-weight:400;opacity:0.7;">/100</span>'
        f'<br><span style="font-size:0.85rem;font-weight:500;letter-spacing:0.02em;'
        f'text-transform:uppercase;opacity:0.85;">{label}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_score_breakdown(analysis: SEOAnalysis) -> None:
    """Render a transparent score breakdown showing how the score is calculated."""
    st.markdown("**Score-Berechnung:**")
    st.caption("Start: 100 Punkte | -15 pro kritisches Problem | -5 pro Warnung")

    critical_count = len([i for i in analysis.issues if i.severity == "critical"])
    warning_count = len(analysis.warnings)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Ausgangswert", "100")
    with col2:
        if critical_count:
            st.metric("Kritisch", f"-{critical_count * 15}", delta=f"{critical_count} Probleme", delta_color="inverse")
        else:
            st.metric("Kritisch", "0", delta="Keine", delta_color="off")
    with col3:
        if warning_count:
            st.metric("Warnungen", f"-{warning_count * 5}", delta=f"{warning_count} Warnungen", delta_color="inverse")
        else:
            st.metric("Warnungen", "0", delta="Keine", delta_color="off")


def _render_seo_analysis(analysis: SEOAnalysis) -> None:
    """Render the SEO analysis results with improved UI."""
    # Score section
    score_col, detail_col = st.columns([1, 3])

    with score_col:
        _render_score_box(analysis.score)

    with detail_col:
        _render_score_breakdown(analysis)

    st.markdown("---")

    # Quick stats in metric cards
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Wortanzahl", analysis.word_count)
    c2.metric("Bilder ohne Alt", analysis.missing_alt_images, delta=f"von {analysis.total_images}", delta_color="off")
    c3.metric("Interne Links", analysis.internal_links)
    c4.metric("Schema", "Ja" if analysis.has_schema else "Nein")
    c5.metric("TPD2-Warnung", "Ja" if analysis.has_health_warning else "Nein")

    # Issues & Warnings in organized layout
    issues_col, passed_col = st.columns([2, 1])

    with issues_col:
        # Critical issues
        criticals = [i for i in analysis.issues if i.severity == "critical"]
        if criticals:
            st.markdown("#### Kritische Probleme")
            for issue in criticals:
                st.error(f"**{issue.category}:** {issue.message}\n\n*{issue.suggestion}*")

        # Warnings
        if analysis.warnings:
            st.markdown("#### Warnungen")
            for w in analysis.warnings:
                st.warning(f"**{w.category}:** {w.message}\n\n*{w.suggestion}*")

        if not criticals and not analysis.warnings:
            st.success("Keine Probleme oder Warnungen gefunden!")

    with passed_col:
        if analysis.passed:
            st.markdown("#### Bestanden")
            for p in analysis.passed:
                st.markdown(f":green[{p}]")

    # --- Keyword Section ---
    st.markdown("---")
    st.markdown("### Keyword-Analyse")

    kw_col1, kw_col2 = st.columns(2)

    with kw_col1:
        if analysis.keyword_density:
            st.markdown("**Aktuelle Keywords auf der Seite:**")
            st.caption("Hauptinhalt (ohne Menue/Footer)")
            kw_data = [
                {"Keyword": kw, "Dichte (%)": f"{density:.2f}"}
                for kw, density in sorted(
                    analysis.keyword_density.items(), key=lambda x: x[1], reverse=True
                )[:10]
            ]
            st.dataframe(pd.DataFrame(kw_data), use_container_width=True, hide_index=True)

    with kw_col2:
        if analysis.suggested_keywords:
            sk = analysis.suggested_keywords
            total_kw = sum(
                len(v) for k, v in sk.items() if k != "seeds_used" and isinstance(v, list)
            )
            st.markdown(f"**Google Keyword-Recherche** ({total_kw} Keywords)")
            st.caption("Echte Suchanfragen von Google + Google Shopping")

            if sk.get("buying"):
                st.markdown("**Kauf-Keywords** (Höchste Priorität):")
                pills = " ".join(f'<span class="kw-pill kw-pill-buy">{kw}</span>' for kw in sk["buying"])
                st.markdown(pills, unsafe_allow_html=True)

            if sk.get("primary"):
                st.markdown("**Primäre Keywords:**")
                pills = " ".join(f'<span class="kw-pill">{kw}</span>' for kw in sk["primary"])
                st.markdown(pills, unsafe_allow_html=True)

            if sk.get("research"):
                st.markdown("**Vergleich/Test-Keywords:**")
                pills = " ".join(f'<span class="kw-pill">{kw}</span>' for kw in sk["research"])
                st.markdown(pills, unsafe_allow_html=True)

            if sk.get("longtail"):
                st.markdown("**Longtail-Keywords:**")
                pills = " ".join(f'<span class="kw-pill">{kw}</span>' for kw in sk["longtail"])
                st.markdown(pills, unsafe_allow_html=True)

            if sk.get("questions"):
                st.markdown("**Fragen-Keywords** (für FAQ):")
                pills = " ".join(f'<span class="kw-pill kw-pill-question">{kw}</span>' for kw in sk["questions"])
                st.markdown(pills, unsafe_allow_html=True)

            if sk.get("seeds_used"):
                with st.expander("Verwendete Suchbegriffe", expanded=False):
                    for s in sk["seeds_used"]:
                        st.caption(f"-> {s}")
        else:
            st.info("Keine Keywords gefunden.")


def _render_ranking_section(
    ranking_data: list[RankingData],
    config: AppConfig,
    resource_type: ResourceType,
    handle: str,
) -> None:
    """Render ranking data and history."""
    st.subheader("Google Rankings")

    if not ranking_data:
        st.info("Keine Ranking-Daten verfügbar.")
        return

    rows = []
    for rd in ranking_data:
        rows.append(
            {
                "Keyword": rd.keyword,
                "Position": f"{rd.position:.1f}",
                "Klicks": rd.clicks,
                "Impressionen": rd.impressions,
                "CTR": f"{rd.ctr * 100:.1f}%",
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # Snapshot button
    if st.button("Ranking-Snapshot speichern", key="seo_tab_ranking_snap"):
        tracker = _get_ranking_tracker()
        if tracker:
            tracker.save_snapshot(ranking_data)
            st.success("Snapshot gespeichert!")


def _change_indicator(old: str, new: str) -> str:
    """Return a coloured indicator showing if a field changed."""
    if not old and not new:
        return ":gray[---]"
    if old == new:
        return ":gray[Keine Änderung]"
    return ":orange[Geändert]"


def _render_content_preview(body_html: str) -> None:
    """Render an HTML preview of the body content using a real HTML iframe.

    The iframe always uses a light background with dark text so that
    HTML content is readable regardless of the Streamlit dark/light theme.
    """
    if not body_html:
        st.caption("(kein Inhalt)")
        return
    # Use st.components.v1.html for true HTML rendering (no Streamlit tag filtering)
    import streamlit.components.v1 as components
    wrapped = (
        '<div style="font-family:Inter,-apple-system,BlinkMacSystemFont,sans-serif;'
        'font-size:14px;line-height:1.7;color:#1d1d1f;padding:16px;'
        'background:#ffffff;border-radius:8px;'
        '-webkit-font-smoothing:antialiased;">'
        '<style>'
        'body{margin:0;background:#ffffff;}'
        'h1,h2,h3,h4,h5,h6{color:#1d1d1f;}'
        'p,li,td,th,span,div{color:#1d1d1f;}'
        'a{color:#007AFF;}'
        'table{border-collapse:collapse;width:100%;}'
        'th,td{border:1px solid #e0e0e0;padding:8px;text-align:left;}'
        'th{background:#f5f5f7;}'
        'img{max-width:100%;height:auto;border-radius:4px;}'
        '</style>'
        f'{body_html}</div>'
    )
    components.html(wrapped, height=400, scrolling=True)


def _render_comparison_dashboard(comparison: SEOComparison) -> None:
    """Render the side-by-side current vs. suggested SEO dashboard."""
    current = comparison.current
    suggested = comparison.suggested

    # ---- Summary of changes ----
    changes_count = 0
    if current.seo_title != suggested.seo_title:
        changes_count += 1
    if current.meta_description != suggested.meta_description:
        changes_count += 1
    if current.h1 != suggested.h1:
        changes_count += 1
    if current.body_html != suggested.body_html:
        changes_count += 1
    img_changes = sum(
        1
        for img in suggested.images
        if img.suggested_alt and img.suggested_alt != img.current_alt
    )

    ch_col1, ch_col2, ch_col3 = st.columns(3)
    ch_col1.metric("Textfelder geändert", f"{changes_count}/4")
    ch_col2.metric("Bilder geändert", f"{img_changes}/{len(suggested.images)}")
    ch_col3.metric("Gesamt-Änderungen", changes_count + img_changes)

    # ================================================================
    # SEO-Titel
    # ================================================================
    st.markdown("---")
    st.markdown(f"### SEO-Titel {_change_indicator(current.seo_title, suggested.seo_title)}")
    col_old, col_new = st.columns(2)
    with col_old:
        st.markdown(f"**Aktuell** {_char_count_badge(current.seo_title, _TITLE_MAX)}")
        st.code(current.seo_title or "(leer)")
    with col_new:
        new_title = st.text_input(
            f"Vorschlag {_char_count_badge(suggested.seo_title, _TITLE_MAX)}",
            value=suggested.seo_title,
            max_chars=80,
            key="edit_seo_title",
        )
        st.markdown(_char_count_badge(new_title, _TITLE_MAX))

    # ================================================================
    # Meta-Beschreibung
    # ================================================================
    st.markdown("---")
    st.markdown(
        f"### Meta-Beschreibung {_change_indicator(current.meta_description, suggested.meta_description)}"
    )
    col_old, col_new = st.columns(2)
    with col_old:
        st.markdown(f"**Aktuell** {_char_count_badge(current.meta_description, _DESC_MAX)}")
        st.code(current.meta_description or "(leer)")
    with col_new:
        new_desc = st.text_area(
            f"Vorschlag {_char_count_badge(suggested.meta_description, _DESC_MAX)}",
            value=suggested.meta_description,
            max_chars=200,
            height=80,
            key="edit_meta_desc",
        )
        st.markdown(_char_count_badge(new_desc, _DESC_MAX))

    # ================================================================
    # H1
    # ================================================================
    st.markdown("---")
    st.markdown(f"### H1-Überschrift {_change_indicator(current.h1, suggested.h1)}")
    col_old, col_new = st.columns(2)
    with col_old:
        st.markdown("**Aktuell**")
        st.code(current.h1 or "(leer)")
    with col_new:
        new_h1 = st.text_input(
            "Vorschlag",
            value=suggested.h1,
            key="edit_h1",
        )

    # ================================================================
    # H2-Überschriften
    # ================================================================
    old_h2 = current.h2_list or []
    new_h2 = suggested.h2_list or []
    if old_h2 or new_h2:
        st.markdown("---")
        st.markdown("### H2-Überschriften")
        col_old, col_new = st.columns(2)
        with col_old:
            st.markdown("**Aktuell**")
            if old_h2:
                for h2 in old_h2:
                    st.markdown(f"- {h2}")
            else:
                st.caption("(keine)")
        with col_new:
            st.markdown("**Vorschlag**")
            if new_h2:
                for h2 in new_h2:
                    st.markdown(f"- {h2}")
            else:
                st.caption("(keine)")

    # ================================================================
    # Body HTML with Content Preview
    # ================================================================
    st.markdown("---")
    st.markdown(
        f"### Body HTML {_change_indicator(current.body_html, suggested.body_html)}"
    )

    # Content preview tabs
    preview_tab, code_tab = st.tabs(["Vorschau", "HTML-Code bearbeiten"])

    with preview_tab:
        prev_col1, prev_col2 = st.columns(2)
        with prev_col1:
            st.markdown("**Aktuell:**")
            _render_content_preview(current.body_html)
        with prev_col2:
            st.markdown("**Vorschlag:**")
            _render_content_preview(suggested.body_html)

    with code_tab:
        new_body = st.text_area(
            "Body HTML (bearbeitbar)",
            value=suggested.body_html,
            height=400,
            key="edit_body_html",
        )
        # Word count
        from bs4 import BeautifulSoup as BS4
        plain_text = BS4(new_body, "html.parser").get_text(separator=" ", strip=True) if new_body else ""
        word_count = len(plain_text.split())
        st.caption(f"Wörter: {word_count} | HTML-Größe: {len(new_body.encode('utf-8')) / 1024:.1f} KB")

    # ================================================================
    # Bilder – Alt-Texte Vorher / Nachher
    # ================================================================
    all_images = suggested.images or current.images or []
    edited_images: list[ImageSEO] = []
    if all_images:
        st.markdown("---")
        st.markdown(f"### Bilder - Alt-Texte ({len(all_images)} Bilder)")

        current_alt_map: dict[int, str] = {
            img.image_id: img.current_alt for img in (current.images or [])
        }

        for idx, img in enumerate(all_images):
            old_alt = current_alt_map.get(img.image_id, img.current_alt) or ""
            new_alt_suggestion = img.suggested_alt or old_alt
            alt_changed = old_alt != new_alt_suggestion

            with st.container():
                img_col, old_col, new_col = st.columns([1, 3, 3])

                with img_col:
                    if img.image_src:
                        st.image(img.image_src, width=80)
                    else:
                        st.caption(f"Bild #{img.image_id}")

                with old_col:
                    st.markdown("**Aktuell:**")
                    if old_alt:
                        st.code(old_alt)
                    else:
                        st.warning("(leer)")

                with new_col:
                    new_alt = st.text_input(
                        f"Vorschlag (Bild {img.image_id})",
                        value=new_alt_suggestion,
                        key=f"edit_alt_{img.image_id}_{idx}",
                        max_chars=125,
                    )
                    st.markdown(_char_count_badge(new_alt, 125))

                edited_images.append(
                    ImageSEO(
                        image_id=img.image_id,
                        image_src=img.image_src,
                        current_alt=old_alt,
                        suggested_alt=new_alt,
                    )
                )

            if idx < len(all_images) - 1:
                st.divider()

    # Store edited values in session state
    st.session_state["_edited_seo"] = SEOData(
        seo_title=new_title,
        meta_description=new_desc,
        h1=new_h1,
        h2_list=suggested.h2_list,
        body_html=new_body if 'new_body' in dir() else suggested.body_html,
        images=edited_images if edited_images else suggested.images,
    )


def _render_compliance_warnings(warnings: list[ComplianceWarning]) -> None:
    """Show compliance warnings in a red box."""
    if not warnings:
        return
    st.markdown("### Compliance-Warnungen")
    for w in warnings:
        terms = ", ".join(w.found_terms) if w.found_terms else ""
        detail = f" (Begriffe: {terms})" if terms else ""
        st.error(f"**{w.category}:** {w.message}{detail}")


def _render_tab_dashboard() -> None:
    """Render the dashboard / overview tab with key metrics."""
    cfg: AppConfig | None = st.session_state.get("config")
    if not cfg:
        st.info("Bitte zuerst die Konfiguration in der Seitenleiste ausfuellen.")
        return

    st.markdown("### Dashboard")

    # --- Load stats ---
    try:
        backup_store = BackupStore()
        stats = backup_store.get_stats()
    except Exception:
        stats = {
            "total_backups": 0,
            "total_optimized_7d": 0,
            "total_optimized_30d": 0,
            "recent_backups": [],
        }

    # --- Product / Collection / Page counts ---
    count_col1, count_col2, count_col3 = st.columns(3)
    resource_counts: dict[str, int] = {}
    for rt in ResourceType:
        cache_key = f"_items_{rt.value}"
        items = st.session_state.get(cache_key)
        if items is not None:
            resource_counts[rt.value] = len(items)

    with count_col1:
        cnt = resource_counts.get("Produkte", "—")
        st.metric("Produkte", cnt)
    with count_col2:
        cnt = resource_counts.get("Kategorien", "—")
        st.metric("Kategorien", cnt)
    with count_col3:
        cnt = resource_counts.get("Seiten", "—")
        st.metric("Seiten", cnt)

    if not resource_counts:
        st.caption(
            "Produktzahlen werden angezeigt, nachdem du einen Tab mit Shopify-Daten besucht hast."
        )

    st.markdown("---")

    # --- Optimization stats ---
    st.markdown("### Optimierungs-Statistik")
    opt_col1, opt_col2, opt_col3, opt_col4 = st.columns(4)
    with opt_col1:
        st.metric("Optimiert (7 Tage)", stats["total_optimized_7d"])
    with opt_col2:
        st.metric("Optimiert (30 Tage)", stats["total_optimized_30d"])
    with opt_col3:
        st.metric("Backups gesamt", stats["total_backups"])
    with opt_col4:
        # Average score from last batch if available
        batch_results = st.session_state.get("_batch_results", [])
        if batch_results:
            scores = [r.get("score", 0) for r in batch_results if r.get("score")]
            avg = round(sum(scores) / len(scores)) if scores else "—"
        else:
            avg = "—"
        st.metric("Ø SEO-Score", avg)

    st.markdown("---")

    # --- Recent activity ---
    st.markdown("### Letzte Aenderungen")
    recent = stats["recent_backups"]
    if not recent:
        st.caption("Noch keine Optimierungen durchgeführt.")
    else:
        for entry in recent:
            ts_display = entry.timestamp[:16].replace("T", " ") if entry.timestamp else "?"
            status_icon = "🔄" if entry.rolled_back else "✅"
            resource_label = entry.resource_type or "?"
            st.markdown(
                f"{status_icon} **{ts_display}** — {resource_label} #{entry.resource_id} "
                f"{'(zurückgesetzt)' if entry.rolled_back else ''}"
            )

    st.markdown("---")

    # --- Quick actions ---
    st.markdown("### Schnellzugriff")
    qa_col1, qa_col2, qa_col3 = st.columns(3)
    with qa_col1:
        st.markdown(
            '<div class="info-box info-box-blue" style="text-align:center;">'
            '<strong>SEO-Optimierung</strong><br>'
            '<span style="font-size:0.85rem;">Einzelne Produkte analysieren & optimieren</span>'
            '</div>',
            unsafe_allow_html=True,
        )
    with qa_col2:
        st.markdown(
            '<div class="info-box info-box-green" style="text-align:center;">'
            '<strong>Batch-Analyse</strong><br>'
            '<span style="font-size:0.85rem;">Mehrere Produkte auf einmal optimieren</span>'
            '</div>',
            unsafe_allow_html=True,
        )
    with qa_col3:
        st.markdown(
            '<div class="info-box info-box-orange" style="text-align:center;">'
            '<strong>Google Rankings</strong><br>'
            '<span style="font-size:0.85rem;">Search Console Daten & Trends</span>'
            '</div>',
            unsafe_allow_html=True,
        )


def _render_tab_seo() -> None:
    """Render the SEO optimization tab."""
    cfg: AppConfig | None = st.session_state.get("config")
    if not cfg:
        st.info("Bitte zuerst die Konfiguration in der Seitenleiste ausfüllen.")
        return

    if not st.session_state.get("connection_ok"):
        st.info("Bitte zuerst die Shopify-Verbindung testen (Seitenleiste -> Testen).")
        return

    # --- Resource selection ---
    st.markdown("### Ressource wählen")

    sel_col1, sel_col2, sel_col3, sel_col4 = st.columns([1, 2, 1, 1])

    with sel_col1:
        resource_type_label = st.selectbox(
            "Typ",
            options=[rt.value for rt in ResourceType],
            key="sel_resource_type",
        )
    resource_type = ResourceType(resource_type_label)

    # Load items
    cache_key = f"_items_{resource_type.value}"
    if cache_key not in st.session_state:
        with st.spinner("Lade Ressourcen..."):
            st.session_state[cache_key] = _load_items(resource_type)

    items_list: list[dict] = st.session_state[cache_key]

    if not items_list:
        st.info("Keine Ressourcen gefunden oder Verbindung fehlgeschlagen.")
        if st.button("Neu laden", key="reload_items"):
            st.session_state.pop(cache_key, None)
            st.rerun()
        return

    with sel_col2:
        # Search filter for items
        search_query = st.text_input(
            "Suche", placeholder="Produkt suchen...", key="item_search",
        )

    with sel_col3:
        seo_status_filter = st.selectbox(
            "Status",
            options=[
                "Alle",
                "Nicht optimiert",
                "Optimiert (3 Tage)",
                "Optimiert (7 Tage)",
                "Optimiert (30 Tage)",
                "Nicht optimiert (3+ Tage)",
                "Nicht optimiert (7+ Tage)",
            ],
            key="seo_status_filter",
            help="Filtere nach Optimierungs-Status",
        )

    with sel_col4:
        stock_options = ["Alle", "Auf Lager", "Ausverkauft"]
        if resource_type == ResourceType.PRODUCT:
            stock_filter = st.selectbox(
                "Lager",
                options=stock_options,
                key="seo_stock_filter",
                help="Filtere nach Lagerbestand",
            )
        else:
            stock_filter = "Alle"
            st.selectbox("Lager", options=["—"], key="seo_stock_na", disabled=True)

    # Pre-load optimization data for status filter
    _seo_opt_map: dict[int, str] = {}
    if seo_status_filter != "Alle":
        _bs_filter = BackupStore()
        if "3 Tage" in seo_status_filter:
            _seo_opt_map = _bs_filter.get_optimized_resource_ids(since_days=3)
        elif "7 Tage" in seo_status_filter or "7+" in seo_status_filter:
            _seo_opt_map = _bs_filter.get_optimized_resource_ids(since_days=7)
        elif "30 Tage" in seo_status_filter:
            _seo_opt_map = _bs_filter.get_optimized_resource_ids(since_days=30)

    # Filter items based on search
    if search_query:
        filtered_items = [
            item for item in items_list
            if search_query.lower() in item["title"].lower()
            or search_query.lower() in item["handle"].lower()
        ]
    else:
        filtered_items = items_list

    # Apply status filter
    if seo_status_filter == "Nicht optimiert":
        # Never optimized (check all time)
        _all_opt = BackupStore().get_optimized_resource_ids(since_days=9999)
        filtered_items = [it for it in filtered_items if it["id"] not in _all_opt]
    elif seo_status_filter == "Nicht optimiert (3+ Tage)":
        filtered_items = [it for it in filtered_items if it["id"] not in _seo_opt_map]
    elif seo_status_filter == "Nicht optimiert (7+ Tage)":
        filtered_items = [it for it in filtered_items if it["id"] not in _seo_opt_map]
    elif "Optimiert" in seo_status_filter and "Nicht" not in seo_status_filter:
        filtered_items = [it for it in filtered_items if it["id"] in _seo_opt_map]

    # Apply stock filter (only for products)
    if stock_filter == "Auf Lager":
        filtered_items = [it for it in filtered_items if it.get("total_inventory", 0) > 0]
    elif stock_filter == "Ausverkauft":
        filtered_items = [it for it in filtered_items if it.get("total_inventory", 0) <= 0]

    if not filtered_items:
        st.warning(f"Keine Ergebnisse für '{search_query}'.")
        return

    item_labels = [f"{item['title']} ({item['handle']})" for item in filtered_items]
    selected_idx = st.selectbox(
        f"Ressource ({len(filtered_items)} von {len(items_list)})",
        options=range(len(item_labels)),
        format_func=lambda i: item_labels[i],
        key="sel_item_idx",
    )
    selected_item = filtered_items[selected_idx]

    # --- Live link to the page ---
    storefront_url = cfg.get_storefront_url()
    handle = selected_item.get("handle", "")
    if handle and storefront_url:
        if resource_type == ResourceType.PRODUCT:
            live_url = f"{storefront_url}/products/{handle}"
        elif resource_type == ResourceType.COLLECTION:
            live_url = f"{storefront_url}/collections/{handle}"
        else:
            live_url = f"{storefront_url}/pages/{handle}"
        st.markdown(
            f'<a href="{live_url}" target="_blank" style="'
            f'display:inline-block;margin:6px 0 10px;padding:4px 12px;'
            f'border-radius:6px;font-size:13px;text-decoration:none;'
            f'background:rgba(0,122,255,0.1);color:#007AFF;'
            f'border:1px solid rgba(0,122,255,0.2);">'
            f'🔗 {live_url}</a>',
            unsafe_allow_html=True,
        )

    # --- Optimization history for selected item ---
    try:
        _bs = BackupStore()
        item_backups = _bs.list_backups(resource_id=selected_item["id"], limit=5)
        if item_backups:
            with st.expander(f"Optimierungs-Verlauf ({len(item_backups)} letzte)", expanded=False):
                for bk in item_backups:
                    ts = bk.timestamp[:16].replace("T", " ") if bk.timestamp else "?"
                    status = "🔄 Zurückgesetzt" if bk.rolled_back else "✅ Live"
                    changes_summary = ""
                    if bk.before_state and bk.after_state:
                        changed_fields = []
                        for field in ["seo_title", "meta_description", "h1", "body_html"]:
                            if bk.before_state.get(field, "") != bk.after_state.get(field, ""):
                                changed_fields.append(field.replace("_", " ").title())
                        if changed_fields:
                            changes_summary = f" — {', '.join(changed_fields)}"
                    st.markdown(f"**{ts}** {status}{changes_summary}")
    except Exception:
        pass  # Don't break UI if backup store fails

    # Action buttons
    btn_col1, btn_col2 = st.columns([1, 1])
    with btn_col1:
        analyze_clicked = st.button("SEO analysieren", type="primary", use_container_width=True, key="btn_analyze")
    with btn_col2:
        if st.button("Aktualisieren", use_container_width=True, key="btn_reload"):
            st.session_state.pop(cache_key, None)
            st.rerun()

    # --- Analyse ---
    if analyze_clicked:
        with st.spinner("Analysiere Seite..."):
            try:
                client = ShopifyClient(cfg)

                # Load full resource
                if resource_type == ResourceType.PRODUCT:
                    full = client.get_product(selected_item["id"])
                elif resource_type == ResourceType.COLLECTION:
                    full = client.get_collection(
                        selected_item["id"],
                        selected_item.get("collection_type", "custom"),
                    )
                else:
                    full = client.get_page(selected_item["id"])

                st.session_state["full_resource"] = full

                # SEO analysis
                analyzer = SEOAnalyzer(cfg.get_storefront_url())
                analysis = analyzer.analyze_page(
                    selected_item["handle"], resource_type.value
                )

                # Keyword research
                from keyword_research import research_keywords

                product_name = selected_item.get("title", full.title)
                brand = ""
                category = ""
                tags = ""
                if resource_type == ResourceType.PRODUCT and isinstance(full, ShopifyProduct):
                    brand = full.vendor or ""
                    category = full.product_type or ""
                    tags = full.tags or ""

                kw_progress = st.progress(0, text="Recherchiere Keywords bei Google…")

                def _kw_progress_cb(pct: float, msg: str) -> None:
                    kw_progress.progress(min(pct, 1.0), text=msg)

                kw_research = research_keywords(
                    product_name=product_name,
                    brand=brand,
                    category=category,
                    tags=tags,
                    progress_callback=_kw_progress_cb,
                )
                kw_progress.empty()
                analysis.suggested_keywords = kw_research
                st.session_state["seo_analysis"] = analysis

                # Ranking data
                ranking_data: list[RankingData] = []
                if st.session_state.get("gsc_connected"):
                    tracker = RankingTracker(
                        site_url=cfg.get_storefront_url(),
                        credentials_path=cfg.google_credentials_path,
                    )
                    ok, _ = tracker.connect()
                    if ok:
                        page_url = _build_page_url(
                            cfg, resource_type, selected_item["handle"]
                        )
                        ranking_data = tracker.get_top_keywords(page_url)
                st.session_state["ranking_data"] = ranking_data

                # Clear previous suggestions
                st.session_state.pop("seo_comparison", None)
                st.session_state.pop("compliance_warnings", None)
                st.session_state.pop("sanitizer_warnings", None)
                st.session_state.pop("_edited_seo", None)

            except Exception as exc:
                st.error(f"Fehler bei der Analyse: {exc}")

    # --- Show analysis results ---
    analysis: SEOAnalysis | None = st.session_state.get("seo_analysis")
    if analysis:
        st.markdown("---")
        st.markdown("## SEO-Analyse")
        _render_seo_analysis(analysis)

    # Ranking section
    ranking_data: list[RankingData] | None = st.session_state.get("ranking_data")
    if ranking_data:
        st.markdown("---")
        _render_ranking_section(
            ranking_data, cfg, resource_type, selected_item["handle"]
        )

    # --- Optimize button ---
    full_resource = st.session_state.get("full_resource")
    if full_resource and analysis:
        st.markdown("---")

        # Show status from previous run
        if st.session_state.get("seo_comparison"):
            st.success("SEO-Vorschläge wurden generiert - siehe Dashboard unten")

        if st.button("SEO optimieren", type="primary", use_container_width=True, key="btn_optimize"):
            progress = st.progress(0, text="Starte KI-Optimierung...")
            try:
                progress.progress(10, text="KI-Engine wird vorbereitet...")
                engine = SEOEngine(
                    api_key=cfg.anthropic_api_key,
                    provider=st.session_state.get("ai_provider", "anthropic"),
                    model_id=st.session_state.get("ai_model_id", ""),
                )
                st.caption(f"Provider: {engine.provider} | Modell: {engine.model}")
                current_seo = full_resource.to_seo_data()

                extra_context: dict = {}
                if resource_type == ResourceType.PRODUCT and isinstance(
                    full_resource, ShopifyProduct
                ):
                    extra_context = {
                        "vendor": full_resource.vendor,
                        "product_type": full_resource.product_type,
                        "tags": full_resource.tags,
                    }
                elif resource_type == ResourceType.COLLECTION and isinstance(
                    full_resource, ShopifyCollection
                ):
                    extra_context = {
                        "collection_type": full_resource.collection_type,
                    }

                progress.progress(20, text="KI generiert SEO-Vorschläge... (30-90 Sek.)")
                suggested = engine.generate_seo_suggestions(
                    resource_type=resource_type,
                    current_data=current_seo,
                    title=full_resource.title,
                    analysis=analysis,
                    ranking_data=ranking_data,
                    extra_context=extra_context,
                )

                title_len = len(suggested.seo_title)
                desc_len = len(suggested.meta_description)
                progress.progress(70, text=f"Titel: {title_len}/60 | Meta: {desc_len}/160")

                # Compliance check
                all_text = " ".join([
                    suggested.seo_title,
                    suggested.meta_description,
                    suggested.body_html,
                ])
                is_nicotine = resource_type == ResourceType.PRODUCT
                compliance_warnings = engine.check_compliance(
                    all_text, is_nicotine_product=is_nicotine
                )
                st.session_state["compliance_warnings"] = compliance_warnings
                progress.progress(80, text="Compliance-Check abgeschlossen...")

                # HTML sanitizer
                san_warnings: list[str] = []
                try:
                    sanitizer = HTMLSanitizer()
                    sanitized_html, san_warnings = sanitizer.full_check(
                        suggested.body_html, current_seo.body_html
                    )
                    suggested.body_html = sanitized_html
                except Exception as san_exc:
                    san_warnings = [f"HTML-Sanitizer fehlgeschlagen: {san_exc}"]
                st.session_state["sanitizer_warnings"] = san_warnings
                progress.progress(90, text="HTML bereinigt...")

                # Build comparison
                comparison = SEOComparison(
                    resource_type=resource_type,
                    resource_id=full_resource.id,
                    resource_title=full_resource.title,
                    current=current_seo,
                    suggested=suggested,
                    analysis=analysis,
                )
                st.session_state["seo_comparison"] = comparison
                st.session_state["_optimize_done"] = True
                progress.progress(100, text="Fertig!")

            except Exception as exc:
                import traceback
                progress.empty()
                st.error(f"Fehler bei der KI-Optimierung: {exc}")
                st.code(traceback.format_exc(), language="text")

        # Rerun to show dashboard
        if st.session_state.pop("_optimize_done", False):
            st.rerun()

    # --- Show comparison dashboard ---
    comparison: SEOComparison | None = st.session_state.get("seo_comparison")
    if comparison:
        st.markdown("---")
        st.markdown("## SEO-Dashboard — Vorschau der Änderungen")
        st.markdown(
            '<div class="info-box info-box-orange">'
            '<span style="font-size:1.1rem;">&#9888;&#65039;</span> '
            '<strong>Noch nicht live</strong> — Das sind nur KI-Vorschläge. '
            'Dein Shop wurde noch nicht verändert. Prüfe die Vorschläge und klicke unten auf '
            '<strong>In Shopify übernehmen</strong> um sie live zu schalten.'
            '</div>',
            unsafe_allow_html=True,
        )
        try:
            _render_comparison_dashboard(comparison)
        except Exception as dash_exc:
            import traceback
            st.error(f"Fehler beim Dashboard: {dash_exc}")
            st.code(traceback.format_exc(), language="text")

        # Compliance warnings
        cw = st.session_state.get("compliance_warnings", [])
        if cw:
            _render_compliance_warnings(cw)

        # Sanitizer warnings
        sw = st.session_state.get("sanitizer_warnings", [])
        if sw:
            st.markdown("### HTML-Sanitizer-Warnungen")
            for w in sw:
                st.warning(w)

        # --- Publish section ---
        st.markdown("---")
        st.markdown("## Jetzt live schalten")
        st.markdown(
            '<div class="info-box info-box-blue">'
            'Prüfe die Vorschläge oben und passe sie bei Bedarf an. '
            'Erst wenn du auf <strong>In Shopify übernehmen</strong> klickst, '
            'werden die Änderungen in deinem Shop sichtbar. '
            'Vorher wird automatisch ein <strong>Backup</strong> erstellt.'
            '</div>',
            unsafe_allow_html=True,
        )

        edited_seo: SEOData | None = st.session_state.get("_edited_seo")
        if edited_seo:
            field_changes = 0
            if edited_seo.seo_title != comparison.current.seo_title:
                field_changes += 1
            if edited_seo.meta_description != comparison.current.meta_description:
                field_changes += 1
            if edited_seo.h1 != comparison.current.h1:
                field_changes += 1
            if edited_seo.body_html != comparison.current.body_html:
                field_changes += 1

            image_changes = 0
            for img in edited_seo.images:
                if img.suggested_alt and img.suggested_alt != img.current_alt:
                    image_changes += 1

            pub_col1, pub_col2 = st.columns(2)
            with pub_col1:
                st.metric("Felder geändert", field_changes)
            with pub_col2:
                st.metric("Bilder geändert", image_changes)

            confirm = st.checkbox("Ich bestätige die Änderungen und möchte sie live schalten", key="confirm_publish")

            if st.button(
                "In Shopify übernehmen",
                type="primary",
                disabled=not confirm,
                use_container_width=True,
                key="btn_publish",
            ):
                if st.session_state.get("write_lock"):
                    st.warning("Ein Schreibvorgang läuft bereits.")
                    return

                st.session_state["write_lock"] = True
                try:
                    # Final HTML sanitizer check
                    sanitizer = HTMLSanitizer()
                    final_html, final_warnings = sanitizer.full_check(
                        edited_seo.body_html, comparison.current.body_html
                    )
                    edited_seo.body_html = final_html

                    if final_warnings:
                        for fw in final_warnings:
                            st.warning(fw)

                    # Create backup
                    backup_store = BackupStore()
                    before_state = comparison.current.model_dump()
                    if resource_type == ResourceType.COLLECTION and isinstance(
                        full_resource, ShopifyCollection
                    ):
                        before_state["collection_type"] = full_resource.collection_type
                    backup_id = backup_store.create_backup(
                        resource_type=comparison.resource_type.value,
                        resource_id=comparison.resource_id,
                        before_state=before_state,
                    )

                    # Auto-cleanup old backups
                    cleaned = backup_store.cleanup_old_backups(max_age_days=90)
                    if cleaned > 0:
                        logging.info("Alte Backups bereinigt: %d Einträge gelöscht", cleaned)

                    # Update in Shopify
                    client = ShopifyClient(cfg)
                    updated_at = (
                        full_resource.updated_at
                        if hasattr(full_resource, "updated_at")
                        else ""
                    )

                    with st.spinner("Schreibe Änderungen nach Shopify..."):
                        if resource_type == ResourceType.PRODUCT:
                            client.update_product(
                                comparison.resource_id,
                                edited_seo,
                                original_updated_at=updated_at,
                            )
                        elif resource_type == ResourceType.COLLECTION:
                            ctype = ""
                            if isinstance(full_resource, ShopifyCollection):
                                ctype = full_resource.collection_type
                            client.update_collection(
                                comparison.resource_id,
                                ctype,
                                edited_seo,
                                original_updated_at=updated_at,
                            )
                        else:
                            client.update_page(
                                comparison.resource_id,
                                edited_seo,
                                original_updated_at=updated_at,
                            )

                    # Update backup with after state
                    after_state = edited_seo.model_dump()
                    backup_store.update_after_state(backup_id, after_state)

                    st.markdown(
                        '<div class="success-box">'
                        '<span style="font-size:1.5rem;">&#9989;</span><br>'
                        '<strong style="font-size:1.1rem;">Live geschaltet!</strong><br>'
                        '<span style="opacity:0.7;font-size:0.85rem;">'
                        f'Änderungen wurden in Shopify übernommen. Backup-ID: {backup_id}'
                        '</span></div>',
                        unsafe_allow_html=True,
                    )

                    # Clear stale data
                    st.session_state.pop("seo_comparison", None)
                    st.session_state.pop("seo_analysis", None)
                    st.session_state.pop("full_resource", None)
                    st.session_state.pop("_edited_seo", None)

                except Exception as exc:
                    st.error(f"Fehler beim Schreiben: {exc}")
                finally:
                    st.session_state["write_lock"] = False


# ---------------------------------------------------------------------------
# Tab 2 — Batch-Analyse
# ---------------------------------------------------------------------------


def _render_tab_batch() -> None:
    """Render the batch SEO analysis & bulk optimization tab."""
    cfg: AppConfig | None = st.session_state.get("config")
    if not cfg:
        st.info("Bitte zuerst die Konfiguration in der Seitenleiste ausfüllen.")
        return

    if not st.session_state.get("connection_ok"):
        st.info("Bitte zuerst die Shopify-Verbindung testen.")
        return

    # --- Smart Review Queue (takes over the tab when active) ---
    smart_phase = st.session_state.get("_smart_queue_phase")
    if smart_phase in ("review", "summary"):
        _render_smart_review(cfg)
        return

    st.markdown("### Batch-Analyse & Bulk-Optimierung")
    st.caption(
        "Analysiere und optimiere mehrere Produkte gleichzeitig per KI. "
        "Wähle Produkte per Checkbox aus und nutze 'Ausgewählte optimieren' für die Freigabe-Queue."
    )

    # --- Show bulk optimization results first (always visible) ---
    _render_bulk_results(cfg)

    # --- Settings row ---
    batch_col1, batch_col2, batch_col3, batch_col3b, batch_col4 = st.columns([1, 2, 1, 1, 1])

    with batch_col1:
        resource_type_label = st.selectbox(
            "Ressourcentyp",
            options=[rt.value for rt in ResourceType],
            key="batch_resource_type",
        )
    resource_type = ResourceType(resource_type_label)

    # Load items
    cache_key = f"_items_{resource_type.value}"
    if cache_key not in st.session_state:
        with st.spinner("Lade Ressourcen..."):
            st.session_state[cache_key] = _load_items(resource_type)

    items_list: list[dict] = st.session_state.get(cache_key, [])

    if not items_list:
        st.info("Keine Ressourcen gefunden.")
        return

    with batch_col2:
        batch_filter = st.text_input(
            "Produktfilter",
            placeholder="z.B. 'elfbar elfa' oder 'watermelon'...",
            key="batch_filter",
            help="Filtere nach Name oder Handle. Mehrere Begriffe mit Leerzeichen trennen (alle müssen enthalten sein).",
        )

    with batch_col3:
        status_filter = st.selectbox(
            "Status",
            options=[
                "Alle",
                "Nicht optimiert",
                "Optimiert (3 Tage)",
                "Optimiert (7 Tage)",
                "Optimiert (30 Tage)",
                "Nicht optimiert (3+ Tage)",
                "Nicht optimiert (7+ Tage)",
            ],
            key="batch_status_filter",
            help="Filtere nach Optimierungs-Status",
        )

    with batch_col3b:
        batch_stock_options = ["Alle", "Auf Lager", "Ausverkauft"]
        if resource_type == ResourceType.PRODUCT:
            batch_stock_filter = st.selectbox(
                "Lager",
                options=batch_stock_options,
                key="batch_stock_filter",
                help="Filtere nach Lagerbestand",
            )
        else:
            batch_stock_filter = "Alle"
            st.selectbox("Lager", options=["—"], key="batch_stock_na", disabled=True)

    # Pre-load optimization history for status filter
    _status_opt_map: dict[int, str] = {}
    if status_filter != "Alle":
        _bs = BackupStore()
        if "3 Tage" in status_filter:
            _status_opt_map = _bs.get_optimized_resource_ids(since_days=3)
        elif "7 Tage" in status_filter or "7+" in status_filter:
            _status_opt_map = _bs.get_optimized_resource_ids(since_days=7)
        elif "30 Tage" in status_filter:
            _status_opt_map = _bs.get_optimized_resource_ids(since_days=30)

    # Filter items
    if batch_filter:
        filter_terms = batch_filter.lower().split()
        filtered_items = [
            item for item in items_list
            if all(
                term in item["title"].lower() or term in item["handle"].lower()
                for term in filter_terms
            )
        ]
    else:
        filtered_items = items_list

    # Apply status filter
    if status_filter == "Nicht optimiert":
        _all_opt = BackupStore().get_optimized_resource_ids(since_days=9999)
        filtered_items = [it for it in filtered_items if it["id"] not in _all_opt]
    elif "Nicht optimiert" in status_filter and "+" in status_filter:
        filtered_items = [it for it in filtered_items if it["id"] not in _status_opt_map]
    elif "Optimiert" in status_filter and "Nicht" not in status_filter:
        filtered_items = [it for it in filtered_items if it["id"] in _status_opt_map]

    # Apply stock filter (only for products)
    if batch_stock_filter == "Auf Lager":
        filtered_items = [it for it in filtered_items if it.get("total_inventory", 0) > 0]
    elif batch_stock_filter == "Ausverkauft":
        filtered_items = [it for it in filtered_items if it.get("total_inventory", 0) <= 0]

    with batch_col4:
        st.metric("Gefiltert", f"{len(filtered_items)} / {len(items_list)}")

    if not filtered_items:
        st.warning(f"Keine Produkte gefunden für '{batch_filter}'.")
        return

    # --- Optimization history: mark already-optimized products ---
    skip_col1, skip_col2 = st.columns([2, 1])

    with skip_col1:
        skip_days = st.selectbox(
            "Bereits optimierte überspringen",
            options=[0, 1, 3, 7, 14, 30],
            index=2,
            format_func=lambda d: "Nicht überspringen" if d == 0 else f"Optimiert in den letzten {d} Tagen",
            key="batch_skip_days",
            help="Produkte die kürzlich per KI optimiert wurden, können übersprungen werden.",
        )

    # Load optimization history from backup DB
    optimized_map: dict[int, str] = {}
    skipped_count = 0
    if skip_days > 0:
        backup_store = BackupStore()
        optimized_map = backup_store.get_optimized_resource_ids(since_days=skip_days)

    # Mark items with optimization status
    display_items: list[dict] = []
    for item in filtered_items:
        item_copy = dict(item)
        last_opt = optimized_map.get(item["id"])
        if last_opt:
            item_copy["_last_optimized"] = last_opt
            if skip_days > 0:
                skipped_count += 1
        else:
            item_copy["_last_optimized"] = None
        display_items.append(item_copy)

    # Items to actually process (excluding already-optimized if skip is on)
    if skip_days > 0:
        pending_items = [it for it in display_items if it["_last_optimized"] is None]
    else:
        pending_items = display_items

    with skip_col2:
        if skip_days > 0 and skipped_count > 0:
            st.metric("Übersprungen", skipped_count, help="Bereits kürzlich optimiert")
        else:
            st.metric("Zu verarbeiten", len(pending_items))

    # Show filtered product list with checkboxes for selection
    _MAX_SELECTION = 50
    # Count currently selected across ALL display_items
    _all_selected_ids = {
        item["id"] for item in display_items
        if st.session_state.get(f"smart_sel_{item['id']}", False)
    }

    with st.expander(
        f"Produkte auswählen — {len(_all_selected_ids)}/{_MAX_SELECTION} ausgewählt ({len(display_items)} verfügbar)",
        expanded=False,
    ):
        # Search within product list
        pick_search = st.text_input(
            "Produkt suchen",
            placeholder="Name eingeben um zu filtern...",
            key="smart_pick_search",
        )
        if pick_search:
            pick_filtered = [
                it for it in display_items
                if pick_search.lower() in it["title"].lower()
                or pick_search.lower() in it.get("handle", "").lower()
            ]
        else:
            pick_filtered = display_items

        # Pagination
        _PAGE_SIZE = 30
        total_pages = max(1, (len(pick_filtered) + _PAGE_SIZE - 1) // _PAGE_SIZE)
        page_col1, page_col2, page_col3 = st.columns([1, 2, 1])
        with page_col1:
            current_page = st.number_input(
                "Seite", min_value=1, max_value=total_pages,
                value=1, key="smart_pick_page",
            )
        with page_col2:
            st.caption(f"Seite {current_page} von {total_pages} ({len(pick_filtered)} Produkte)")
        with page_col3:
            pass

        # Select all on page / none buttons
        page_start = (current_page - 1) * _PAGE_SIZE
        page_items = pick_filtered[page_start : page_start + _PAGE_SIZE]

        btn_col1, btn_col2 = st.columns([1, 1])
        with btn_col1:
            if st.button(
                f"Seite auswählen ({len(page_items)})",
                key="smart_select_page",
                use_container_width=True,
            ):
                added = 0
                for item in page_items:
                    if len(_all_selected_ids) + added >= _MAX_SELECTION:
                        break
                    if item["id"] not in _all_selected_ids:
                        st.session_state[f"smart_sel_{item['id']}"] = True
                        added += 1
                    else:
                        st.session_state[f"smart_sel_{item['id']}"] = True
                if added == 0 and len(_all_selected_ids) >= _MAX_SELECTION:
                    st.toast(f"Maximum von {_MAX_SELECTION} Produkten erreicht!", icon="⚠️")
                st.rerun()
        with btn_col2:
            if st.button("Alle abwählen", key="smart_select_none", use_container_width=True):
                for item in display_items:
                    st.session_state[f"smart_sel_{item['id']}"] = False
                st.rerun()

        if len(_all_selected_ids) >= _MAX_SELECTION:
            st.warning(f"Maximum von {_MAX_SELECTION} Produkten erreicht. Wähle zuerst andere ab.")

        st.divider()
        for item in page_items:
            last_opt = item.get("_last_optimized")
            if last_opt:
                try:
                    ts = last_opt[:10]
                except Exception:
                    ts = "kürzlich"
                label = f"{item['title']}  ·  optimiert: {ts}"
            else:
                label = item["title"]
            item_id = item["id"]
            is_selected = st.session_state.get(f"smart_sel_{item_id}", False)
            at_limit = len(_all_selected_ids) >= _MAX_SELECTION and not is_selected
            st.checkbox(
                label,
                key=f"smart_sel_{item_id}",
                disabled=at_limit,
            )

    # Count selected items (from ALL display_items, not just current page)
    selected_ids = {
        item["id"] for item in display_items
        if st.session_state.get(f"smart_sel_{item['id']}", False)
    }
    selected_items = [it for it in display_items if it["id"] in selected_ids]
    if selected_ids:
        st.caption(f"**{len(selected_ids)}** Produkt(e) ausgewählt (max. {_MAX_SELECTION})")

    if not pending_items:
        st.success(
            f"Alle {len(filtered_items)} gefilterten Produkte wurden bereits in den letzten "
            f"{skip_days} Tagen optimiert! Setze den Filter auf 'Nicht überspringen' um sie erneut zu verarbeiten."
        )
        return

    # --- Max items slider ---
    max_items = st.slider(
        f"Anzahl verarbeiten (von {len(pending_items)} ausstehenden)",
        min_value=1,
        max_value=min(len(pending_items), 50),
        value=min(len(pending_items), 10),
        key="batch_count",
    )

    # --- Action buttons ---
    action_col1, action_col2, action_col3 = st.columns(3)

    with action_col1:
        analyze_clicked = st.button(
            "Alle analysieren",
            type="secondary",
            use_container_width=True,
            key="btn_batch_start",
        )

    with action_col2:
        optimize_clicked = st.button(
            "Alle optimieren (KI)",
            type="secondary",
            use_container_width=True,
            key="btn_bulk_optimize",
            help="Analysiert UND optimiert alle gefilterten Produkte automatisch per KI",
        )

    with action_col3:
        smart_count = len(selected_ids) if 'selected_ids' in dir() else 0
        smart_clicked = st.button(
            f"Ausgewählte optimieren ({smart_count})",
            type="primary",
            use_container_width=True,
            disabled=smart_count == 0,
            key="btn_smart_optimize",
            help="Optimiert nur die ausgewählten Produkte und zeigt eine Freigabe-Queue",
        )

    # --- Batch Analysis (score only) ---
    if analyze_clicked:
        analyzer = SEOAnalyzer(cfg.get_storefront_url())
        results: list[dict] = []
        progress = st.progress(0, text="Starte Batch-Analyse...")

        for idx, item in enumerate(pending_items[:max_items]):
            progress.progress(
                (idx + 1) / max_items,
                text=f"Analysiere {idx + 1}/{max_items}: {item['title'][:40]}...",
            )
            try:
                analysis = analyzer.analyze_page(item["handle"], resource_type.value)
                results.append({
                    "Titel": item["title"],
                    "Handle": item["handle"],
                    "Score": analysis.score,
                    "Kritisch": len([i for i in analysis.issues if i.severity == "critical"]),
                    "Warnungen": len(analysis.warnings),
                    "Wörter": analysis.word_count,
                    "Bilder ohne Alt": analysis.missing_alt_images,
                    "H1": "Ja" if analysis.has_h1 else "Nein",
                    "Schema": "Ja" if analysis.has_schema else "Nein",
                    "TPD2": "Ja" if analysis.has_health_warning else "Nein",
                })
            except Exception:
                results.append({
                    "Titel": item["title"],
                    "Handle": item["handle"],
                    "Score": 0,
                    "Kritisch": 0,
                    "Warnungen": 0,
                    "Wörter": 0,
                    "Bilder ohne Alt": 0,
                    "H1": "?",
                    "Schema": "?",
                    "TPD2": "?",
                })

        progress.empty()
        st.session_state["_batch_results"] = results

    # --- Bulk KI-Optimization ---
    if optimize_clicked:
        _run_bulk_optimization(cfg, resource_type, pending_items[:max_items])

    # --- Smart Optimization (selected products only) ---
    if smart_clicked and selected_items:
        _run_smart_optimization(cfg, resource_type, selected_items)

    # --- Display batch results ---
    batch_results: list[dict] = st.session_state.get("_batch_results", [])
    if batch_results:
        st.markdown("---")
        st.markdown("### Analyse-Ergebnisse")

        df = pd.DataFrame(batch_results)

        avg_score = df["Score"].mean()
        worst_count = len(df[df["Score"] < 50])
        no_h1 = len(df[df["H1"] == "Nein"])
        no_tpd2 = len(df[df["TPD2"] == "Nein"])

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Durchschnitt Score", f"{avg_score:.0f}/100")
        m2.metric("Score < 50", worst_count, help="Dringend optimieren")
        m3.metric("Ohne H1", no_h1)
        m4.metric("Ohne TPD2", no_tpd2)

        sort_col = st.selectbox(
            "Sortieren nach",
            options=["Score", "Kritisch", "Warnungen", "Wörter"],
            key="batch_sort",
        )
        ascending = sort_col == "Score"
        df_sorted = df.sort_values(sort_col, ascending=ascending)

        st.dataframe(
            df_sorted,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Score": st.column_config.ProgressColumn(
                    "Score",
                    min_value=0,
                    max_value=100,
                    format="%d",
                ),
            },
        )

        csv = df_sorted.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Als CSV exportieren",
            data=csv,
            file_name=f"seo_batch_{resource_type_label}.csv",
            mime="text/csv",
            key="btn_batch_export",
        )

    # (Bulk results are displayed at the top of the tab via _render_bulk_results)


def _render_duplicate_check(items: list[dict]) -> None:
    """Check for duplicate/near-duplicate SEO titles and meta descriptions."""
    from difflib import SequenceMatcher

    # Collect titles and metas from batch results
    titles: list[tuple[str, str]] = []  # (title, product_name)
    metas: list[tuple[str, str]] = []

    for item in items:
        seo = item.get("suggested_seo") or item.get("current_seo")
        if not seo:
            continue
        name = item.get("title", "?")
        if seo.get("seo_title"):
            titles.append((seo["seo_title"], name))
        if seo.get("meta_description"):
            metas.append((seo["meta_description"], name))

    # Find duplicates
    THRESHOLD = 0.85
    title_dupes: list[tuple[str, str, float]] = []
    meta_dupes: list[tuple[str, str, float]] = []

    for i in range(len(titles)):
        for j in range(i + 1, len(titles)):
            ratio = SequenceMatcher(None, titles[i][0].lower(), titles[j][0].lower()).ratio()
            if ratio >= THRESHOLD:
                title_dupes.append((titles[i][1], titles[j][1], ratio))

    for i in range(len(metas)):
        for j in range(i + 1, len(metas)):
            ratio = SequenceMatcher(None, metas[i][0].lower(), metas[j][0].lower()).ratio()
            if ratio >= THRESHOLD:
                meta_dupes.append((metas[i][1], metas[j][1], ratio))

    if not title_dupes and not meta_dupes:
        return

    with st.expander(
        f"⚠️ Duplikat-Check: {len(title_dupes)} Titel + {len(meta_dupes)} Meta zu ähnlich",
        expanded=False,
    ):
        st.caption(
            "Google bestraft doppelte Meta-Inhalte. "
            "Produkte mit >85% Ähnlichkeit sollten unterschiedlichere Texte bekommen."
        )
        if title_dupes:
            st.markdown("**Ähnliche SEO-Titel:**")
            for p1, p2, ratio in title_dupes[:10]:
                pct = int(ratio * 100)
                st.markdown(f"- **{p1}** ↔ **{p2}** — {pct}% ähnlich")
        if meta_dupes:
            st.markdown("**Ähnliche Meta-Beschreibungen:**")
            for p1, p2, ratio in meta_dupes[:10]:
                pct = int(ratio * 100)
                st.markdown(f"- **{p1}** ↔ **{p2}** — {pct}% ähnlich")


def _render_bulk_results(cfg: AppConfig) -> None:
    """Render bulk optimization results with publish buttons — always visible."""
    bulk_results: list[dict] = st.session_state.get("_bulk_results", [])
    if not bulk_results:
        return

    st.markdown("---")
    st.markdown("### Bulk-Optimierungs-Ergebnisse")

    success_count = sum(1 for r in bulk_results if r["status"] == "optimiert")
    published_count = sum(1 for r in bulk_results if r["status"] == "veröffentlicht")
    error_count = sum(1 for r in bulk_results if r["status"] == "fehler")
    publishable_count = success_count

    # --- Duplicate check ---
    _render_duplicate_check(bulk_results)

    # --- Metrics ---
    r1, r2, r3 = st.columns(3)
    r1.metric("🟡 Nur Vorschlag", success_count, help="KI-Vorschläge generiert, NICHT live")
    r2.metric("✅ Live geschaltet", published_count, help="Direkt in Shopify geschrieben")
    r3.metric("❌ Fehler", error_count)

    # --- Mode banner + Bulk publish action ---
    if published_count > 0 and publishable_count == 0:
        st.success(
            f"✅ **Alle {published_count} Produkt(e) sind live** — "
            f"Änderungen wurden in Shopify geschrieben. Backups wurden erstellt."
        )
    elif publishable_count > 0:
        st.warning(
            f"🟡 **{publishable_count} Produkt(e) warten auf Freigabe** — "
            f"Die KI-Vorschläge wurden generiert, aber noch **nicht** in Shopify übernommen."
        )

        # === BULK PUBLISH ALL BUTTON ===
        st.markdown(
            '<div class="publish-box">'
            '<strong style="font-size:1.05rem;">Alle Vorschläge freigeben</strong><br>'
            '<span style="font-size:0.9rem;opacity:0.8;">Alle optimierten Produkte werden '
            'in Shopify übernommen. Für jedes Produkt wird vorher ein Backup erstellt.</span>'
            '</div>',
            unsafe_allow_html=True,
        )
        pub_col1, pub_col2 = st.columns([1, 1])
        with pub_col1:
            confirm_all = st.checkbox(
                f"Ich bestätige: {publishable_count} Produkt(e) live schalten",
                key="confirm_bulk_publish_all",
            )
        with pub_col2:
            if st.button(
                f"✅ Alle {publishable_count} live schalten",
                type="primary",
                disabled=not confirm_all,
                use_container_width=True,
                key="btn_bulk_publish_all",
            ):
                _publish_bulk_items(cfg, bulk_results, publish_all=True)
                st.rerun()

    # --- Per-item list ---
    for idx, result in enumerate(bulk_results):
        status = result["status"]
        icon = {
            "optimiert": "🟡",
            "veröffentlicht": "✅",
            "fehler": "❌",
            "übersprungen": "🔵",
        }.get(status, "⚪")

        status_label = {
            "optimiert": "VORSCHLAG — nicht live",
            "veröffentlicht": "✅ LIVE",
            "fehler": "FEHLER",
            "übersprungen": "ÜBERSPRUNGEN",
        }.get(status, status.upper())

        with st.expander(f"{icon} {result['title']} — {status_label}", expanded=False):
            if result.get("timestamp"):
                st.caption(f"Optimiert am: {result['timestamp']}")

            if status == "veröffentlicht":
                st.markdown("✅ **Live** — Änderungen wurden in Shopify geschrieben.")
                if result.get("backup_id"):
                    st.caption(f"Backup-ID: {result['backup_id']}")

            elif status == "optimiert":
                st.markdown(
                    "🟡 **Nur Vorschlag** — Änderungen wurden noch **nicht** "
                    "in Shopify geschrieben."
                )
                # Detailed before/after comparison
                if result.get("current_seo") and result.get("suggested_seo"):
                    _render_smart_comparison(result["current_seo"], result["suggested_seo"])
                elif result.get("changes"):
                    for key, val in result["changes"].items():
                        st.markdown(f"**{key}:** {val}")

                # === SINGLE ITEM PUBLISH BUTTON ===
                st.markdown("---")
                single_col1, single_col2 = st.columns([1, 1])
                with single_col1:
                    single_confirm = st.checkbox(
                        "Freigeben",
                        key=f"confirm_single_pub_{idx}",
                    )
                with single_col2:
                    if st.button(
                        "✅ Live schalten",
                        type="primary",
                        disabled=not single_confirm,
                        use_container_width=True,
                        key=f"btn_single_pub_{idx}",
                    ):
                        _publish_bulk_items(cfg, bulk_results, publish_index=idx)
                        st.rerun()

            elif status == "fehler":
                if result.get("error"):
                    st.error(result["error"])

            # Show changes for non-optimiert statuses too
            if status != "optimiert" and result.get("changes"):
                for key, val in result["changes"].items():
                    st.markdown(f"**{key}:** {val}")

    # Clear button
    col_clear1, col_clear2 = st.columns([1, 1])
    with col_clear1:
        if st.button("🗑️ Ergebnisse löschen", key="btn_clear_bulk"):
            st.session_state.pop("_bulk_results", None)
            st.rerun()

    st.markdown("---")


def _publish_bulk_items(
    cfg: AppConfig,
    bulk_results: list[dict],
    publish_all: bool = False,
    publish_index: int | None = None,
) -> None:
    """Publish one or all optimized bulk items to Shopify."""
    client = ShopifyClient(cfg)
    backup_store = BackupStore()

    indices = []
    if publish_all:
        indices = [i for i, r in enumerate(bulk_results) if r["status"] == "optimiert"]
    elif publish_index is not None:
        indices = [publish_index]

    if not indices:
        return

    progress = st.progress(0, text="Veröffentliche...")
    total = len(indices)

    for step, idx in enumerate(indices):
        result = bulk_results[idx]
        if result["status"] != "optimiert" or not result.get("suggested_seo"):
            continue

        pct = (step + 1) / total
        progress.progress(pct, text=f"[{step+1}/{total}] {result['title'][:40]}...")

        try:
            suggested = SEOData(**result["suggested_seo"])
            current = SEOData(**result["current_seo"])
            resource_type = ResourceType(result["resource_type"])
            resource_id = result["resource_id"]
            updated_at = result.get("updated_at", "")

            # Create backup
            before_state = current.model_dump()
            if result.get("collection_type"):
                before_state["collection_type"] = result["collection_type"]
            backup_id = backup_store.create_backup(
                resource_type=resource_type.value,
                resource_id=resource_id,
                before_state=before_state,
            )

            # Write to Shopify
            if resource_type == ResourceType.PRODUCT:
                client.update_product(resource_id, suggested, original_updated_at=updated_at)
            elif resource_type == ResourceType.COLLECTION:
                ctype = result.get("collection_type", "")
                client.update_collection(resource_id, ctype, suggested, original_updated_at=updated_at)
            else:
                client.update_page(resource_id, suggested, original_updated_at=updated_at)

            # Save after state
            backup_store.update_after_state(backup_id, suggested.model_dump())

            # Update result in-place
            result["status"] = "veröffentlicht"
            result["backup_id"] = backup_id

        except Exception as exc:
            result["status"] = "fehler"
            result["error"] = f"Publish-Fehler: {exc}"
            logging.error("Bulk-Publish fehlgeschlagen für '%s': %s", result["title"], exc)

    progress.empty()

    # Update session state
    st.session_state["_bulk_results"] = bulk_results


def _optimize_single_item(
    item: dict,
    resource_type: ResourceType,
    client: ShopifyClient,
    analyzer: SEOAnalyzer,
    engine: SEOEngine,
    sanitizer: HTMLSanitizer,
    status_container,
    step: int,
    total: int,
) -> dict:
    """Optimize a single item (shared by bulk and smart optimization).

    Returns a result dict with status, suggested_seo, current_seo, changes, etc.
    """
    from keyword_research import research_keywords
    from datetime import datetime as _dt, timezone as _tz

    product_name = item["title"][:50]
    now_str = _dt.now(_tz.utc).strftime("%Y-%m-%d %H:%M")

    result: dict = {
        "title": item["title"],
        "handle": item["handle"],
        "resource_id": item["id"],
        "resource_type": resource_type.value,
        "status": "fehler",
        "error": None,
        "changes": {},
        "backup_id": None,
        "timestamp": now_str,
        "suggested_seo": None,
        "current_seo": None,
        "collection_type": None,
        "updated_at": None,
    }

    try:
        # 1. Load full resource from Shopify
        status_container.info(f"[{step}/{total}] Lade {product_name}...")
        if resource_type == ResourceType.PRODUCT:
            full = client.get_product(item["id"])
        elif resource_type == ResourceType.COLLECTION:
            full = client.get_collection(
                item["id"], item.get("collection_type", "custom")
            )
        else:
            full = client.get_page(item["id"])

        current_seo = full.to_seo_data()

        # 2. SEO analysis
        status_container.info(f"[{step}/{total}] Analysiere {product_name}...")
        try:
            analysis = analyzer.analyze_page(item["handle"], resource_type.value)
        except Exception:
            analysis = None

        # 3. Keyword research
        status_container.info(f"[{step}/{total}] Keywords für {product_name}...")
        brand = ""
        category = ""
        tags = ""
        if resource_type == ResourceType.PRODUCT and isinstance(full, ShopifyProduct):
            brand = full.vendor or ""
            category = full.product_type or ""
            tags = full.tags or ""

        try:
            kw_research = research_keywords(
                product_name=item.get("title", full.title),
                brand=brand,
                category=category,
                tags=tags,
            )
            if analysis:
                analysis.suggested_keywords = kw_research
        except Exception:
            pass

        # 4. KI optimization
        status_container.info(f"[{step}/{total}] KI optimiert {product_name}... (30-90 Sek.)")
        extra_context: dict = {}
        if resource_type == ResourceType.PRODUCT and isinstance(full, ShopifyProduct):
            extra_context = {
                "vendor": full.vendor,
                "product_type": full.product_type,
                "tags": full.tags,
            }
        elif resource_type == ResourceType.COLLECTION and isinstance(full, ShopifyCollection):
            extra_context = {"collection_type": full.collection_type}

        suggested = engine.generate_seo_suggestions(
            resource_type=resource_type,
            current_data=current_seo,
            title=full.title,
            analysis=analysis,
            extra_context=extra_context,
        )

        # 5. Sanitize HTML
        sanitized_html, _san_warnings = sanitizer.full_check(
            suggested.body_html, current_seo.body_html
        )
        suggested.body_html = sanitized_html

        # Record changes
        changes: dict = {}
        if suggested.seo_title != current_seo.seo_title:
            changes["SEO-Titel"] = f"{current_seo.seo_title[:30]}... → {suggested.seo_title[:30]}..."
        if suggested.meta_description != current_seo.meta_description:
            changes["Meta"] = f"{len(suggested.meta_description)} Zeichen (neu)"
        if suggested.h1 != current_seo.h1:
            changes["H1"] = f"{current_seo.h1[:30]}... → {suggested.h1[:30]}..."
        if suggested.body_html != current_seo.body_html:
            changes["Body"] = f"{len(suggested.body_html)} Zeichen (neu)"

        result["changes"] = changes
        result["status"] = "optimiert"
        result["suggested_seo"] = suggested.model_dump()
        result["current_seo"] = current_seo.model_dump()
        result["updated_at"] = full.updated_at if hasattr(full, "updated_at") else ""
        if resource_type == ResourceType.COLLECTION and isinstance(full, ShopifyCollection):
            result["collection_type"] = full.collection_type

        # Store full object reference for auto-publish callers
        result["_full_resource"] = full

    except Exception as exc:
        result["error"] = str(exc)
        result["status"] = "fehler"
        logging.error("Optimierung fehlgeschlagen für '%s': %s", item["title"], exc)

    return result


def _run_bulk_optimization(
    cfg: AppConfig,
    resource_type: ResourceType,
    items: list[dict],
) -> None:
    """Run bulk KI optimization: analyze, optimize, and optionally publish."""
    import time as _time

    st.markdown("---")
    st.markdown("### Bulk-Optimierung läuft...")

    # Mode selection
    mode_col1, mode_col2 = st.columns([1, 2])
    with mode_col1:
        auto_publish = st.checkbox(
            "Direkt live schalten",
            value=False,
            key="bulk_auto_publish",
        )
    with mode_col2:
        if auto_publish:
            st.markdown(
                "✅ **Live-Modus** — Änderungen werden direkt in Shopify geschrieben. "
                "Für jedes Produkt wird ein Backup erstellt."
            )
        else:
            st.markdown(
                "🟡 **Vorschau-Modus** — KI-Vorschläge werden nur generiert, "
                "**nicht** in Shopify geschrieben. Du kannst danach einzeln oder alle auf einmal freigeben."
            )

    total = len(items)
    progress = st.progress(0, text=f"Starte Bulk-Optimierung für {total} Produkte...")
    status_container = st.empty()
    results: list[dict] = []

    client = ShopifyClient(cfg)
    analyzer = SEOAnalyzer(cfg.get_storefront_url())
    engine = SEOEngine(
        api_key=cfg.anthropic_api_key,
        provider=st.session_state.get("ai_provider", "anthropic"),
        model_id=st.session_state.get("ai_model_id", ""),
    )
    sanitizer = HTMLSanitizer()
    backup_store = BackupStore()

    st.caption(f"Provider: {engine.provider} | Modell: {engine.model}")

    for idx, item in enumerate(items):
        step = idx + 1
        progress.progress(step / total, text=f"[{step}/{total}] {item['title'][:50]}...")

        result = _optimize_single_item(
            item, resource_type, client, analyzer, engine, sanitizer,
            status_container, step, total,
        )

        # Auto-publish if enabled and optimization succeeded
        if auto_publish and result["status"] == "optimiert":
            full = result.pop("_full_resource", None)
            if full:
                status_container.info(f"[{step}/{total}] Veröffentliche {item['title'][:50]}...")
                try:
                    suggested = SEOData(**result["suggested_seo"])
                    current_seo = SEOData(**result["current_seo"])

                    # Create backup
                    before_state = current_seo.model_dump()
                    if resource_type == ResourceType.COLLECTION and isinstance(full, ShopifyCollection):
                        before_state["collection_type"] = full.collection_type
                    backup_id = backup_store.create_backup(
                        resource_type=resource_type.value,
                        resource_id=full.id,
                        before_state=before_state,
                    )
                    result["backup_id"] = backup_id

                    # Write to Shopify
                    updated_at = full.updated_at if hasattr(full, "updated_at") else ""
                    if resource_type == ResourceType.PRODUCT:
                        client.update_product(full.id, suggested, original_updated_at=updated_at)
                    elif resource_type == ResourceType.COLLECTION:
                        ctype = full.collection_type if isinstance(full, ShopifyCollection) else ""
                        client.update_collection(full.id, ctype, suggested, original_updated_at=updated_at)
                    else:
                        client.update_page(full.id, suggested, original_updated_at=updated_at)

                    backup_store.update_after_state(backup_id, suggested.model_dump())
                    result["status"] = "veröffentlicht"
                except Exception as pub_exc:
                    logging.error("Auto-Publish fehlgeschlagen: %s", pub_exc)
        else:
            result.pop("_full_resource", None)

        results.append(result)

        # Small delay between products to avoid rate limits
        if idx < total - 1:
            _time.sleep(1)

    progress.empty()
    status_container.empty()
    st.session_state["_bulk_results"] = results

    # Summary
    success = sum(1 for r in results if r["status"] in ("optimiert", "veröffentlicht"))
    st.success(f"Bulk-Optimierung abgeschlossen: {success}/{total} erfolgreich!")
    st.rerun()


# ---------------------------------------------------------------------------
# Smart Automation — Review Queue
# ---------------------------------------------------------------------------


def _run_smart_optimization(
    cfg: AppConfig,
    resource_type: ResourceType,
    items: list[dict],
) -> None:
    """Run KI optimization for selected products and store in smart queue."""
    import time as _time

    st.markdown("---")
    st.markdown("### Optimierung läuft...")

    total = len(items)
    progress = st.progress(0, text=f"Starte Optimierung für {total} ausgewählte Produkte...")
    status_container = st.empty()
    results: list[dict] = []

    client = ShopifyClient(cfg)
    analyzer = SEOAnalyzer(cfg.get_storefront_url())
    engine = SEOEngine(
        api_key=cfg.anthropic_api_key,
        provider=st.session_state.get("ai_provider", "anthropic"),
        model_id=st.session_state.get("ai_model_id", ""),
    )
    sanitizer = HTMLSanitizer()

    st.caption(f"Provider: {engine.provider} | Modell: {engine.model}")

    for idx, item in enumerate(items):
        step = idx + 1
        progress.progress(step / total, text=f"[{step}/{total}] {item['title'][:50]}...")

        result = _optimize_single_item(
            item, resource_type, client, analyzer, engine, sanitizer,
            status_container, step, total,
        )
        result.pop("_full_resource", None)
        result["review_status"] = "pending"

        results.append(result)

        if idx < total - 1:
            _time.sleep(1)

    progress.empty()
    status_container.empty()

    # Store in smart queue and switch to review mode
    st.session_state["_smart_queue"] = results
    st.session_state["_smart_queue_index"] = 0
    st.session_state["_smart_queue_phase"] = "review"

    success = sum(1 for r in results if r["status"] == "optimiert")
    st.success(f"Optimierung abgeschlossen: {success}/{total} erfolgreich! Starte Freigabe-Queue...")
    st.rerun()


def _render_smart_comparison(current_seo: dict, suggested_seo: dict, editable: bool = False, queue_idx: int = 0) -> dict | None:
    """Render a detailed before/after comparison for the smart review queue.

    When *editable* is True, the "Vorschlag" side uses input fields so the user
    can tweak suggestions before approving.  Returns a dict of edited values
    if editable, or None otherwise.
    """
    from bs4 import BeautifulSoup as BS4

    current = SEOData(**current_seo)
    suggested = SEOData(**suggested_seo)
    edits: dict = {}

    # --- SEO-Titel ---
    title_changed = current.seo_title != suggested.seo_title
    st.markdown(f"#### SEO-Titel {'<span class=\"changed-badge\">● Geändert</span>' if title_changed else ''}", unsafe_allow_html=True)
    col_old, col_new = st.columns(2)
    with col_old:
        st.markdown("**Aktuell:**")
        st.code(current.seo_title or "(leer)")
        st.caption(f"{len(current.seo_title)}/{_TITLE_MAX} Zeichen")
    with col_new:
        st.markdown("**Vorschlag:**")
        if editable:
            edited_title = st.text_input(
                "SEO-Titel bearbeiten",
                value=suggested.seo_title or "",
                key=f"smart_edit_title_{queue_idx}",
                label_visibility="collapsed",
            )
            edits["seo_title"] = edited_title
            title_len = len(edited_title)
        else:
            st.code(suggested.seo_title or "(leer)")
            title_len = len(suggested.seo_title)
        css_cls = "char-count char-count-ok" if title_len <= _TITLE_MAX else "char-count char-count-over"
        st.markdown(f'<span class="{css_cls}">{title_len}/{_TITLE_MAX} Zeichen</span>', unsafe_allow_html=True)

    # --- Meta-Beschreibung ---
    meta_changed = current.meta_description != suggested.meta_description
    st.markdown(f"#### Meta-Beschreibung {'<span class=\"changed-badge\">● Geändert</span>' if meta_changed else ''}", unsafe_allow_html=True)
    col_old, col_new = st.columns(2)
    with col_old:
        st.markdown("**Aktuell:**")
        st.code(current.meta_description or "(leer)")
        st.caption(f"{len(current.meta_description)}/{_DESC_MAX} Zeichen")
    with col_new:
        st.markdown("**Vorschlag:**")
        if editable:
            edited_meta = st.text_area(
                "Meta-Beschreibung bearbeiten",
                value=suggested.meta_description or "",
                key=f"smart_edit_meta_{queue_idx}",
                label_visibility="collapsed",
                height=100,
            )
            edits["meta_description"] = edited_meta
            meta_len = len(edited_meta)
        else:
            st.code(suggested.meta_description or "(leer)")
            meta_len = len(suggested.meta_description)
        css_cls = "char-count char-count-ok" if meta_len <= _DESC_MAX else "char-count char-count-over"
        st.markdown(f'<span class="{css_cls}">{meta_len}/{_DESC_MAX} Zeichen</span>', unsafe_allow_html=True)

    # --- H1 ---
    h1_changed = current.h1 != suggested.h1
    st.markdown(f"#### H1-Überschrift {'<span class=\"changed-badge\">● Geändert</span>' if h1_changed else ''}", unsafe_allow_html=True)
    col_old, col_new = st.columns(2)
    with col_old:
        st.markdown("**Aktuell:**")
        st.code(current.h1 or "(leer)")
    with col_new:
        st.markdown("**Vorschlag:**")
        if editable:
            edited_h1 = st.text_input(
                "H1 bearbeiten",
                value=suggested.h1 or "",
                key=f"smart_edit_h1_{queue_idx}",
                label_visibility="collapsed",
            )
            edits["h1"] = edited_h1
        else:
            st.code(suggested.h1 or "(leer)")

    # --- Body HTML ---
    body_changed = current.body_html != suggested.body_html
    st.markdown(f"#### Body HTML {'<span class=\"changed-badge\">● Geändert</span>' if body_changed else ''}", unsafe_allow_html=True)

    old_text = BS4(current.body_html or "", "html.parser").get_text(separator=" ", strip=True)
    new_text = BS4(suggested.body_html or "", "html.parser").get_text(separator=" ", strip=True)
    old_words = len(old_text.split()) if old_text else 0
    new_words = len(new_text.split()) if new_text else 0

    col_old, col_new = st.columns(2)
    with col_old:
        st.markdown(f"**Aktuell:** {old_words} Wörter")
        _render_content_preview(current.body_html)
    with col_new:
        word_diff = new_words - old_words
        diff_str = f" (+{word_diff})" if word_diff > 0 else f" ({word_diff})" if word_diff < 0 else ""
        st.markdown(f"**Vorschlag:** {new_words} Wörter{diff_str}")
        _render_content_preview(suggested.body_html)

    # --- Bilder Alt-Texte ---
    all_images = suggested.images or current.images or []
    if all_images:
        current_alt_map = {img.image_id: img.current_alt for img in (current.images or [])}
        img_changes = sum(
            1 for img in all_images
            if img.suggested_alt and img.suggested_alt != current_alt_map.get(img.image_id, img.current_alt)
        )
        st.markdown(f"#### Bilder Alt-Texte ({img_changes}/{len(all_images)} geändert)")

        for i, img in enumerate(all_images):
            old_alt = current_alt_map.get(img.image_id, img.current_alt) or ""
            new_alt = img.suggested_alt or old_alt
            if old_alt != new_alt:
                img_col, old_col, new_col = st.columns([1, 3, 3])
                with img_col:
                    if img.image_src:
                        st.image(img.image_src, width=60)
                    else:
                        st.caption(f"Bild #{img.image_id}")
                with old_col:
                    st.code(old_alt or "(leer)")
                with new_col:
                    if editable:
                        edited_alt = st.text_input(
                            f"Alt-Text Bild {i+1}",
                            value=new_alt,
                            key=f"smart_edit_alt_{queue_idx}_{img.image_id}",
                            label_visibility="collapsed",
                        )
                        if f"image_alts" not in edits:
                            edits["image_alts"] = {}
                        edits["image_alts"][img.image_id] = edited_alt
                    else:
                        st.code(new_alt)

    return edits if editable else None


def _render_smart_review(cfg: AppConfig) -> None:
    """Render the smart review queue — one product at a time with approve/skip/reject."""
    queue: list[dict] = st.session_state.get("_smart_queue", [])
    if not queue:
        return

    phase = st.session_state.get("_smart_queue_phase", "select")

    # --- Summary phase ---
    if phase == "summary":
        _render_smart_summary(queue)
        return

    # --- Review phase ---
    idx = st.session_state.get("_smart_queue_index", 0)
    total = len(queue)

    # Find next pending item
    while idx < total and queue[idx]["review_status"] != "pending":
        idx += 1

    if idx >= total:
        st.session_state["_smart_queue_phase"] = "summary"
        st.rerun()
        return

    st.session_state["_smart_queue_index"] = idx
    result = queue[idx]

    # Count reviewed
    reviewed = sum(1 for r in queue if r["review_status"] != "pending")
    approved_so_far = sum(1 for r in queue if r["review_status"] == "approved")
    rejected_so_far = sum(1 for r in queue if r["review_status"] == "rejected")
    skipped_so_far = sum(1 for r in queue if r["review_status"] == "skipped")

    # --- Header ---
    st.markdown(
        f'<div class="info-box-header">'
        f'<span class="queue-title">Freigabe-Queue</span>'
        f'<span class="queue-counter">'
        f'Produkt {reviewed + 1} von {total}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.progress((reviewed + 1) / total)

    # Status badges
    stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)
    stat_col1.metric("Ausstehend", total - reviewed)
    stat_col2.metric("✅ Freigegeben", approved_so_far)
    stat_col3.metric("⏭️ Übersprungen", skipped_so_far)
    stat_col4.metric("❌ Abgelehnt", rejected_so_far)

    st.markdown("---")

    # --- Current product ---
    st.markdown(f"### {result['title']}")
    if result.get("timestamp"):
        st.caption(f"Optimiert am: {result['timestamp']}")

    # Handle errors
    if result["status"] == "fehler":
        st.error(f"Fehler bei diesem Produkt: {result.get('error', 'Unbekannt')}")
        if st.button("⏭️ Weiter (Fehler überspringen)", key="smart_skip_error", use_container_width=True):
            queue[idx]["review_status"] = "skipped"
            st.session_state["_smart_queue_index"] = idx + 1
            st.rerun()
        return

    # --- Detailed comparison (editable!) ---
    edits = None
    if result.get("current_seo") and result.get("suggested_seo"):
        edits = _render_smart_comparison(
            result["current_seo"], result["suggested_seo"],
            editable=True, queue_idx=idx,
        )
    elif result.get("changes"):
        for key, val in result["changes"].items():
            st.markdown(f"**{key}:** {val}")

    # --- Action buttons ---
    st.markdown("---")
    btn_col1, btn_col2, btn_col3, btn_col4 = st.columns(4)

    with btn_col1:
        if st.button(
            "✅ Freigeben",
            type="primary",
            use_container_width=True,
            key=f"smart_approve_{idx}",
        ):
            # Apply inline edits to suggested_seo before publishing
            if edits and result.get("suggested_seo"):
                seo = result["suggested_seo"]
                if "seo_title" in edits:
                    seo["seo_title"] = edits["seo_title"]
                if "meta_description" in edits:
                    seo["meta_description"] = edits["meta_description"]
                if "h1" in edits:
                    seo["h1"] = edits["h1"]
                if "image_alts" in edits and seo.get("images"):
                    for img in seo["images"]:
                        img_id = img.get("image_id")
                        if img_id in edits["image_alts"]:
                            img["suggested_alt"] = edits["image_alts"][img_id]

            _publish_bulk_items(cfg, queue, publish_index=idx)
            queue[idx]["review_status"] = "approved"
            st.session_state["_smart_queue_index"] = idx + 1
            st.rerun()

    with btn_col2:
        if st.button(
            "⏭️ Überspringen",
            use_container_width=True,
            key=f"smart_skip_{idx}",
        ):
            queue[idx]["review_status"] = "skipped"
            st.session_state["_smart_queue_index"] = idx + 1
            st.rerun()

    with btn_col3:
        if st.button(
            "❌ Ablehnen",
            use_container_width=True,
            key=f"smart_reject_{idx}",
        ):
            queue[idx]["review_status"] = "rejected"
            st.session_state["_smart_queue_index"] = idx + 1
            st.rerun()

    with btn_col4:
        if st.button(
            "🚪 Abbrechen",
            use_container_width=True,
            key="smart_cancel",
        ):
            st.session_state["_smart_queue_phase"] = "summary"
            st.rerun()


def _render_smart_summary(queue: list[dict]) -> None:
    """Render the final summary after all products have been reviewed."""
    st.markdown(
        '<div class="info-box-header">'
        '<span class="queue-title">Freigabe abgeschlossen</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    approved = [r for r in queue if r["review_status"] == "approved"]
    skipped = [r for r in queue if r["review_status"] == "skipped"]
    rejected = [r for r in queue if r["review_status"] == "rejected"]
    errors = [r for r in queue if r["status"] == "fehler"]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("✅ Freigegeben", len(approved))
    m2.metric("⏭️ Übersprungen", len(skipped))
    m3.metric("❌ Abgelehnt", len(rejected))
    m4.metric("⚠️ Fehler", len(errors))

    if approved:
        st.markdown("#### ✅ Freigegeben (live geschaltet)")
        for r in approved:
            backup_info = f" · Backup #{r.get('backup_id', '?')}" if r.get("backup_id") else ""
            st.markdown(f"- **{r['title']}**{backup_info}")

    if skipped:
        st.markdown("#### ⏭️ Übersprungen")
        for r in skipped:
            st.markdown(f"- {r['title']}")

    if rejected:
        st.markdown("#### ❌ Abgelehnt")
        for r in rejected:
            st.markdown(f"- {r['title']}")

    if errors:
        st.markdown("#### ⚠️ Fehler")
        for r in errors:
            st.markdown(f"- {r['title']}: {r.get('error', 'Unbekannt')}")

    st.markdown("---")
    if st.button("Fertig — zurück zur Auswahl", type="primary", use_container_width=True, key="smart_done"):
        # Clean up smart queue state
        for key in ["_smart_queue", "_smart_queue_index", "_smart_queue_phase"]:
            st.session_state.pop(key, None)
        st.rerun()


# ---------------------------------------------------------------------------
# Tab 3 — Google Rankings
# ---------------------------------------------------------------------------


def _render_tab_rankings() -> None:
    """Render the Google Search Console rankings tab."""
    cfg: AppConfig | None = st.session_state.get("config")
    if not cfg:
        st.info("Bitte zuerst die Konfiguration ausfüllen.")
        return

    if not st.session_state.get("gsc_connected"):
        st.info(
            "Google Search Console ist nicht verbunden. "
            "Trage den Pfad zur Google-Credentials-Datei in der Seitenleiste ein "
            "und klicke auf 'Testen'."
        )
        return

    st.markdown("### Google Search Console - Ranking-Übersicht")

    tracker = _get_ranking_tracker()
    if not tracker:
        st.error("Ranking-Tracker konnte nicht initialisiert werden.")
        return

    if not tracker.is_connected():
        ok, msg = tracker.connect()
        if not ok:
            st.error(f"GSC-Verbindung fehlgeschlagen: {msg}")
            return

    # URL input
    st.markdown("#### Seite analysieren")

    url_mode = st.radio(
        "URL-Modus",
        options=["Manuelle URL", "Aus Ressource wählen"],
        horizontal=True,
        key="ranking_url_mode",
    )

    page_url = ""
    if url_mode == "Manuelle URL":
        page_url = st.text_input(
            "Seiten-URL",
            value=cfg.get_storefront_url() + "/",
            key="ranking_manual_url",
        )
    else:
        rank_col1, rank_col2 = st.columns([1, 3])
        with rank_col1:
            resource_type_label = st.selectbox(
                "Typ",
                options=[rt.value for rt in ResourceType],
                key="ranking_resource_type",
            )
        resource_type = ResourceType(resource_type_label)
        cache_key = f"_items_{resource_type.value}"
        if cache_key in st.session_state:
            items_list = st.session_state[cache_key]
            if items_list:
                with rank_col2:
                    item_labels = [f"{item['title']} ({item['handle']})" for item in items_list]
                    selected_idx = st.selectbox(
                        "Ressource",
                        options=range(len(item_labels)),
                        format_func=lambda i: item_labels[i],
                        key="ranking_sel_item",
                    )
                    page_url = _build_page_url(
                        cfg, resource_type, items_list[selected_idx]["handle"]
                    )
                st.caption(f"URL: `{page_url}`")
            else:
                st.info("Lade zuerst Ressourcen im SEO-Tab.")
        else:
            st.info("Lade zuerst Ressourcen im SEO-Tab.")

    # Timeframe
    days = st.selectbox(
        "Zeitraum",
        options=[7, 14, 28, 90],
        index=2,
        format_func=lambda d: f"Letzte {d} Tage",
        key="ranking_days",
    )

    if page_url and st.button("Rankings abrufen", type="primary", use_container_width=True, key="btn_fetch_rankings"):
        with st.spinner("Lade Ranking-Daten..."):
            rankings = tracker.get_page_rankings(page_url, days=days)
            st.session_state["_tab_rankings_data"] = rankings
            st.session_state["_tab_rankings_url"] = page_url

    # Display results
    rankings: list[RankingData] = st.session_state.get("_tab_rankings_data", [])
    rankings_url: str = st.session_state.get("_tab_rankings_url", "")

    if rankings:
        st.markdown(f"#### Rankings für `{rankings_url}`")
        st.markdown(f"**{len(rankings)} Keywords** (letzte {days} Tage)")

        # Summary
        total_clicks = sum(r.clicks for r in rankings)
        total_impressions = sum(r.impressions for r in rankings)
        avg_position = sum(r.position for r in rankings) / len(rankings) if rankings else 0
        avg_ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Klicks", f"{total_clicks:,}")
        m2.metric("Impressionen", f"{total_impressions:,}")
        m3.metric("Durchschnitt Position", f"{avg_position:.1f}")
        m4.metric("Durchschnitt CTR", f"{avg_ctr:.1f}%")

        # Keyword table
        st.markdown("#### Keyword-Details")
        rows = []
        for rd in rankings:
            if rd.position <= 3:
                pos_icon = "Top 3"
            elif rd.position <= 10:
                pos_icon = "Seite 1"
            elif rd.position <= 20:
                pos_icon = "Seite 2"
            else:
                pos_icon = f"Seite {int(rd.position // 10) + 1}"

            rows.append({
                "Status": pos_icon,
                "Keyword": rd.keyword,
                "Position": f"{rd.position:.1f}",
                "Klicks": rd.clicks,
                "Impressionen": rd.impressions,
                "CTR": f"{rd.ctr * 100:.1f}%",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # Snapshot
        if st.button("Snapshot speichern", key="btn_save_ranking_snap"):
            tracker.save_snapshot(rankings)
            st.success("Ranking-Snapshot gespeichert!")

        # Historical trend
        history = tracker.load_history(rankings_url)
        if history:
            st.markdown("#### Ranking-Verlauf")
            st.caption(f"{len(history)} historische Datenpunkte")
            df = pd.DataFrame(history)
            if "snapshot_time" in df.columns and "position" in df.columns:
                chart_df = (
                    df.groupby("snapshot_time")["position"]
                    .mean()
                    .reset_index()
                    .rename(columns={"snapshot_time": "Datum", "position": "Durchschnitt Position"})
                )
                st.line_chart(chart_df, x="Datum", y="Durchschnitt Position")

            # Per-keyword trend
            keywords_in_history = df["keyword"].unique().tolist() if "keyword" in df.columns else []
            if keywords_in_history:
                selected_kw = st.selectbox(
                    "Keyword-Trend anzeigen",
                    options=keywords_in_history,
                    key="ranking_trend_kw",
                )
                trend = tracker.get_trend(rankings_url, selected_kw)
                if trend:
                    trend_df = pd.DataFrame(trend)
                    st.line_chart(trend_df, x="date", y="position")

    elif rankings_url:
        st.info("Keine Ranking-Daten für diese URL gefunden.")


# ---------------------------------------------------------------------------
# Tab 4 — Backup-Verlauf
# ---------------------------------------------------------------------------


def _render_tab_backups() -> None:
    """Render the backup history tab."""
    st.markdown("### Backup-Verlauf")

    backup_store = BackupStore()
    backups = backup_store.list_backups()

    if not backups:
        st.info("Noch keine Backups vorhanden.")
        return

    # Cleanup button
    cleanup_col1, cleanup_col2 = st.columns([3, 1])
    with cleanup_col1:
        st.caption(f"{len(backups)} Backup(s) gespeichert")
    with cleanup_col2:
        if st.button("Alte Backups löschen", key="btn_cleanup"):
            cleaned = backup_store.cleanup_old_backups(max_age_days=90)
            if cleaned > 0:
                st.success(f"{cleaned} alte Backup(s) gelöscht.")
                st.rerun()
            else:
                st.info("Keine alten Backups zum Löschen.")

    # ------------------------------------------------------------------
    # Batch-Rollback: grouped by minute-level timestamp
    # ------------------------------------------------------------------
    groups = backup_store.list_backup_groups(limit=20)
    if groups:
        st.markdown("#### Batch-Rollback")
        st.caption(
            "Zusammengehörige Optimierungen (gleicher Zeitpunkt) können "
            "mit einem Klick komplett zurückgesetzt werden."
        )
        for gi, grp in enumerate(groups):
            minute_label = grp["minute"].replace("T", " ")
            type_label = grp["resource_type"]
            count = grp["count"]
            has_active = grp["has_active"]  # at least one not rolled back

            col_info, col_action = st.columns([3, 1])
            with col_info:
                status_icon = "🟢" if has_active else "⏪"
                st.markdown(
                    f"{status_icon} **{minute_label}** — {count}× {type_label}"
                )
            with col_action:
                if has_active:
                    confirm_key = f"batch_rb_confirm_{gi}"
                    confirmed = st.checkbox("Bestätigen", key=confirm_key)
                    if st.button(
                        f"Alle {count} zurücksetzen",
                        key=f"batch_rb_btn_{gi}",
                        disabled=not confirmed,
                    ):
                        _perform_batch_rollback(
                            backup_store, grp["backup_ids"]
                        )
                else:
                    st.caption("Bereits zurückgesetzt")
        st.markdown("---")

    # Table
    rows = []
    for b in backups:
        rows.append(
            {
                "ID": b.id,
                "Typ": b.resource_type,
                "Ressource-ID": b.resource_id,
                "Zeitstempel": b.timestamp,
                "Zurückgesetzt": "Ja" if b.rolled_back else "Nein",
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # Expandable details
    for b in backups:
        with st.expander(
            f"Backup #{b.id} - {b.resource_type} ({b.resource_id}) - {b.timestamp}"
        ):
            col_b, col_a = st.columns(2)
            with col_b:
                st.markdown("**Vorher:**")
                st.json(b.before_state)
            with col_a:
                st.markdown("**Nachher:**")
                st.json(b.after_state)

            if b.rolled_back:
                st.info("Bereits zurückgesetzt.")
            else:
                rollback_key = f"rollback_confirm_{b.id}"
                confirm_rb = st.checkbox(
                    "Rollback bestätigen", key=rollback_key
                )
                if st.button(
                    f"Rollback #{b.id}",
                    key=f"btn_rollback_{b.id}",
                    disabled=not confirm_rb,
                ):
                    _perform_rollback(b)


def _perform_batch_rollback(
    backup_store: BackupStore, backup_ids: list[int]
) -> None:
    """Roll back a group of backups at once (batch rollback)."""
    cfg: AppConfig | None = st.session_state.get("config")
    if not cfg:
        st.error("Keine Konfiguration vorhanden.")
        return

    if st.session_state.get("write_lock"):
        st.warning("Ein Schreibvorgang läuft bereits.")
        return

    st.session_state["write_lock"] = True
    success_count = 0
    fail_count = 0
    try:
        client = ShopifyClient(cfg)
        progress_bar = st.progress(0, text="Batch-Rollback wird ausgeführt...")
        total = len(backup_ids)

        for idx, bid in enumerate(backup_ids):
            entry = backup_store.get_backup(bid)
            if entry is None or entry.rolled_back:
                continue

            restore_data = backup_store.get_restore_data(bid)
            if not restore_data:
                fail_count += 1
                continue

            try:
                collection_type = restore_data.pop("collection_type", "custom")
                seo_data = SEOData(**restore_data)
                resource_type_str = entry.resource_type

                if resource_type_str == ResourceType.PRODUCT.value:
                    client.update_product(entry.resource_id, seo_data)
                elif resource_type_str == ResourceType.COLLECTION.value:
                    client.update_collection(
                        entry.resource_id, collection_type, seo_data
                    )
                else:
                    client.update_page(entry.resource_id, seo_data)

                backup_store.mark_rolled_back(bid)
                success_count += 1
            except Exception as exc:
                logging.warning("Rollback für Backup #%d fehlgeschlagen: %s", bid, exc)
                fail_count += 1

            progress_bar.progress(
                (idx + 1) / total,
                text=f"Rollback {idx + 1}/{total}...",
            )

        progress_bar.empty()
        if success_count > 0:
            st.success(
                f"Batch-Rollback abgeschlossen: {success_count} erfolgreich"
                + (f", {fail_count} fehlgeschlagen" if fail_count else "")
            )
        if fail_count > 0 and success_count == 0:
            st.error(f"Alle {fail_count} Rollbacks fehlgeschlagen.")
        st.rerun()
    except Exception as exc:
        st.error(f"Fehler beim Batch-Rollback: {exc}")
    finally:
        st.session_state["write_lock"] = False


def _render_tab_help() -> None:
    """Render the help & documentation tab."""

    st.markdown("### Willkommen bei ShopSEO Pro")
    st.markdown(
        "ShopSEO Pro ist ein KI-gestütztes SEO-Optimierungstool, das speziell für "
        "Shopify-Stores entwickelt wurde. Es analysiert deine Produkte, Kategorien und "
        "Seiten, findet SEO-Schwachstellen und generiert automatisch optimierte Texte "
        "mit Hilfe von künstlicher Intelligenz."
    )

    st.markdown("---")

    # Schnellstart
    with st.expander("Schnellstart — So richtest du das Tool ein", expanded=False):
        st.markdown("""
**1. Shopify-Verbindung einrichten**
- Öffne die Seitenleiste (links) und klappe **Shopify-Verbindung** auf
- Trage deine **Shopify Store URL** ein (z.B. `mein-shop` oder `mein-shop.myshopify.com`)
- Trage deinen **Shopify Access Token** ein (findest du unter Shopify Admin → Einstellungen → Apps → Custom App)
- Optional: Trage deine **Storefront URL** ein (z.B. `https://www.mein-shop.de`)

**2. KI-Provider wählen**
- Klappe **KI-Einstellungen** auf
- Wähle zwischen **Anthropic** (direkt) oder **OpenRouter** (viele Modelle)
- Trage den entsprechenden **API Key** ein
- Wähle ein **KI-Modell** aus der Liste

**3. Verbindung testen**
- Klicke auf **Testen** in der Seitenleiste
- Bei Erfolg erscheint "Shopify: Verbunden" in grün
- Klicke auf **Speichern** um die Einstellungen in der .env-Datei zu sichern

**4. Optional: Google Search Console**
- Klappe **Google Search Console** auf
- Trage den Pfad zur Google Service Account JSON-Datei ein
- Klicke erneut auf **Testen**
        """)

    # Tab-Erklärungen
    with st.expander("Tab 1: SEO-Optimierung — Einzelne Seiten optimieren"):
        st.markdown("""
**Das ist der Hauptbereich des Tools. Hier optimierst du einzelne Produkte, Kategorien oder Seiten.**

**Schritt 1: Ressource wählen**
- Wähle den **Typ** (Produkt, Kategorie oder Statische Seite)
- Nutze die **Suche** um schnell ein bestimmtes Produkt zu finden
- Wähle das gewünschte Element aus der Liste

**Schritt 2: SEO analysieren**
- Klicke auf **SEO analysieren** — das Tool crawlt dann die Live-Seite deines Shops
- Du bekommst einen **SEO-Score** (0-100) mit detaillierter Aufschlüsselung
- **Kritische Probleme** (rot): Müssen dringend behoben werden
- **Warnungen** (gelb): Sollten behoben werden
- **Bestanden** (grün): Alles in Ordnung
- Zusätzlich wird eine **Google Keyword-Recherche** durchgeführt (echte Suchanfragen!)

**Schritt 3: SEO optimieren**
- Klicke auf **SEO optimieren** — die KI generiert optimierte Texte
- Du siehst ein **Dashboard** mit Vorher/Nachher-Vergleich für:
  - SEO-Titel (max. 60 Zeichen)
  - Meta-Beschreibung (max. 160 Zeichen)
  - H1-Überschrift
  - H2-Überschriften
  - Body-HTML (mit Vorschau und Code-Editor)
  - Bild-Alt-Texte
- Alle Felder sind **bearbeitbar** — du kannst die KI-Vorschläge anpassen
- **Compliance-Warnungen** zeigen dir, ob rechtliche Vorgaben eingehalten werden

**Schritt 4: Live schalten**
- Setze den Haken bei "Ich bestätige die Änderungen"
- Klicke auf **In Shopify übernehmen**
- Vor dem Schreiben wird automatisch ein **Backup** erstellt
- Bei Fehler kannst du im Backup-Tab **zurücksetzen**
        """)

    with st.expander("Tab 2: Batch-Analyse — Mehrere Seiten auf einmal"):
        st.markdown("""
**Analysiere und optimiere alle deine Produkte, Kategorien oder Seiten auf einmal.**

**Produkte filtern:**
- Gib einen **Suchbegriff** ein um nur bestimmte Produkte zu laden (z.B. "elfbar elfa")
- Mehrere Begriffe werden mit UND verknüpft — alle müssen im Titel vorkommen

**Bereits optimierte Produkte überspringen:**
- Wähle einen **Zeitraum** (1, 3, 7, 14 oder 30 Tage)
- Produkte die in diesem Zeitraum bereits optimiert wurden, werden automatisch übersprungen
- Du siehst das **Optimierungsdatum** hinter jedem Produkt (z.B. `[optimiert: 15.03.2026]`)

**Zwei Aktionen:**
- **Alle analysieren**: SEO-Score für alle geladenen Produkte berechnen — liefert eine sortierbare Tabelle mit Score, Problemen, Wortanzahl etc.
- **Alle optimieren (KI)**: Analyse + KI-Optimierung + optionales Auto-Publish in einem Durchlauf
  - Setzt den Haken bei "Auto-Publish" um Änderungen direkt in Shopify zu schreiben
  - Jede Änderung wird vorher automatisch als **Backup** gesichert
  - Du siehst den Fortschritt und Status für jedes Produkt in Echtzeit

**Ergebnisse:**
- Sortierbare Tabelle mit SEO-Score, Problemen, Warnungen und Wortanzahl
- Exportiere die Ergebnisse als **CSV-Datei** für Excel
        """)

    with st.expander("Tab 3: Google Rankings — Suchmaschinen-Performance"):
        st.markdown("""
**Verfolge deine Google-Rankings über die Google Search Console.**

*Voraussetzung: Google Search Console muss in der Seitenleiste verbunden sein.*

- Gib eine **URL** ein oder wähle eine Ressource aus deinem Shop
- Wähle den **Zeitraum** (7, 14, 28 oder 90 Tage)
- Klicke auf **Rankings abrufen**
- Du siehst:
  - **Gesamtklicks**, **Impressionen**, **Durchschnittsposition** und **CTR**
  - **Keyword-Tabelle** mit Position, Klicks und Impressionen pro Keyword
  - Keyword-Status: Top 3, Seite 1, Seite 2, etc.
- **Snapshot speichern**: Speichert die aktuellen Daten für den historischen Verlauf
- **Ranking-Verlauf**: Zeigt die Positionsentwicklung über die Zeit als Liniendiagramm
        """)

    with st.expander("Tab 4: Backup-Verlauf — Sicherheit & Rollback"):
        st.markdown("""
**Jede Änderung die du über das Tool in Shopify machst, wird vorher gesichert.**

- Siehst eine **Tabelle** aller bisherigen Änderungen mit Zeitstempel
- Klappe ein Backup auf um den **Vorher/Nachher-Vergleich** als JSON zu sehen
- Um eine Änderung rückgängig zu machen:
  1. Setze den Haken bei "Rollback bestätigen"
  2. Klicke auf **Rollback**
  3. Der vorherige Zustand wird in Shopify wiederhergestellt
- **Alte Backups löschen**: Entfernt Backups die älter als 90 Tage sind
        """)

    st.markdown("---")

    # Technische Details
    with st.expander("Wie funktioniert die SEO-Analyse?"):
        st.markdown("""
Die SEO-Analyse crawlt die **öffentliche URL** deines Shops (nicht die Shopify-Admin-Seite) und prüft:

| Prüfung | Was wird geprüft? | Gewichtung |
|---------|-------------------|------------|
| **Titel-Tag** | Vorhanden? 30-60 Zeichen? | Kritisch |
| **Meta-Beschreibung** | Vorhanden? 70-160 Zeichen? | Kritisch |
| **H1-Überschrift** | Genau eine H1? Keyword enthalten? | Kritisch |
| **Content-Länge** | Produkte: 300+, Kategorien: 150+, Seiten: 200+ Wörter | Kritisch/Warnung |
| **Bilder** | Alle Bilder mit Alt-Text? | Warnung |
| **Interne Links** | Links zu anderen Seiten im Shop? | Warnung |
| **Schema-Markup** | JSON-LD vorhanden (Product, etc.)? | Warnung |
| **Canonical-Tag** | Vorhanden und korrekt? | Warnung |
| **Open Graph Tags** | og:title, og:description, og:image? | Warnung |
| **TPD2-Warnung** | Gesundheitswarnung bei Nikotinprodukten? | Kritisch |
| **Robots Meta** | Keine noindex/nofollow Blockierung? | Kritisch |

**Score-Berechnung:** Start bei 100 Punkten, -15 pro kritisches Problem, -5 pro Warnung.
        """)

    with st.expander("Wie funktioniert die KI-Optimierung?"):
        st.markdown("""
Die KI-Optimierung nutzt **Claude** (Anthropic) oder andere Modelle über **OpenRouter**.

**Was die KI macht:**
1. Liest den aktuellen Content deiner Seite (bis zu 10.000 Zeichen)
2. Analysiert die SEO-Probleme aus der Analyse
3. Nutzt die **Google Keyword-Recherche** (echte Suchanfragen)
4. Berücksichtigt deine **Google Rankings** (falls verbunden)
5. Generiert optimierte Texte unter Einhaltung aller **rechtlichen Vorgaben**

**Was die KI berücksichtigt:**
- **E-E-A-T**: Expertise, Erfahrung, Autorität und Vertrauenswürdigkeit
- **Keyword-Strategie**: Kauf-Keywords im Titel, Longtail in H2, natürliche Integration im Body
- **Content-Struktur**: Kurze Absätze, H2-Gliederung, FAQ-Bereich, Listen
- **Zeichenlimits**: SEO-Titel max. 60, Meta-Beschreibung max. 160 Zeichen
- **Compliance**: TabakerzG, TPD2, JuSchG — automatischer Check nach der Generierung

**Sicherheitsmaßnahmen:**
- Alle generierten Texte werden durch den **HTML-Sanitizer** gereinigt
- Gefährliche Tags (script, iframe, etc.) werden entfernt
- Semantische HTML5-Tags (section, article, details, figure, etc.) sind erlaubt für besseres SEO
- Liquid-Syntax ({{ }}) wird erkannt und blockiert
- TPD2-Warnhinweis wird geschützt (kann nicht versehentlich gelöscht werden)
        """)

    with st.expander("Wie funktioniert die Keyword-Recherche?"):
        st.markdown("""
Die Keyword-Recherche nutzt die **Google Suggest API** — das sind die Vorschläge, die Google beim Tippen anzeigt.

**Ablauf:**
1. **Seed-Keywords generieren**: Aus Produktname, Marke, Kategorie und Tags
2. **Google Suggest abfragen**: Für jeden Seed normale + Shopping-Vorschläge
3. **Alphabet-Expansion**: Seed + jeden Buchstaben (A-Z) → findet versteckte Keywords
4. **Kategorisierung**: Jedes Keyword wird nach Suchintention einsortiert:
   - **Kauf-Keywords** (höchste Priorität): "elfbar kaufen", "vape bestellen"
   - **Primäre Keywords**: "elfbar 600", "elf bar"
   - **Longtail-Keywords**: "elfbar 600 watermelon geschmack"
   - **Fragen-Keywords**: "wie funktioniert elfbar", "wie lange hält elfbar"
   - **Research-Keywords**: "elfbar test", "elfbar vergleich"

**Caching:** Ergebnisse werden zwischengespeichert um doppelte API-Anfragen zu vermeiden.
        """)

    with st.expander("Rechtliche Compliance — Deutsche Vape-Gesetze"):
        st.markdown("""
Das Tool prüft automatisch alle generierten Texte auf Einhaltung deutscher Gesetze:

**TabakerzG §§19-22 (Tabakerzeugnisgesetz)**
- ❌ Verboten: "gesünder", "weniger schädlich", "harmlos", "sicher", "Rauchentwöhnung"
- ❌ Verboten: Auffordernde Werbung wie "Jetzt ausprobieren", "Teste jetzt", "Erlebe"
- ✅ Erlaubt: "Jetzt bestellen", "Zum Produkt", "Mehr erfahren"

**TPD2 (EU-Tabakrichtlinie)**
- Bei nikotinhaltigen Produkten **muss** dieser Hinweis im Content stehen:
- *"Dieses Produkt enthält Nikotin – einen Stoff, der sehr stark abhängig macht."*

**JuSchG §10 (Jugendschutzgesetz)**
- Altershinweis "Ab 18" muss erwähnt werden
- "Kein Verkauf an Minderjährige"

**HWG (Heilmittelwerbegesetz)**
- Keine therapeutischen oder gesundheitlichen Behauptungen

**UWG (Wettbewerbsrecht)**
- Alle Produkteigenschaften müssen sachlich korrekt sein
        """)

    with st.expander("Backup & Sicherheit"):
        st.markdown("""
**Jede Änderung ist geschützt.** Der Ablauf bei jedem Schreibvorgang:

```
1. Aktuelle Daten aus Shopify laden (Vorher-Zustand)
2. Backup in SQLite-Datenbank speichern
3. Neue Daten an Shopify senden
4. Verifizierung: Shopify-Daten erneut lesen und vergleichen
5. Nachher-Zustand im Backup speichern
6. Bei Fehler: Automatischer Rollback möglich
```

**Weitere Sicherheitsmaßnahmen:**
- **Rate Limiting**: Pausiert automatisch bei zu vielen API-Anfragen (35/40)
- **Optimistic Locking**: Bricht ab wenn jemand anderes das Produkt gleichzeitig ändert
- **Write Verification**: Liest das Produkt nach dem Speichern nochmal und vergleicht
- **Concurrency Guard**: Verhindert parallele Schreibvorgänge
- **HTML-Sanitizer**: Entfernt alle gefährlichen HTML-Tags und Attribute
        """)

    with st.expander("Dateistruktur & Technische Architektur"):
        st.markdown("""
```
ShopSEO Pro/
├── app.py                 # Streamlit UI (dieser Bildschirm)
├── shopify_client.py      # Shopify Admin REST API Wrapper
├── seo_analyzer.py        # Live-Seiten-Crawler + SEO-Analyse
├── ai_engine.py           # KI-Integration (Claude/OpenRouter)
├── keyword_research.py    # Google Suggest Keyword-Recherche
├── ranking_tracker.py     # Google Search Console Integration
├── backup_store.py        # SQLite Backup/Rollback-System
├── html_sanitizer.py      # HTML-Validierung & Sanitisierung
├── models.py              # Pydantic Datenmodelle
├── config.py              # Konfiguration (.env Management)
├── requirements.txt       # Python-Abhängigkeiten
└── .env                   # Credentials (nicht im Repo!)
```

**Automatisch generierte Dateien:**
- `backups.db` — SQLite Datenbank mit Backup-Snapshots
- `ranking_history.json` — Lokaler Ranking-Verlauf
        """)

    with st.expander("Häufige Probleme & Lösungen"):
        st.markdown("""
**"Shopify: Nicht verbunden"**
- Prüfe ob die Store URL korrekt ist (z.B. `mein-shop` oder `mein-shop.myshopify.com`)
- Prüfe ob der Access Token gültig ist und die nötigen Berechtigungen hat
- Benötigte Scopes: `read_products`, `write_products`, `read_content`, `write_content`

**"Fehler bei der KI-Optimierung"**
- Prüfe ob dein API-Key korrekt ist
- Bei OpenRouter: Prüfe ob das gewählte Modell verfügbar ist und genug Guthaben vorhanden ist
- Versuche ein anderes Modell (z.B. Claude Sonnet statt Gemini)

**"KI-Antwort konnte nicht als JSON interpretiert werden"**
- Manche Modelle geben kein sauberes JSON zurück
- Empfehlung: Claude-Modelle funktionieren am zuverlässigsten
- Einfach nochmal auf "SEO optimieren" klicken — oft klappt es beim 2. Versuch

**"SEO-Score ist 0"**
- Die Storefront URL muss korrekt sein (öffentliche URL des Shops)
- Prüfe ob die Seite öffentlich erreichbar ist (nicht passwortgeschützt)

**Keyword-Recherche dauert sehr lange**
- Die Alphabet-Expansion macht 26 Google-Anfragen — das dauert ca. 5-10 Sekunden
- Ergebnisse werden gecacht, beim 2. Mal ist es schneller
        """)

    # Version info
    st.markdown("---")
    st.markdown(
        '<div class="app-footer">'
        'ShopSEO Pro v2.1 — KI-gestützte SEO-Optimierung für Shopify'
        '</div>',
        unsafe_allow_html=True,
    )


def _perform_rollback(backup: BackupEntry) -> None:
    """Roll back a single backup entry."""
    cfg: AppConfig | None = st.session_state.get("config")
    if not cfg:
        st.error("Keine Konfiguration vorhanden.")
        return

    if st.session_state.get("write_lock"):
        st.warning("Ein Schreibvorgang läuft bereits.")
        return

    st.session_state["write_lock"] = True
    try:
        backup_store = BackupStore()
        restore_data = backup_store.get_restore_data(backup.id)
        if not restore_data:
            st.error("Keine Wiederherstellungsdaten gefunden.")
            return

        collection_type = restore_data.pop("collection_type", "custom")
        seo_data = SEOData(**restore_data)
        client = ShopifyClient(cfg)

        resource_type_str = backup.resource_type
        with st.spinner("Stelle vorherigen Zustand wieder her..."):
            if resource_type_str == ResourceType.PRODUCT.value:
                client.update_product(backup.resource_id, seo_data)
            elif resource_type_str == ResourceType.COLLECTION.value:
                client.update_collection(
                    backup.resource_id, collection_type, seo_data
                )
            else:
                client.update_page(backup.resource_id, seo_data)

        backup_store.mark_rolled_back(backup.id)
        st.success(f"Rollback von Backup #{backup.id} erfolgreich!")
        st.rerun()

    except Exception as exc:
        st.error(f"Fehler beim Rollback: {exc}")
    finally:
        st.session_state["write_lock"] = False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Application entry point."""
    # Init session state defaults
    for key, default in [
        ("authenticated", False),
        ("connection_ok", False),
        ("gsc_connected", False),
        ("write_lock", False),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    # Auth check — including session expiry
    if not st.session_state.get("authenticated"):
        _show_login()
        return

    # Session expiry: auto-logout after 24 hours
    auth_time = st.session_state.get("_auth_time", 0)
    if auth_time and (time.time() - auth_time > _SESSION_MAX_AGE_SECONDS):
        st.session_state["authenticated"] = False
        st.session_state.pop("_auth_time", None)
        st.info("Sitzung abgelaufen — bitte erneut anmelden.")
        _show_login()
        return

    # Sidebar
    _render_sidebar()

    # Main content
    st.markdown(
        '<h1 class="app-title">ShopSEO Pro</h1>',
        unsafe_allow_html=True,
    )

    tab_dashboard, tab_seo, tab_batch, tab_rankings, tab_backups, tab_help = st.tabs(
        ["Dashboard", "SEO-Optimierung", "Batch-Analyse", "Google Rankings", "Backup-Verlauf", "Hilfe & Anleitung"]
    )

    with tab_dashboard:
        _render_tab_dashboard()

    with tab_seo:
        _render_tab_seo()

    with tab_batch:
        _render_tab_batch()

    with tab_rankings:
        _render_tab_rankings()

    with tab_backups:
        _render_tab_backups()

    with tab_help:
        _render_tab_help()


if __name__ == "__main__":
    main()
