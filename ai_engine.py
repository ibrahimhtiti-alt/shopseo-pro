# -*- coding: utf-8 -*-
"""Claude API integration for generating SEO-optimized content with German legal compliance."""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

import anthropic
import requests as http_requests

from models import (
    SEOData,
    SEOAnalysis,
    ImageSEO,
    ResourceType,
    ComplianceWarning,
    AIEngineError,
    AIParseError,
    RankingData,
)


class SEOEngine:
    """Generates SEO suggestions via the Anthropic Claude API.

    All generated content targets the German vape / e-cigarette market
    (myvapez.de) and is checked against TabakerzG, TPD2, JuSchG, HWG and UWG.
    """

    SYSTEM_PROMPT: str = (
        "Du bist ein erfahrener SEO-Spezialist für E-Commerce im deutschen Vape- und E-Zigaretten-Markt.\n"
        "Du optimierst Inhalte für den Online-Shop myvapez.de.\n"
        "\n"
        "RECHTLICHE PFLICHTEN — Diese Regeln darfst du NIEMALS verletzen:\n"
        "\n"
        "1. TabakerzG §§19-22: KEINE gesundheitsbezogenen Werbeversprechen.\n"
        '   VERBOTEN: "gesünder", "weniger schädlich", "Rauchentwöhnung", "harmlos", "sicher", "unbedenklich", "risikofrei"\n'
        "\n"
        "2. TPD2 (EU-Tabakrichtlinie): Bei nikotinhaltigen Produkten MUSS folgender Warnhinweis im Content enthalten sein:\n"
        '   "Dieses Produkt enthält Nikotin – einen Stoff, der sehr stark abhängig macht."\n'
        "\n"
        '3. JuSchG §10: Produkte sind ab 18 Jahren. Erwähne IMMER die Altersverifizierung ("Ab 18", "Kein Verkauf an Minderjährige").\n'
        "\n"
        "4. TabakerzG §19: KEINE auffordernde oder verführerische Werbung.\n"
        '   VERBOTEN: "Jetzt ausprobieren", "Teste jetzt", "Erlebe den Geschmack", "Probiere"\n'
        '   ERLAUBT: "Jetzt bestellen", "Zum Produkt", "Mehr erfahren", "Details ansehen"\n'
        "\n"
        "5. HWG (Heilmittelwerbegesetz): KEINE therapeutischen oder gesundheitlichen Claims.\n"
        "\n"
        "6. UWG (Wettbewerbsrecht): Alle Produkteigenschaften müssen sachlich und korrekt beschrieben werden.\n"
        "\n"
        "SEO-RICHTLINIEN (ZEICHENLIMITS SIND PFLICHT — NICHT ÜBERSCHREITEN!):\n"
        "- SEO-Titel: EXAKT 50-60 Zeichen (Leerzeichen zählen mit!). Hauptkeyword am Anfang.\n"
        "  ZÄHLE DIE ZEICHEN BEVOR DU ANTWORTEST! Über 60 = UNGÜLTIG für Google!\n"
        "- Meta-Description: EXAKT 130-155 Zeichen (Leerzeichen zählen mit!). Sachlicher Call-to-Action.\n"
        "  ZÄHLE DIE ZEICHEN BEVOR DU ANTWORTEST! Über 160 = wird von Google abgeschnitten!\n"
        "- H1: Klar, keyword-relevant, einzigartig, max 70 Zeichen\n"
        "- H2-Überschriften: Strukturiert mit Longtail-Keywords\n"
        "- Content: Informativ, natürliche Keyword-Integration, mindestens 200 Wörter für Produkte\n"
        "- Bild-Alt-Texte: Beschreibend, keyword-relevant, EXAKT 50-125 Zeichen pro Alt-Text\n"
        "\n"
        "CONTENT-STRUKTUR (E-E-A-T Optimierung):\n"
        "- Schreibe aus Expertenperspektive mit Fachwissen über Vape-Produkte\n"
        "- Verwende kurze Absätze (2-3 Sätze pro Paragraph) für bessere Lesbarkeit\n"
        "- Strukturiere mit H2-Überschriften: Produktbeschreibung, Technische Details, Lieferumfang, FAQ\n"
        "- Erstelle einen FAQ-Bereich mit 2-3 häufigen Fragen als H2 (nutze Frage-Keywords)\n"
        "- Empfehle interne Verlinkung zu verwandten Produkten/Kategorien im Text\n"
        "- Nutze Listen (<ul>/<ol>) für Spezifikationen und Features\n"
        "- Verwende <strong> für wichtige Keywords (nicht übertreiben, max 2-3 pro Absatz)\n"
        "- Füge am Ende einen kurzen Vertrauensabschnitt hinzu (z.B. Versandinfo, Qualitätsversprechen)\n"
        "\n"
        "WICHTIG: Zähle bei seo_title und meta_description JEDEN Buchstaben, JEDES Leerzeichen,\n"
        "JEDES Sonderzeichen. Wenn dein seo_title 61 Zeichen hat, KÜRZE ihn!\n"
        "\n"
        "PFLICHTFELDER — ALLE Felder müssen ausgefüllt sein, KEINES darf leer bleiben:\n"
        "- seo_title: PFLICHT (50-60 Zeichen)\n"
        "- meta_description: PFLICHT (130-155 Zeichen)\n"
        "- h1: PFLICHT\n"
        "- body_html: PFLICHT — Generiere IMMER vollständigen HTML-Content mit mindestens 200 Wörtern!\n"
        "  Enthält <h2>, <p>, <ul>, <strong> Tags. NIEMALS leer lassen!\n"
        "- images: PFLICHT — Generiere für JEDES Bild einen suggested_alt Text (50-125 Zeichen)!\n"
        "  Verwende die exakten image_id Werte aus der Bilderliste. NIEMALS leer lassen!\n"
        "\n"
        "Antworte IMMER NUR mit JSON (kein Markdown, kein ```json, kein Text drumherum):\n"
        "{\n"
        '  "seo_title": "50-60 Zeichen, NICHT mehr!",\n'
        '  "meta_description": "130-155 Zeichen, NICHT mehr!",\n'
        '  "h1": "Optimierte Hauptüberschrift",\n'
        '  "h2_list": ["Unterüberschrift 1", "Unterüberschrift 2"],\n'
        '  "body_html": "<h2>Überschrift</h2><p>Vollständiger HTML-Content mit min. 200 Wörtern...</p>",\n'
        '  "images": [\n'
        '    {"image_id": 123, "suggested_alt": "Beschreibender Alt-Text 50-125 Zeichen"}\n'
        "  ]\n"
        "}"
    )

    # ------------------------------------------------------------------
    # Compliance helpers – forbidden terms and patterns
    # ------------------------------------------------------------------

    _HEALTH_TERMS: list[str] = [
        "gesund",
        "harmlos",
        "sicher",
        "unbedenklich",
        "risikofrei",
        "heilend",
        "therapeutisch",
        "weniger schädlich",
        "gesünder",
        "rauchentwöhnung",
    ]

    _SOLICITATION_PATTERN: re.Pattern[str] = re.compile(
        r"(?:jetzt\s+)?(?:ausprobier|probier|teste|erlebe|genieße|entdecke\s+den\s+geschmack)",
        re.IGNORECASE,
    )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    # Verfügbare Modelle pro Provider
    AVAILABLE_MODELS: dict[str, dict[str, str]] = {
        "anthropic": {
            "Claude Sonnet 4": "claude-sonnet-4-20250514",
            "Claude Haiku 3.5": "claude-3-5-haiku-20241022",
        },
        "openrouter": {
            "Claude Sonnet 4.6 (Anthropic)": "anthropic/claude-sonnet-4.6",
            "Claude Opus 4.6 (Anthropic)": "anthropic/claude-opus-4.6",
            "GPT-5.4 Pro (OpenAI)": "openai/gpt-5.4-pro",
            "GPT-5.4 (OpenAI)": "openai/gpt-5.4",
            "GPT-5.3 Chat (OpenAI)": "openai/gpt-5.3-chat",
            "Gemini 3.1 Pro (Google)": "google/gemini-3.1-pro-preview",
            "Gemini 3.1 Flash (Google)": "google/gemini-3.1-flash-image-preview",
            "Gemini 3 Flash (Google)": "google/gemini-3-flash-preview",
        },
    }

    def __init__(self, api_key: str, provider: str = "anthropic", model_id: str = "") -> None:
        self.provider = provider.lower()
        self.api_key = api_key
        if self.provider == "openrouter":
            self.client = None  # OpenRouter nutzt requests direkt
            self.model = model_id or "anthropic/claude-sonnet-4.6"
        else:
            self.client = anthropic.Anthropic(api_key=api_key, timeout=180.0)
            self.model = model_id or "claude-sonnet-4-20250514"
        # Gemini und andere Modelle brauchen mehr Tokens für vollständigen Body-HTML
        self.max_tokens = 8192

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_seo_suggestions(
        self,
        resource_type: ResourceType,
        current_data: SEOData,
        title: str,
        analysis: Optional[SEOAnalysis] = None,
        ranking_data: Optional[list[RankingData]] = None,
        extra_context: Optional[dict] = None,
    ) -> SEOData:
        """Generate SEO-optimised content for a Shopify resource.

        Returns a new :class:`SEOData` instance with AI suggestions.
        Raises :class:`AIEngineError` on API or parsing failures.
        """
        user_prompt = self._build_prompt(
            resource_type=resource_type,
            current_data=current_data,
            title=title,
            analysis=analysis,
            ranking_data=ranking_data,
            extra_context=extra_context,
        )

        if self.provider == "openrouter":
            response_text = self._call_openrouter(user_prompt)
        else:
            response_text = self._call_anthropic(user_prompt)

        result = self._parse_response(response_text, current_data)

        # Auto-fix: If title or description exceed limits, ask AI to shorten
        title_len = len(result.seo_title)
        desc_len = len(result.meta_description)

        if title_len > 60 or desc_len > 160:
            logger.warning(
                "KI-Antwort überschreitet Limits: Titel=%d, Meta=%d. Starte Korrektur...",
                title_len, desc_len,
            )
            fix_prompt = self._build_fix_prompt(result.seo_title, result.meta_description)
            try:
                if self.provider == "openrouter":
                    fix_response = self._call_openrouter(fix_prompt)
                else:
                    fix_response = self._call_anthropic(fix_prompt)

                fix_data = self._extract_balanced_json(fix_response.strip().strip("`").strip())
                if fix_data is None:
                    # Try stripping markdown fences
                    cleaned_fix = fix_response.strip()
                    if cleaned_fix.startswith("```"):
                        nl = cleaned_fix.find("\n")
                        if nl != -1:
                            cleaned_fix = cleaned_fix[nl + 1:]
                        if cleaned_fix.rstrip().endswith("```"):
                            cleaned_fix = cleaned_fix.rstrip()[:-3].rstrip()
                    fix_data = self._extract_balanced_json(cleaned_fix)

                if fix_data:
                    new_title = fix_data.get("seo_title", result.seo_title)
                    new_desc = fix_data.get("meta_description", result.meta_description)
                    if len(new_title) <= 60:
                        result.seo_title = new_title
                    if len(new_desc) <= 160:
                        result.meta_description = new_desc
                    logger.info(
                        "Korrektur erfolgreich: Titel=%d, Meta=%d",
                        len(result.seo_title), len(result.meta_description),
                    )
            except Exception as fix_exc:
                logger.warning("Korrektur fehlgeschlagen: %s. Originaltext wird verwendet.", fix_exc)

        # Auto-fix: If body_html is empty, retry with explicit body-only prompt
        has_empty_body = not result.body_html or len(result.body_html.strip()) < 50
        has_empty_alts = (
            current_data.images
            and all(
                not img.suggested_alt or img.suggested_alt == img.current_alt
                for img in result.images
            )
        )

        if has_empty_body or has_empty_alts:
            logger.warning(
                "KI-Antwort unvollständig: body_html=%s, images_alt=%s. Starte Nachgenerierung...",
                "leer" if has_empty_body else "OK",
                "leer" if has_empty_alts else "OK",
            )
            retry_prompt = self._build_missing_fields_prompt(
                title=title,
                current_data=current_data,
                result=result,
                need_body=has_empty_body,
                need_images=has_empty_alts,
            )
            try:
                if self.provider == "openrouter":
                    retry_response = self._call_openrouter(retry_prompt)
                else:
                    retry_response = self._call_anthropic(retry_prompt)

                retry_data = self._parse_response(retry_response, current_data)

                if has_empty_body and retry_data.body_html and len(retry_data.body_html.strip()) > 50:
                    result.body_html = retry_data.body_html
                    logger.info("Body-HTML nachgeneriert: %d Zeichen", len(result.body_html))

                if has_empty_alts and retry_data.images:
                    for retry_img in retry_data.images:
                        if retry_img.suggested_alt and retry_img.suggested_alt != retry_img.current_alt:
                            for orig_img in result.images:
                                if orig_img.image_id == retry_img.image_id:
                                    orig_img.suggested_alt = retry_img.suggested_alt
                    logger.info("Bild-Alt-Texte nachgeneriert.")

            except Exception as retry_exc:
                logger.warning("Nachgenerierung fehlgeschlagen: %s", retry_exc)

        return result

    def _call_anthropic(self, user_prompt: str) -> str:
        """Sende Anfrage direkt an die Anthropic API."""
        logger.info("Sende Anfrage an Anthropic (%s)...", self.model)
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except anthropic.AuthenticationError as exc:
            raise AIEngineError(
                "Anthropic-API-Authentifizierung fehlgeschlagen. Bitte prüfe den API-Key."
            ) from exc
        except anthropic.RateLimitError as exc:
            raise AIEngineError(
                "API-Ratelimit erreicht. Bitte versuche es später erneut."
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise AIEngineError(
                "Verbindung zur API fehlgeschlagen. Bitte prüfe deine Internetverbindung."
            ) from exc
        except anthropic.APIError as exc:
            raise AIEngineError(f"Anthropic-API-Fehler: {exc}") from exc

        return response.content[0].text

    def _call_openrouter(self, user_prompt: str) -> str:
        """Sende Anfrage an OpenRouter (OpenAI-kompatibles Format)."""
        logger.info("Sende Anfrage an OpenRouter (%s)...", self.model)
        try:
            resp = http_requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://www.myvapez.de",
                    "X-Title": "SEO Tool myvapez.de",
                },
                json={
                    "model": self.model,
                    "max_tokens": self.max_tokens,
                    "messages": [
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                },
                timeout=180,
            )
        except http_requests.exceptions.ConnectionError as exc:
            raise AIEngineError(
                "Verbindung zu OpenRouter fehlgeschlagen. Bitte prüfe deine Internetverbindung."
            ) from exc
        except http_requests.exceptions.Timeout as exc:
            raise AIEngineError(
                "OpenRouter-Anfrage hat zu lange gedauert (Timeout). Bitte erneut versuchen."
            ) from exc

        if resp.status_code == 401:
            raise AIEngineError(
                "OpenRouter-Authentifizierung fehlgeschlagen. Bitte prüfe den API-Key."
            )
        if resp.status_code == 429:
            raise AIEngineError(
                "OpenRouter-Ratelimit erreicht. Bitte versuche es später erneut."
            )
        if resp.status_code != 200:
            try:
                error_data = resp.json()
                error_msg = error_data.get("error", {}).get("message", resp.text[:200])
            except Exception:
                error_msg = resp.text[:200]
            raise AIEngineError(f"OpenRouter-Fehler ({resp.status_code}): {error_msg}")

        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]

            # Some models return content as a list of blocks (e.g., with thinking)
            if isinstance(content, list):
                # Extract only text blocks, skip thinking/reasoning blocks
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") not in ("thinking", "reasoning"):
                            text_parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        text_parts.append(block)
                content = "\n".join(text_parts)

            if not content or not content.strip():
                raise AIEngineError(
                    "OpenRouter hat eine leere Antwort zurückgegeben. "
                    "Bitte versuche es erneut oder wähle ein anderes Modell."
                )

            logger.info("OpenRouter Antwort-Länge: %d Zeichen", len(content))
            return content

        except (KeyError, IndexError) as exc:
            logger.error("OpenRouter Antwortformat: %s", str(data)[:500])
            raise AIEngineError(
                f"Unerwartetes Antwortformat von OpenRouter. Antwort: {str(data)[:300]}"
            ) from exc

    def check_compliance(
        self,
        text: str,
        is_nicotine_product: bool = True,
    ) -> list[ComplianceWarning]:
        """Scan *text* for regulatory compliance violations.

        Returns an empty list when the text is fully compliant.
        """
        warnings: list[ComplianceWarning] = []
        text_lower = text.lower()

        # 1. Verbotene Gesundheitsbegriffe (TabakerzG §19)
        found_health: list[str] = [
            term for term in self._HEALTH_TERMS if term in text_lower
        ]
        if found_health:
            warnings.append(
                ComplianceWarning(
                    category="Gesundheitsbezogene Werbung",
                    message="Verbotene Begriffe gefunden (TabakerzG §19)",
                    found_terms=found_health,
                )
            )

        # 2. Auffordernde Werbung (TabakerzG §19)
        solicitation_matches = self._SOLICITATION_PATTERN.findall(text_lower)
        if solicitation_matches:
            warnings.append(
                ComplianceWarning(
                    category="Auffordernde Werbung",
                    message="Auffordernde oder verführerische Werbeausdrücke gefunden (TabakerzG §19)",
                    found_terms=solicitation_matches,
                )
            )

        # 3. Fehlender TPD2-Warnhinweis (nur bei Nikotinprodukten)
        if is_nicotine_product:
            if "nikotin" not in text_lower and "abhängig" not in text_lower:
                warnings.append(
                    ComplianceWarning(
                        category="TPD2-Warnhinweis",
                        message="Der gesetzlich vorgeschriebene Nikotin-Warnhinweis fehlt.",
                        found_terms=[],
                    )
                )

        # 4. Fehlender Altershinweis (JuSchG §10)
        if (
            "18" not in text
            and "volljährig" not in text_lower
            and "minderjährig" not in text_lower
        ):
            warnings.append(
                ComplianceWarning(
                    category="Jugendschutz",
                    message="Kein Altershinweis (Ab 18) gefunden (JuSchG §10)",
                    found_terms=[],
                )
            )

        return warnings

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_missing_fields_prompt(
        title: str,
        current_data: "SEOData",
        result: "SEOData",
        need_body: bool,
        need_images: bool,
    ) -> str:
        """Build a prompt to generate missing body_html and/or image alt texts."""
        parts = [
            f"NACHGENERIERUNG für das Produkt: {title}\n"
            f"SEO-Titel: {result.seo_title}\n"
            f"H1: {result.h1}\n"
        ]

        if need_body:
            parts.append(
                "\nDu MUSST jetzt den body_html generieren! Der Content war bei deiner letzten Antwort leer.\n"
                "Generiere vollständigen HTML-Content mit MINDESTENS 200 Wörtern.\n"
                "Verwende <h2>, <p>, <ul>, <strong> Tags.\n"
                "Strukturiere: Produktbeschreibung, Technische Details, FAQ.\n"
                f"Aktueller Content als Referenz: {current_data.body_html[:3000] if current_data.body_html else 'Kein Inhalt vorhanden'}\n"
            )

        if need_images and current_data.images:
            img_lines = ["\nDu MUSST jetzt für JEDES Bild einen Alt-Text generieren! Die Alt-Texte waren leer.\n"]
            for img in current_data.images:
                alt = img.current_alt or "Fehlt"
                img_lines.append(f"- Bild-ID {img.image_id}: Aktueller Alt: '{alt}' (URL: {img.image_src})")
            img_lines.append("\nJeder Alt-Text muss 50-125 Zeichen lang sein, beschreibend und keyword-relevant.\n")
            parts.append("\n".join(img_lines))

        parts.append(
            "\nAntworte NUR mit JSON:\n"
            "{\n"
            '  "seo_title": "' + result.seo_title + '",\n'
            '  "meta_description": "' + result.meta_description + '",\n'
            '  "h1": "' + result.h1 + '",\n'
            '  "h2_list": [],\n'
            '  "body_html": "<h2>...</h2><p>VOLLSTÄNDIGER HTML-Content hier...</p>",\n'
            '  "images": [{"image_id": 123, "suggested_alt": "Alt-Text hier"}]\n'
            "}"
        )

        return "\n".join(parts)

    @staticmethod
    def _build_fix_prompt(seo_title: str, meta_description: str) -> str:
        """Build a short prompt to fix over-length title/description."""
        parts = []
        if len(seo_title) > 60:
            parts.append(
                f'Der SEO-Titel ist {len(seo_title)} Zeichen lang (Maximum: 60).\n'
                f'Aktueller Titel: "{seo_title}"\n'
                f'KÜRZE ihn auf EXAKT 50-60 Zeichen. Behalte das Hauptkeyword.'
            )
        if len(meta_description) > 160:
            parts.append(
                f'Die Meta-Description ist {len(meta_description)} Zeichen lang (Maximum: 160).\n'
                f'Aktuelle Description: "{meta_description}"\n'
                f'KÜRZE sie auf EXAKT 130-155 Zeichen. Behalte die wichtigsten Keywords und den Call-to-Action.'
            )

        return (
            "KORREKTUR-AUFGABE: Die folgenden SEO-Texte sind zu lang. Kürze sie EXAKT auf die angegebene Länge.\n"
            "Zähle JEDEN Buchstaben und JEDES Leerzeichen!\n\n"
            + "\n\n".join(parts) +
            "\n\nAntworte NUR mit JSON (kein Markdown, kein Text drumherum):\n"
            '{"seo_title": "gekürzt 50-60 Zeichen", "meta_description": "gekürzt 130-155 Zeichen"}'
        )

    def _build_prompt(
        self,
        resource_type: ResourceType,
        current_data: SEOData,
        title: str,
        analysis: Optional[SEOAnalysis],
        ranking_data: Optional[list[RankingData]],
        extra_context: Optional[dict],
    ) -> str:
        """Assemble a detailed German prompt tailored to *resource_type*."""

        extra = extra_context or {}

        # --- resource-specific header ------------------------------------
        if resource_type == ResourceType.PRODUCT:
            header = (
                "Optimiere die SEO für folgendes Produkt im Vape-Shop myvapez.de:\n"
                "\n"
                f"Produktname: {title}\n"
                f"Kategorie: {extra.get('product_type', '—')}\n"
                f"Marke: {extra.get('vendor', '—')}\n"
                f"Tags: {extra.get('tags', '—')}\n"
            )
        elif resource_type == ResourceType.COLLECTION:
            header = (
                "Optimiere die SEO für folgende Kategorie im Vape-Shop myvapez.de:\n"
                "\n"
                f"Kategoriename: {title}\n"
                f"Typ: {extra.get('collection_type', '—')}\n"
                "\n"
                "Fokus: Kategorie-übergreifende Keywords, breitere Suchbegriffe, "
                "informative Kategoriebeschreibung.\n"
            )
        else:  # PAGE
            header = (
                "Optimiere die SEO für folgende Seite im Vape-Shop myvapez.de:\n"
                "\n"
                f"Seitenname: {title}\n"
                "\n"
                "Fokus: Informationeller Content, Vertrauenssignale, "
                "E-E-A-T-Optimierung.\n"
            )

        # --- current state -----------------------------------------------
        word_count_str = ""
        if analysis:
            word_count_str = str(analysis.word_count)
        else:
            word_count_str = str(len(current_data.body_html.split())) if current_data.body_html else "0"

        body_preview = current_data.body_html[:10000] if current_data.body_html else "Kein Inhalt vorhanden"

        current_section = (
            "\nAKTUELLER STAND:\n"
            f"- SEO-Titel: {current_data.seo_title or 'Nicht gesetzt'}\n"
            f"- Meta-Description: {current_data.meta_description or 'Nicht gesetzt'}\n"
            f"- H1: {current_data.h1 or title}\n"
            f"- Wortanzahl Content: {word_count_str}\n"
            f"- Aktueller Content:\n{body_preview}\n"
        )

        # --- images ------------------------------------------------------
        images_section = ""
        if current_data.images:
            lines = [
                "\nBILDER — PFLICHT! Generiere für JEDES Bild einen neuen Alt-Text (50-125 Zeichen):"
                "\nVerwende die EXAKTEN image_id Werte! KEIN Bild darf fehlen!"
            ]
            for img in current_data.images:
                alt = img.current_alt or "Fehlt"
                lines.append(
                    f"- Bild-ID {img.image_id}: Aktueller Alt-Text: '{alt}' (URL: {img.image_src})"
                )
            example_imgs = ", ".join(
                f'{{"image_id": {img.image_id}, "suggested_alt": "Beschreibung 50-125 Zeichen"}}'
                for img in current_data.images[:2]
            )
            lines.append(f'\nBeispiel für images im JSON:\n  "images": [{example_imgs}]')
            images_section = "\n".join(lines) + "\n"

        # --- analysis ----------------------------------------------------
        analysis_section = ""
        if analysis:
            critical = [
                f"  • {issue.message}" for issue in analysis.issues if issue.severity == "critical"
            ]
            warns = [
                f"  • {issue.message}" for issue in analysis.warnings
            ]
            top_keywords = sorted(
                analysis.keyword_density.items(), key=lambda kv: kv[1], reverse=True
            )[:5]
            kw_str = ", ".join(f"'{kw}' ({pct:.1f}%)" for kw, pct in top_keywords) if top_keywords else "—"

            analysis_section = (
                "\nSEO-ANALYSE (behebe diese Probleme gezielt):\n"
                f"- SEO-Score: {analysis.score}/100\n"
                f"- Kritische Probleme:\n" + ("\n".join(critical) if critical else "  Keine") + "\n"
                f"- Warnungen:\n" + ("\n".join(warns) if warns else "  Keine") + "\n"
                f"- Aktuelle Keywords auf der Seite: {kw_str}\n"
                f"- Fehlende Bild-Alt-Texte: {analysis.missing_alt_images} von {analysis.total_images}\n"
                f"- Gesundheitswarnung vorhanden: {'Ja' if analysis.has_health_warning else 'Nein'}\n"
            )

            # --- Google keyword research ------------------------------------
            sk = analysis.suggested_keywords
            if sk:
                kw_lines = ["\nGOOGLE KEYWORD-RECHERCHE (echte Suchanfragen — NUTZE DIESE KEYWORDS!):"]
                if sk.get("buying"):
                    kw_lines.append(
                        "Kauf-Keywords (HÖCHSTE Priorität für SEO-Titel + Meta!): "
                        + ", ".join(f"'{kw}'" for kw in sk["buying"])
                    )
                if sk.get("primary"):
                    kw_lines.append(
                        "Primäre Keywords: "
                        + ", ".join(f"'{kw}'" for kw in sk["primary"])
                    )
                if sk.get("research"):
                    kw_lines.append(
                        "Vergleich/Test-Keywords (für Body-Content): "
                        + ", ".join(f"'{kw}'" for kw in sk["research"])
                    )
                if sk.get("longtail"):
                    kw_lines.append(
                        "Longtail-Keywords (für H2 und Body): "
                        + ", ".join(f"'{kw}'" for kw in sk["longtail"])
                    )
                if sk.get("questions"):
                    kw_lines.append(
                        "Frage-Keywords (als H2-Überschriften oder FAQ nutzen): "
                        + ", ".join(f"'{kw}'" for kw in sk["questions"])
                    )
                kw_lines.append(
                    "\nKEYWORD-STRATEGIE:"
                    "\n1. SEO-Titel: Das wichtigste Kauf-Keyword am ANFANG"
                    "\n2. Meta-Description: 2-3 Kauf-Keywords + Call-to-Action"
                    "\n3. H1: Hauptkeyword + Marke"
                    "\n4. H2-Überschriften: Longtail + Frage-Keywords"
                    "\n5. Body: Natürliche Integration aller Keywords (1-3% Dichte)"
                    "\n6. Alt-Texte: Produkt-Keywords + beschreibende Wörter"
                )
                analysis_section += "\n".join(kw_lines) + "\n"

        # --- ranking data ------------------------------------------------
        ranking_section = ""
        if ranking_data:
            lines = ["\nAKTUELLE GOOGLE-RANKINGS (stärke diese Keywords gezielt):"]
            for rd in ranking_data[:5]:
                lines.append(
                    f"- '{rd.keyword}': Position {rd.position:.1f}, "
                    f"{rd.clicks} Klicks, {rd.impressions} Impressionen"
                )
            ranking_section = "\n".join(lines) + "\n"

        return header + current_section + images_section + analysis_section + ranking_section

    @staticmethod
    def _extract_balanced_json(text: str) -> dict | None:
        """Find the first balanced ``{...}`` block and parse it as JSON.

        Uses a simple brace counter instead of a greedy regex so that
        trailing text after the JSON object does not get included.
        Falls back to progressively more aggressive extraction strategies.
        """
        start = text.find("{")
        if start == -1:
            return None

        # Strategy 1: Balanced brace counter
        depth = 0
        in_string = False
        escape_next = False

        for i in range(start, len(text)):
            ch = text[i]

            if escape_next:
                escape_next = False
                continue

            if ch == "\\":
                if in_string:
                    escape_next = True
                continue

            if ch == '"':
                in_string = not in_string
                continue

            if in_string:
                continue

            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        # Don't give up — try next strategy
                        break

        # Strategy 2: Find the LAST closing brace and try progressively shorter
        last_brace = text.rfind("}")
        if last_brace > start:
            candidate = text[start : last_brace + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        # Strategy 3: Try to repair common issues (unescaped newlines/tabs in strings)
        try:
            candidate = text[start : last_brace + 1] if last_brace > start else text[start:]
            # Replace problematic control characters inside JSON strings
            # Walk through the string and fix unescaped control chars inside quotes
            repaired_chars = []
            in_str = False
            esc = False
            for ch in candidate:
                if esc:
                    repaired_chars.append(ch)
                    esc = False
                    continue
                if ch == '\\' and in_str:
                    repaired_chars.append(ch)
                    esc = True
                    continue
                if ch == '"':
                    in_str = not in_str
                    repaired_chars.append(ch)
                    continue
                if in_str and ch == '\n':
                    repaired_chars.append('\\n')
                    continue
                if in_str and ch == '\r':
                    continue
                if in_str and ch == '\t':
                    repaired_chars.append('\\t')
                    continue
                repaired_chars.append(ch)
            repaired = "".join(repaired_chars)
            result = json.loads(repaired)
            if isinstance(result, dict):
                logger.info("JSON repariert (unescaped control chars in strings).")
                return result
        except (json.JSONDecodeError, Exception):
            pass

        # Strategy 4: Extract individual fields with regex as last resort
        try:
            data: dict = {}
            # Extract simple string fields
            for field in ("seo_title", "meta_description", "h1"):
                match = re.search(
                    rf'"{field}"\s*:\s*"((?:[^"\\]|\\.){{0,500}})"',
                    text,
                    re.DOTALL,
                )
                if match:
                    data[field] = match.group(1).replace("\\n", "\n").replace('\\"', '"')

            # Extract h2_list
            h2_match = re.search(
                r'"h2_list"\s*:\s*\[(.*?)\]',
                text,
                re.DOTALL,
            )
            if h2_match:
                h2_raw = h2_match.group(1)
                data["h2_list"] = re.findall(r'"((?:[^"\\]|\\.)*)"', h2_raw)

            # Extract body_html (greedy — between "body_html": " and the next top-level key)
            body_match = re.search(
                r'"body_html"\s*:\s*"(.*?)"(?:\s*,\s*"(?:images|seo_title|meta_description|h1|h2_list)"|\s*})',
                text,
                re.DOTALL,
            )
            if body_match:
                body = body_match.group(1).replace("\\n", "\n").replace('\\"', '"')
                data["body_html"] = body

            # Extract images array
            img_match = re.search(r'"images"\s*:\s*(\[.*?\])', text, re.DOTALL)
            if img_match:
                try:
                    data["images"] = json.loads(img_match.group(1))
                except json.JSONDecodeError:
                    data["images"] = []

            if data.get("seo_title") or data.get("h1"):
                logger.warning("JSON-Extraktion per Regex-Fallback (einzelne Felder).")
                return data
        except Exception:
            pass

        return None

    def _parse_response(self, response_text: str, current_data: SEOData) -> SEOData:
        """Parse the Claude JSON response into an :class:`SEOData` instance."""

        if not response_text or not response_text.strip():
            raise AIParseError(
                "Die KI hat eine leere Antwort zurückgegeben. "
                "Bitte versuche es erneut oder wähle ein anderes Modell."
            )

        logger.info("Rohe KI-Antwort (erste 500 Zeichen): %s", response_text[:500])

        # 0. Strip markdown code fences (```json ... ``` or ``` ... ```)
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            # Remove opening fence (```json or ```)
            first_newline = cleaned.find("\n")
            if first_newline != -1:
                cleaned = cleaned[first_newline + 1:]
            # Remove closing fence
            if cleaned.rstrip().endswith("```"):
                cleaned = cleaned.rstrip()[:-3].rstrip()

        # 1. Direct parse attempt
        data: dict | None = None
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # 2. Fallback – find the outermost balanced JSON object using a brace counter
        if data is None:
            data = self._extract_balanced_json(cleaned)

        # 3. Last resort – try on original text
        if data is None:
            data = self._extract_balanced_json(response_text)

        if data is None:
            # Log the full response for debugging
            logger.error("KI-Antwort konnte nicht geparst werden: %s", response_text[:2000])
            raise AIParseError(
                "Die KI-Antwort konnte nicht als JSON interpretiert werden.\n\n"
                f"**Rohe Antwort (Anfang):**\n```\n{response_text[:800]}\n```\n\n"
                "Bitte versuche es erneut oder wähle ein anderes Modell."
            )

        # 3. Map images – merge AI suggestions with current images
        current_images_map: dict[int, ImageSEO] = {
            img.image_id: img for img in current_data.images
        }

        ai_images: dict[int, str] = {}
        for img_entry in data.get("images", []):
            if isinstance(img_entry, dict) and "image_id" in img_entry:
                ai_images[img_entry["image_id"]] = img_entry.get("suggested_alt", "")

        merged_images: list[ImageSEO] = []
        for img in current_data.images:
            merged_images.append(
                ImageSEO(
                    image_id=img.image_id,
                    image_src=img.image_src,
                    current_alt=img.current_alt,
                    suggested_alt=ai_images.get(img.image_id, img.current_alt),
                )
            )

        # Truncate fields that exceed recommended limits (warn, don't crash)
        seo_title = data.get("seo_title", "") or ""
        meta_desc = data.get("meta_description", "") or ""

        if len(seo_title) > 60:
            logger.warning("KI-Titel zu lang (%d Zeichen), wird im UI markiert.", len(seo_title))
        if len(meta_desc) > 160:
            logger.warning("KI-Meta-Description zu lang (%d Zeichen), wird im UI markiert.", len(meta_desc))

        return SEOData(
            seo_title=seo_title,
            meta_description=meta_desc,
            h1=data.get("h1", "") or "",
            h2_list=data.get("h2_list", []) or [],
            body_html=data.get("body_html", "") or "",
            images=merged_images,
        )
