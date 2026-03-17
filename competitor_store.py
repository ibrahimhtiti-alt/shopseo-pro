# -*- coding: utf-8 -*-
"""JSON-backed storage for competitor domains and their ranking data."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from models import Competitor, CompetitorRanking


class CompetitorStore:
    """Manages competitor tracking data (domains + keyword positions).

    Data is stored in two JSON files inside the ``data/`` directory
    (Docker volume) or project root as fallback.
    """

    _MAX_RANKING_ENTRIES = 20_000

    def __init__(self) -> None:
        _data_dir = Path(__file__).resolve().parent / "data"
        if _data_dir.is_dir():
            self._competitors_path = _data_dir / "competitors.json"
            self._rankings_path = _data_dir / "competitor_rankings.json"
        else:
            _root = Path(__file__).resolve().parent
            self._competitors_path = _root / "competitors.json"
            self._rankings_path = _root / "competitor_rankings.json"

    # ------------------------------------------------------------------
    # Competitor CRUD
    # ------------------------------------------------------------------

    def list_competitors(self) -> list[Competitor]:
        """Return all tracked competitors."""
        data = self._load_json(self._competitors_path)
        return [Competitor(**c) for c in data]

    def add_competitor(self, name: str, domain: str) -> Competitor:
        """Add a new competitor and return the created object."""
        competitors = self._load_json(self._competitors_path)

        # Create slug from domain
        slug = domain.lower().replace("www.", "").split(".")[0]
        # Ensure unique
        existing_ids = {c["id"] for c in competitors}
        base_slug = slug
        counter = 1
        while slug in existing_ids:
            slug = f"{base_slug}-{counter}"
            counter += 1

        competitor = Competitor(
            id=slug,
            name=name,
            domain=domain.lower().strip().rstrip("/"),
            added_date=datetime.now(timezone.utc).isoformat(),
        )
        competitors.append(competitor.model_dump())
        self._save_json(self._competitors_path, competitors)
        return competitor

    def remove_competitor(self, competitor_id: str) -> bool:
        """Remove a competitor by ID. Returns True if found and removed."""
        competitors = self._load_json(self._competitors_path)
        original_len = len(competitors)
        competitors = [c for c in competitors if c.get("id") != competitor_id]
        if len(competitors) == original_len:
            return False
        self._save_json(self._competitors_path, competitors)

        # Also remove associated rankings
        rankings = self._load_json(self._rankings_path)
        rankings = [r for r in rankings if r.get("competitor_id") != competitor_id]
        self._save_json(self._rankings_path, rankings)
        return True

    # ------------------------------------------------------------------
    # Competitor ranking data
    # ------------------------------------------------------------------

    def save_competitor_ranking(
        self,
        competitor_id: str,
        keyword: str,
        position: float,
        url: str = "",
        source: str = "manual",
    ) -> None:
        """Save or update a competitor position for a keyword."""
        rankings = self._load_json(self._rankings_path)
        today = datetime.now(timezone.utc).date().isoformat()

        # Update existing entry for same competitor + keyword + date, or add new
        found = False
        for r in rankings:
            if (
                r.get("competitor_id") == competitor_id
                and r.get("keyword") == keyword
                and r.get("date") == today
            ):
                r["position"] = position
                r["url"] = url
                r["source"] = source
                found = True
                break

        if not found:
            entry = CompetitorRanking(
                competitor_id=competitor_id,
                keyword=keyword,
                position=position,
                url=url,
                date=today,
                source=source,
            )
            rankings.append(entry.model_dump())

        # Trim if over limit
        if len(rankings) > self._MAX_RANKING_ENTRIES:
            rankings = rankings[-self._MAX_RANKING_ENTRIES:]

        self._save_json(self._rankings_path, rankings)

    def save_competitor_rankings_bulk(
        self, entries: list[CompetitorRanking]
    ) -> None:
        """Save multiple competitor ranking entries at once."""
        rankings = self._load_json(self._rankings_path)
        for entry in entries:
            rankings.append(entry.model_dump())
        if len(rankings) > self._MAX_RANKING_ENTRIES:
            rankings = rankings[-self._MAX_RANKING_ENTRIES:]
        self._save_json(self._rankings_path, rankings)

    def get_competitor_rankings(
        self, keyword: str
    ) -> list[CompetitorRanking]:
        """Get all competitor positions for a specific keyword (latest per competitor)."""
        rankings = self._load_json(self._rankings_path)
        # Filter for keyword
        kw_rankings = [r for r in rankings if r.get("keyword", "").lower() == keyword.lower()]

        # Keep only the latest entry per competitor
        latest: dict[str, dict] = {}
        for r in kw_rankings:
            cid = r.get("competitor_id", "")
            existing = latest.get(cid)
            if not existing or r.get("date", "") > existing.get("date", ""):
                latest[cid] = r

        return [CompetitorRanking(**v) for v in latest.values()]

    def get_keyword_comparison(
        self, keyword: str, our_position: float
    ) -> list[dict]:
        """Build a comparison table: our position vs each competitor.

        Returns list of dicts with keys:
            competitor_name, competitor_domain, competitor_position,
            our_position, gap (positive = we are ahead).
        """
        competitors = {c.id: c for c in self.list_competitors()}
        comp_rankings = self.get_competitor_rankings(keyword)

        result = []
        for cr in comp_rankings:
            comp = competitors.get(cr.competitor_id)
            if not comp:
                continue
            gap = cr.position - our_position  # positive = competitor is worse
            result.append({
                "competitor_name": comp.name,
                "competitor_domain": comp.domain,
                "competitor_position": cr.position,
                "our_position": our_position,
                "gap": gap,
                "date": cr.date,
                "source": cr.source,
            })

        # Sort by competitor position (best first)
        result.sort(key=lambda x: x["competitor_position"])
        return result

    def get_all_tracked_keywords(self) -> list[str]:
        """Return a unique sorted list of all keywords with competitor data."""
        rankings = self._load_json(self._rankings_path)
        keywords = sorted({r.get("keyword", "") for r in rankings if r.get("keyword")})
        return keywords

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_json(self, path: Path) -> list[dict]:
        """Load a JSON array file, returning [] if missing or corrupt."""
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except (json.JSONDecodeError, IOError):
            return []

    def _save_json(self, path: Path, data: list[dict]) -> None:
        """Write a JSON array to file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
