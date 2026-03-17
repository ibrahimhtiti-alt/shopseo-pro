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
        # Use data/ directory if available (Docker volume), otherwise project root
        _data_dir = Path(__file__).resolve().parent / "data"
        if _data_dir.is_dir():
            self._history_path = _data_dir / "ranking_history.json"
        else:
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
    # Site-wide keyword intelligence
    # ------------------------------------------------------------------

    def get_site_keywords(
        self, days: int = 28, limit: int = 100
    ) -> list[RankingData]:
        """Get ALL keywords for the entire site (not filtered by page).

        Returns up to *limit* keywords sorted by impressions descending.
        """
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
                        "rowLimit": limit,
                        "type": "web",
                    },
                )
                .execute()
            )

            results: list[RankingData] = []
            for row in response.get("rows", []):
                results.append(
                    RankingData(
                        url=self.site_url,
                        keyword=row["keys"][0],
                        position=row.get("position", 0.0),
                        clicks=row.get("clicks", 0),
                        impressions=row.get("impressions", 0),
                        ctr=row.get("ctr", 0.0),
                        date=end_date.isoformat(),
                    )
                )
            results.sort(key=lambda r: r.impressions, reverse=True)
            return results
        except Exception:
            return []

    def get_position_distribution(self, days: int = 28) -> dict[str, int]:
        """Count keywords in each position bucket.

        Returns dict with keys: top3, page1, page2, page3_plus, total.
        """
        keywords = self.get_site_keywords(days=days, limit=500)
        dist = {"top3": 0, "page1": 0, "page2": 0, "page3_plus": 0, "total": 0}
        for kw in keywords:
            dist["total"] += 1
            pos = kw.position
            if pos <= 3:
                dist["top3"] += 1
            elif pos <= 10:
                dist["page1"] += 1
            elif pos <= 20:
                dist["page2"] += 1
            else:
                dist["page3_plus"] += 1
        return dist

    def get_movers(
        self, days_current: int = 7, days_previous: int = 7
    ) -> dict[str, list[dict]]:
        """Compare recent period vs previous period to find biggest movers.

        Returns dict with keys 'winners' and 'losers', each a list of:
            {keyword, old_position, new_position, change, clicks, impressions}
        Sorted by absolute change descending.
        """
        if not self._connected or not self.service:
            return {"winners": [], "losers": []}

        end_current = datetime.now(timezone.utc).date()
        start_current = end_current - timedelta(days=days_current)
        end_previous = start_current - timedelta(days=1)
        start_previous = end_previous - timedelta(days=days_previous)

        def _fetch_period(start, end):
            try:
                resp = (
                    self.service.searchanalytics()
                    .query(
                        siteUrl=self.site_url,
                        body={
                            "startDate": start.isoformat(),
                            "endDate": end.isoformat(),
                            "dimensions": ["query"],
                            "rowLimit": 200,
                            "type": "web",
                        },
                    )
                    .execute()
                )
                return {
                    row["keys"][0]: {
                        "position": row.get("position", 0.0),
                        "clicks": row.get("clicks", 0),
                        "impressions": row.get("impressions", 0),
                    }
                    for row in resp.get("rows", [])
                }
            except Exception:
                return {}

        current = _fetch_period(start_current, end_current)
        previous = _fetch_period(start_previous, end_previous)

        winners, losers = [], []
        for kw, cur_data in current.items():
            if kw in previous:
                old_pos = previous[kw]["position"]
                new_pos = cur_data["position"]
                change = old_pos - new_pos  # positive = improved
                if abs(change) >= 1.0:
                    entry = {
                        "keyword": kw,
                        "old_position": round(old_pos, 1),
                        "new_position": round(new_pos, 1),
                        "change": round(change, 1),
                        "clicks": cur_data["clicks"],
                        "impressions": cur_data["impressions"],
                    }
                    if change > 0:
                        winners.append(entry)
                    else:
                        losers.append(entry)

        winners.sort(key=lambda x: x["change"], reverse=True)
        losers.sort(key=lambda x: x["change"])
        return {"winners": winners[:10], "losers": losers[:10]}

    def get_opportunities(self, days: int = 28) -> list[dict]:
        """Find high-impression but low-CTR keywords (position 5-20).

        These are 'quick wins' where improving position yields traffic.
        Returns list of: {keyword, position, impressions, clicks, ctr, estimated_clicks}
        """
        keywords = self.get_site_keywords(days=days, limit=500)
        opportunities = []
        for kw in keywords:
            if 4.0 <= kw.position <= 25.0 and kw.impressions >= 5:
                # Estimate clicks if position improved to top 3 (avg CTR ~8%)
                estimated_clicks = int(kw.impressions * 0.08)
                opportunities.append({
                    "keyword": kw.keyword,
                    "position": round(kw.position, 1),
                    "impressions": kw.impressions,
                    "clicks": kw.clicks,
                    "ctr": round(kw.ctr * 100, 2),
                    "estimated_clicks": estimated_clicks,
                    "potential_gain": max(0, estimated_clicks - kw.clicks),
                })
        # Sort by potential gain
        opportunities.sort(key=lambda x: x["potential_gain"], reverse=True)
        return opportunities[:30]

    def get_cannibalization(self, days: int = 28) -> list[dict]:
        """Find keywords where multiple pages compete with each other.

        Returns list of: {keyword, pages: [{url, position, clicks, impressions}]}
        """
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
                        "dimensions": ["query", "page"],
                        "rowLimit": 500,
                        "type": "web",
                    },
                )
                .execute()
            )

            # Group by keyword
            keyword_pages: dict[str, list[dict]] = {}
            for row in response.get("rows", []):
                kw = row["keys"][0]
                page = row["keys"][1]
                if kw not in keyword_pages:
                    keyword_pages[kw] = []
                keyword_pages[kw].append({
                    "url": page,
                    "position": round(row.get("position", 0.0), 1),
                    "clicks": row.get("clicks", 0),
                    "impressions": row.get("impressions", 0),
                })

            # Only keywords with 2+ pages
            result = []
            for kw, pages in keyword_pages.items():
                if len(pages) >= 2:
                    pages.sort(key=lambda p: p["position"])
                    result.append({
                        "keyword": kw,
                        "page_count": len(pages),
                        "pages": pages,
                        "total_impressions": sum(p["impressions"] for p in pages),
                    })

            result.sort(key=lambda x: x["total_impressions"], reverse=True)
            return result[:20]
        except Exception:
            return []

    def generate_alerts(self, threshold: float = 3.0) -> list[dict]:
        """Compare latest snapshot with previous to find significant changes.

        Returns list of: {keyword, old_position, new_position, change, alert_type}
        """
        history = self._load_history_file()
        if not history:
            return []

        # Group by snapshot_time
        snapshots: dict[str, list[dict]] = {}
        for entry in history:
            st = entry.get("snapshot_time", "")
            if st:
                if st not in snapshots:
                    snapshots[st] = []
                snapshots[st].append(entry)

        times = sorted(snapshots.keys())
        if len(times) < 2:
            return []

        latest = {e["keyword"]: e for e in snapshots[times[-1]]}
        previous = {e["keyword"]: e for e in snapshots[times[-2]]}

        alerts = []
        for kw, cur in latest.items():
            if kw in previous:
                old_pos = previous[kw].get("position", 0.0)
                new_pos = cur.get("position", 0.0)
                change = old_pos - new_pos  # positive = improved
                if abs(change) >= threshold:
                    alerts.append({
                        "keyword": kw,
                        "old_position": round(old_pos, 1),
                        "new_position": round(new_pos, 1),
                        "change": round(change, 1),
                        "alert_type": "winner" if change > 0 else "loser",
                        "url": cur.get("url", ""),
                    })

        alerts.sort(key=lambda x: abs(x["change"]), reverse=True)
        return alerts[:20]

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

    _MAX_HISTORY_ENTRIES = 10000

    def _save_history_file(self, data: list[dict]) -> None:
        """Lokale Historie-Datei speichern (max 10.000 Einträge)."""
        if len(data) > self._MAX_HISTORY_ENTRIES:
            data = data[-self._MAX_HISTORY_ENTRIES:]
        with open(self._history_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
