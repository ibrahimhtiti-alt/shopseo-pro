# -*- coding: utf-8 -*-
"""Google Search Console integration and local ranking history tracking."""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from models import RankingData


class RankingTracker:
    """Verwaltet die Verbindung zur Google Search Console und speichert
    lokale Ranking-Historien fuer die SEO-Analyse."""

    def __init__(self, site_url: str = "", credentials_path: str = ""):
        self.site_url = site_url.rstrip("/")  # e.g. "https://www.myvapez.de"
        self.credentials_path = credentials_path
        self.service = None  # Google API service object
        self._history_path = Path(__file__).resolve().parent / "ranking_history.json"
        self._connected = False

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> tuple[bool, str]:
        """Verbindung zur Google Search Console API herstellen."""
        if not self.credentials_path:
            return (False, "Kein Google-Credentials-Pfad konfiguriert.")

        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError:
            return (
                False,
                "Google-API-Bibliotheken nicht installiert. "
                "Bitte 'google-auth' und 'google-api-python-client' installieren.",
            )

        try:
            credentials = service_account.Credentials.from_service_account_file(
                self.credentials_path,
                scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
            )
            self.service = build("searchconsole", "v1", credentials=credentials)

            # Zugriff pruefen – verfuegbare Sites auflisten
            sites = self.service.sites().list().execute()
            site_urls = [s["siteUrl"] for s in sites.get("siteEntry", [])]

            # Pruefen, ob unsere Site erreichbar ist
            accessible = False
            from urllib.parse import urlparse

            # Normalisiere: www.myvapez.de → myvapez.de
            our_domain = urlparse(self.site_url).netloc.lower().removeprefix("www.")

            for url in site_urls:
                if self.site_url in url or url in self.site_url:
                    self.site_url = url  # Exakte URL aus GSC uebernehmen
                    accessible = True
                    break

            if not accessible:
                # Vergleiche ohne www und mit sc-domain:-Format
                for url in site_urls:
                    gsc_domain = url.lower().rstrip("/")
                    # Vergleich: https://myvapez.de == www.myvapez.de
                    if our_domain in gsc_domain or gsc_domain.endswith(our_domain):
                        self.site_url = url
                        accessible = True
                        break
                    # sc-domain:myvapez.de Format
                    if url.startswith("sc-domain:") and our_domain in url:
                        self.site_url = url
                        accessible = True
                        break

            if not accessible:
                return (
                    False,
                    f"Kein Zugriff auf {self.site_url} in der Search Console. "
                    f"Verfuegbare Sites: {', '.join(site_urls)}",
                )

            self._connected = True
            return (True, f"Verbunden mit Google Search Console: {self.site_url}")

        except FileNotFoundError:
            return (
                False,
                f"Credentials-Datei nicht gefunden: {self.credentials_path}",
            )
        except Exception as e:
            return (False, f"Search Console Verbindung fehlgeschlagen: {str(e)}")

    def is_connected(self) -> bool:
        """Gibt zurueck, ob eine aktive Verbindung zur Search Console besteht."""
        return self._connected

    # ------------------------------------------------------------------
    # Data retrieval
    # ------------------------------------------------------------------

    def get_page_rankings(
        self, page_url: str, days: int = 28
    ) -> list[RankingData]:
        """Ranking-Daten fuer eine bestimmte Seite aus der Search Console abfragen."""
        if not self._connected or not self.service:
            return []

        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=days)

        try:
            response = (
                self.service.searchanalytics()
                .query(
                    siteUrl=self.site_url,
                    body={
                        "startDate": start_date.isoformat(),
                        "endDate": end_date.isoformat(),
                        "dimensions": ["query"],
                        "dimensionFilterGroups": [
                            {
                                "filters": [
                                    {
                                        "dimension": "page",
                                        "operator": "equals",
                                        "expression": page_url,
                                    }
                                ]
                            }
                        ],
                        "rowLimit": 25,
                        "type": "web",
                    },
                )
                .execute()
            )

            results: list[RankingData] = []
            for row in response.get("rows", []):
                results.append(
                    RankingData(
                        url=page_url,
                        keyword=row["keys"][0],
                        position=row.get("position", 0.0),
                        clicks=row.get("clicks", 0),
                        impressions=row.get("impressions", 0),
                        ctr=row.get("ctr", 0.0),
                        date=end_date.isoformat(),
                    )
                )

            # Nach Impressionen absteigend sortieren
            results.sort(key=lambda r: r.impressions, reverse=True)
            return results

        except Exception:
            return []

    def get_top_keywords(
        self, page_url: str, limit: int = 10
    ) -> list[RankingData]:
        """Die wichtigsten Keywords fuer eine Seite zurueckgeben."""
        rankings = self.get_page_rankings(page_url)
        return rankings[:limit]

    # ------------------------------------------------------------------
    # Local history
    # ------------------------------------------------------------------

    def save_snapshot(self, rankings: list[RankingData]) -> None:
        """Aktuelle Ranking-Daten in der lokalen Historie speichern."""
        history = self._load_history_file()
        timestamp = datetime.now(timezone.utc).isoformat()

        for ranking in rankings:
            entry = {
                "url": ranking.url,
                "keyword": ranking.keyword,
                "position": ranking.position,
                "clicks": ranking.clicks,
                "impressions": ranking.impressions,
                "ctr": ranking.ctr,
                "date": ranking.date,
                "snapshot_time": timestamp,
            }
            history.append(entry)

        self._save_history_file(history)

    def load_history(self, page_url: str) -> list[dict]:
        """Ranking-Historie fuer eine bestimmte Seite laden."""
        history = self._load_history_file()
        filtered = [entry for entry in history if entry.get("url") == page_url]
        filtered.sort(key=lambda e: e.get("snapshot_time", ""))
        return filtered

    def get_trend(self, page_url: str, keyword: str) -> list[dict]:
        """Ranking-Trend fuer eine Seite und ein Keyword zurueckgeben.

        Jeder Eintrag enthaelt: date, position, clicks, impressions.
        """
        history = self._load_history_file()
        filtered = [
            entry
            for entry in history
            if entry.get("url") == page_url and entry.get("keyword") == keyword
        ]
        filtered.sort(key=lambda e: e.get("date", ""))

        return [
            {
                "date": entry.get("date", ""),
                "position": entry.get("position", 0.0),
                "clicks": entry.get("clicks", 0),
                "impressions": entry.get("impressions", 0),
            }
            for entry in filtered
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_history_file(self) -> list[dict]:
        """Lokale Historie-Datei laden."""
        if not self._history_path.exists():
            return []
        try:
            with open(self._history_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []

    def _save_history_file(self, data: list[dict]) -> None:
        """Lokale Historie-Datei speichern."""
        with open(self._history_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
