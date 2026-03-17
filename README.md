# SEO-Optimierung Tool für myvapez.de

## Beschreibung

Eine Streamlit-Webanwendung zur automatisierten SEO-Optimierung von Shopify-Stores.

### Funktionen

- **Shopify Admin API Integration** – Produkte, Kategorien und statische Seiten lesen und schreiben
- **Live-SEO-Analyse** – Öffentliche Seiten werden gecrawlt und mit einem SEO-Score bewertet
- **KI-gestützte SEO-Textgenerierung** – Optimierte Texte via Claude (Anthropic)
- **Deutsche Rechtskonformität** – Automatische Prüfung auf TabakerzG, TPD2, JuSchG
- **Alt-Text-Optimierung** – Alle Produktbilder erhalten suchmaschinenfreundliche Alt-Texte
- **Google Search Console Tracking** – Ranking-Entwicklung verfolgen
- **Backup & Rollback** – Alle Änderungen werden gesichert und können rückgängig gemacht werden
- **HTML-Sanitisierung** – Sichere Aufbereitung aller KI-generierten Inhalte vor dem Push

---

## Voraussetzungen

- Python 3.10+
- Shopify Store mit Admin API Access Token
- Anthropic API Key (Claude)
- Optional: Google Search Console Service Account

---

## Installation

```bash
# Repository klonen oder Dateien herunterladen
cd "Seo Programm"

# Virtuelle Umgebung erstellen
python -m venv .venv

# Aktivieren (Windows)
.venv\Scripts\activate

# Dependencies installieren
pip install -r requirements.txt
```

---

## Konfiguration

1. `.env.example` nach `.env` kopieren
2. Folgende Werte eintragen:

| Variable | Beschreibung |
|---|---|
| `SHOPIFY_STORE_URL` | `your-store.myshopify.com` |
| `SHOPIFY_ACCESS_TOKEN` | Admin API Token aus Shopify Admin → Settings → Apps → Develop apps |
| `ANTHROPIC_API_KEY` | Von [console.anthropic.com](https://console.anthropic.com) |
| `STOREFRONT_URL` | `https://www.dein-shop.de` (die öffentliche Shop-URL) |
| `GOOGLE_CREDENTIALS_PATH` | Pfad zur Service-Account JSON (optional) |

---

## Shopify Access Token erstellen

1. **Shopify Admin** → Settings → Apps and sales channels → Develop apps
2. **"Create an app"** → Name vergeben
3. **"Configure Admin API scopes"** → Folgende Scopes aktivieren:
   - `read_products`, `write_products`
   - `read_content`, `write_content` (für Pages)
   - `read_metafields`, `write_metafields` (für SEO-Felder)
   - `read_online_store_pages` (für Collections)
4. **"Install app"** → Admin API Access Token kopieren

---

## Google Search Console einrichten (optional)

1. **Google Cloud Console** → Neues Projekt erstellen
2. **"Search Console API"** aktivieren
3. **Service Account** erstellen → JSON-Key herunterladen
4. **Google Search Console** → Einstellungen → Nutzer und Berechtigungen → Service Account E-Mail hinzufügen
5. Pfad zur JSON-Datei in `.env` unter `GOOGLE_CREDENTIALS_PATH` eintragen

---

## Starten

```bash
streamlit run app.py
```

Login-Daten werden in der `.env` Datei konfiguriert (siehe Konfiguration).

> **Hinweis:** Standard-Passwort nach dem ersten Login unbedingt ändern!

---

## Nutzung

1. **Anmelden** → Credentials in der Sidebar eingeben → "Verbindung testen"
2. **Ressource wählen** → Produkt, Kategorie oder statische Seite auswählen
3. **SEO analysieren** → Live-Seite wird gecrawlt, SEO-Score wird berechnet
4. **SEO optimieren** → KI generiert optimierte Texte (rechtskonform)
5. **Prüfen & Bearbeiten** → Vorschläge im Dashboard überprüfen und anpassen
6. **Live schalten** → Änderungen nach Bestätigung in Shopify übernehmen

---

## Sicherheitsfeatures

- **Backup** vor jedem Schreibvorgang (SQLite)
- **Rollback** für alle Änderungen
- **HTML-Sanitisierung** aller KI-generierten Inhalte
- **Optimistic Locking** – verhindert Überschreiben gleichzeitiger Änderungen
- **Schreibverifizierung** – GET nach PUT zur Bestätigung
- **Rate Limiting** – respektiert Shopify API-Limits
- **Login-Schutz** für die Anwendung

---

## Rechtskonformität

Die KI-generierten Texte werden automatisch auf Einhaltung folgender Vorschriften geprüft:

| Gesetz | Prüfung |
|---|---|
| **TabakerzG §§19-22** | Keine gesundheitsbezogenen Werbeversprechen |
| **TPD2** | Pflicht-Warnhinweis für nikotinhaltige Produkte |
| **JuSchG §10** | Altersverifizierung (Ab 18) |
| **HWG** | Keine therapeutischen Claims |
| **UWG** | Sachlich korrekte Produktbeschreibungen |

---

## Projektstruktur

| Datei | Beschreibung |
|---|---|
| `app.py` | Haupt-Streamlit-Anwendung (UI, Navigation, Login) |
| `config.py` | Konfiguration und Umgebungsvariablen laden |
| `models.py` | Pydantic-Datenmodelle und Exceptions |
| `shopify_client.py` | Shopify Admin REST API Wrapper mit Rate Limiting |
| `seo_analyzer.py` | Live-Seiten-Crawler und SEO-Analyse mit BeautifulSoup |
| `ai_engine.py` | Claude API Integration zur SEO-Textgenerierung (rechtskonform) |
| `html_sanitizer.py` | HTML-Sanitisierung und Validierung für Shopify-Inhalte |
| `backup_store.py` | SQLite-basiertes Backup- und Rollback-System |
| `ranking_tracker.py` | Google Search Console Integration und Ranking-Verlauf |
| `requirements.txt` | Python-Abhängigkeiten |

---

## Lizenz

Private Nutzung – Nicht zur Weitergabe bestimmt.
