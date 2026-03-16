# -*- coding: utf-8 -*-
"""Application configuration with environment variable loading and persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from dotenv import dotenv_values, set_key
from pydantic import BaseModel

ENV_PATH: Path = Path(__file__).resolve().parent / ".env"


class AppConfig(BaseModel):
    """Central configuration for the SEO tool."""

    shopify_store_url: str
    shopify_access_token: str
    anthropic_api_key: str
    shopify_api_version: str = "2025-01"
    storefront_url: str = ""
    google_credentials_path: str = ""
    ai_provider: str = "anthropic"  # "anthropic" oder "openrouter"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _normalised_store(self) -> str:
        """Return the store identifier with the myshopify.com suffix."""
        url = self.shopify_store_url.strip().rstrip("/")
        # Strip protocol if present
        for prefix in ("https://", "http://"):
            if url.lower().startswith(prefix):
                url = url[len(prefix):]
        # Ensure the suffix is present
        if not url.endswith(".myshopify.com"):
            url = f"{url}.myshopify.com"
        return url

    def get_base_url(self) -> str:
        """Return the Shopify Admin REST API base URL.

        Handles inputs like ``"store"``, ``"store.myshopify.com"`` or
        ``"https://store.myshopify.com"`` and always produces
        ``https://<store>.myshopify.com/admin/api/<version>/``.
        """
        store = self._normalised_store()
        return f"https://{store}/admin/api/{self.shopify_api_version}/"

    def get_storefront_url(self) -> str:
        """Return the public storefront URL.

        If *storefront_url* was set explicitly it is returned as-is (with a
        trailing slash stripped).  Otherwise a URL is derived from the Shopify
        store identifier.
        """
        if self.storefront_url:
            return self.storefront_url.rstrip("/")
        store = self._normalised_store()
        return f"https://{store}"

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_to_env(self) -> None:
        """Write the current configuration values to the *.env* file."""
        if not ENV_PATH.exists():
            ENV_PATH.touch()

        set_key(str(ENV_PATH), "SHOPIFY_STORE_URL", self.shopify_store_url)
        set_key(str(ENV_PATH), "SHOPIFY_ACCESS_TOKEN", self.shopify_access_token)
        set_key(str(ENV_PATH), "ANTHROPIC_API_KEY", self.anthropic_api_key)
        set_key(str(ENV_PATH), "SHOPIFY_API_VERSION", self.shopify_api_version)
        set_key(str(ENV_PATH), "STOREFRONT_URL", self.storefront_url)
        set_key(str(ENV_PATH), "GOOGLE_CREDENTIALS_PATH", self.google_credentials_path)
        set_key(str(ENV_PATH), "AI_PROVIDER", self.ai_provider)

    @staticmethod
    def load_from_env() -> Optional["AppConfig"]:
        """Load configuration from the *.env* file.

        Returns ``None`` when the file does not exist or the mandatory keys
        are missing / empty.
        """
        if not ENV_PATH.exists():
            return None

        values = dotenv_values(str(ENV_PATH))

        shopify_store_url = values.get("SHOPIFY_STORE_URL", "").strip()
        shopify_access_token = values.get("SHOPIFY_ACCESS_TOKEN", "").strip()
        anthropic_api_key = values.get("ANTHROPIC_API_KEY", "").strip()

        if not shopify_store_url or not shopify_access_token or not anthropic_api_key:
            return None

        return AppConfig(
            shopify_store_url=shopify_store_url,
            shopify_access_token=shopify_access_token,
            anthropic_api_key=anthropic_api_key,
            shopify_api_version=values.get("SHOPIFY_API_VERSION", "2024-10").strip(),
            storefront_url=values.get("STOREFRONT_URL", "").strip(),
            google_credentials_path=values.get("GOOGLE_CREDENTIALS_PATH", "").strip(),
            ai_provider=values.get("AI_PROVIDER", "anthropic").strip(),
        )
