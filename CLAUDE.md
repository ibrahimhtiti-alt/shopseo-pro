# ShopSEO Pro — Projekt-Kontext für Claude Code

## Was ist das?
KI-gestützte SEO-Optimierung für Shopify-Stores. Streamlit-App mit Docker-Deployment auf VPS.

## Techstack
- **Python 3.14** (lokal), **Python 3.12** (Docker)
- **Streamlit 1.55.0** — Web-UI
- **Shopify Admin REST API** (Version 2025-01)
- **KI-Provider:** OpenRouter (Gemini, Claude, GPT) oder Anthropic direkt
- **SQLite** — Backup-Datenbank
- **Docker + docker-compose** — Deployment
- **GitHub:** Private oder Public Repository (keine Credentials committen!)

## Architektur & Dateien

| Datei | Zweck |
|-------|-------|
| `app.py` | Haupt-UI (~3000 Zeilen), 5 Tabs: SEO-Optimierung, Batch-Analyse, Google Rankings, Backup-Verlauf, Hilfe |
| `ai_engine.py` | SEOEngine — KI-Integration (Anthropic + OpenRouter), Prompt-Bau, JSON-Parsing, Compliance-Check |
| `config.py` | AppConfig — lädt aus .env-Datei ODER os.environ (Docker-kompatibel) |
| `shopify_client.py` | ShopifyClient — REST API, CRUD für Products/Collections/Pages, Metafields, Rate-Limiting |
| `seo_analyzer.py` | SEOAnalyzer — crawlt Live-Seite, prüft 12 SEO-Faktoren, Score 0-100 |
| `backup_store.py` | BackupStore (SQLite) — Before/After Snapshots, Rollback, Optimierungs-Tracking |
| `html_sanitizer.py` | HTMLSanitizer — erlaubte Tags/Attribute, Cleanup, semantische HTML5-Tags |
| `keyword_research.py` | Keyword-Recherche via Google Suggest API |
| `ranking_tracker.py` | Google Search Console Integration |
| `models.py` | Pydantic-Modelle: SEOData, SEOAnalysis, ImageSEO, ShopifyProduct/Collection/Page |

## Wichtige Patterns

### Konfiguration
- `.env` Datei wird NIEMALS committed (`.gitignore`)
- `config.py` liest zuerst `.env`-Datei, dann `os.environ` als Fallback (für Docker)
- Login: `ADMIN_USERNAME` + `ADMIN_PASSWORD_HASH` (SHA256) in `.env` — ohne diese ist Login deaktiviert

### Optimierungs-Flow
1. Produkt laden (Shopify API) → `ShopifyProduct.to_seo_data()` → `SEOData`
2. SEO analysieren → `SEOAnalyzer.analyze_page()` → `SEOAnalysis`
3. Keywords recherchieren → `research_keywords()`
4. KI optimieren → `SEOEngine.generate_seo_suggestions()` → neues `SEOData`
5. HTML sanitizen → `HTMLSanitizer.full_check()`
6. Backup erstellen → `BackupStore.create_backup()`
7. In Shopify schreiben → `ShopifyClient.update_product()`
8. After-State speichern → `BackupStore.update_after_state()`

### Smart-Automation (Batch-Tab)
- Produkte per Checkbox auswählen
- "Ausgewählte optimieren" → KI optimiert alle
- Freigabe-Queue: Produkt für Produkt mit Vorher/Nachher-Vergleich
- 3 Aktionen: Freigeben (publiziert sofort) / Überspringen / Ablehnen
- Session-State Keys: `_smart_queue`, `_smart_queue_index`, `_smart_queue_phase`

### Bulk-Optimierung
- "Alle optimieren (KI)" → verarbeitet alle gefilterten Produkte
- Ergebnisse in `_bulk_results` Session-State
- Einzeln oder alle auf einmal freigeben via `_publish_bulk_items()`

## Deployment

### Lokal
```
cd "C:\Users\L0cky\Documents\Seo Programm"
streamlit run app.py
```

### VPS
- **OS:** Ubuntu 24.04
- **Projekt-Pfad:** /opt/shopseo-pro
- **Docker Container:** shopseo-pro
- VPS-IP und App-URL stehen in der lokalen `ANLEITUNG-FÜR-IBO.txt` (nicht im Repo)

### Update-Workflow
```bash
# Lokal: committen + pushen
git add . && git commit -m "Beschreibung" && git push

# VPS: updaten
cd /opt/shopseo-pro && git pull && docker compose up -d --build
```

## Zugangsdaten
- Alle Credentials stehen in der lokalen `.env` Datei (nie committen!)
- Login-Daten und API-Keys: siehe `ANLEITUNG-FÜR-IBO.txt` (nicht im Repo)
- Google Credentials JSON: Pfad wird in `.env` unter `GOOGLE_CREDENTIALS_PATH` konfiguriert

## Bekannte Besonderheiten
- **Gemini JSON-Bug:** Gemini gibt manchmal unescapte Newlines in JSON-Strings zurück → `ai_engine.py` hat einen Character-by-Character JSON-Repair (Strategy 3 in `_extract_balanced_json`)
- **Dark Mode:** Alle CSS-Farben nutzen `rgba()` statt hardcoded Hex-Werte
- **Body HTML Vorschau:** Nutzt `st.components.v1.html()` (iframe) statt `st.markdown(unsafe_allow_html=True)` weil Streamlit HTML filtert
- **Ressourcentyp-spezifische SEO-Schwellen:** Produkte 300 Wörter, Kategorien 150, Seiten 200
- **TPD2/TabakerzG Compliance:** KI-Prompts enthalten deutsche Rechtsvorschriften für Nikotinprodukte
- **Anleitung für Benutzer:** Siehe `ANLEITUNG-FÜR-IBO.txt` im Projektordner
