# -*- coding: utf-8 -*-
"""Shopify Admin REST API wrapper with rate limiting and safety measures."""

from __future__ import annotations

import logging
import re
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

from config import AppConfig
from models import (
    SEOData,
    ShopifyProduct,
    ShopifyCollection,
    ShopifyPage,
    ImageSEO,
    ShopifyAuthError,
    ShopifyConnectionError,
    ShopifyRateLimitError,
    ShopifyNotFoundError,
)


class ShopifyClient:
    """Thin wrapper around the Shopify Admin REST API.

    Handles authentication, rate-limiting, pagination and provides
    convenience methods for products, collections, pages and redirects.
    """

    def __init__(self, config: AppConfig) -> None:
        self.base_url = config.get_base_url()
        self.headers = {
            "X-Shopify-Access-Token": config.shopify_access_token,
            "Content-Type": "application/json",
        }
        self._call_limit = 40
        self._calls_made = 0
        self._last_link_header: str = ""

    # ------------------------------------------------------------------
    # Rate-limiting helpers
    # ------------------------------------------------------------------

    def _check_rate_limit(self, response: requests.Response) -> None:
        """Read the call-limit header and throttle when approaching the cap."""
        header = response.headers.get("X-Shopify-Shop-Api-Call-Limit", "")
        if "/" in header:
            parts = header.split("/")
            try:
                self._calls_made = int(parts[0])
                self._call_limit = int(parts[1])
            except ValueError:
                pass
        if self._calls_made >= 35:
            time.sleep(1.0)

    def _handle_response(
        self,
        response: requests.Response,
        *,
        _retry: int = 0,
        _method: str = "GET",
        _url: str = "",
        _kwargs: Optional[dict] = None,
    ) -> dict:
        """Validate *response*, handle errors and return the JSON body.

        For 429 responses the request is retried up to 3 times honouring the
        ``Retry-After`` header.
        """
        if response.status_code == 401:
            raise ShopifyAuthError("Ungültiger Access Token")

        if response.status_code == 404:
            raise ShopifyNotFoundError(
                f"Ressource nicht gefunden (404): {response.url}"
            )

        if response.status_code == 429:
            if _retry >= 3:
                raise ShopifyRateLimitError(
                    "API-Rate-Limit überschritten nach 3 Versuchen"
                )
            retry_after = float(response.headers.get("Retry-After", "2.0"))
            time.sleep(retry_after)
            # Retry the original request
            if _kwargs is None:
                _kwargs = {}
            fn = {
                "GET": requests.get,
                "PUT": requests.put,
                "POST": requests.post,
            }.get(_method, requests.get)
            try:
                new_response = fn(_url, **_kwargs)
            except requests.exceptions.RequestException as exc:
                raise ShopifyConnectionError(
                    f"Verbindungsfehler beim Retry: {exc}"
                ) from exc
            return self._handle_response(
                new_response,
                _retry=_retry + 1,
                _method=_method,
                _url=_url,
                _kwargs=_kwargs,
            )

        if response.status_code >= 400:
            raise ShopifyConnectionError(
                f"Shopify API Fehler {response.status_code}: {response.text[:300]}"
            )

        self._check_rate_limit(response)

        # Some endpoints (e.g. 204 No Content) may not return JSON.
        if not response.content:
            return {}
        return response.json()

    # ------------------------------------------------------------------
    # Low-level HTTP verbs
    # ------------------------------------------------------------------

    def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        url = self.base_url + endpoint
        kwargs = {"headers": self.headers, "params": params, "timeout": 30}
        try:
            response = requests.get(url, **kwargs)
        except requests.exceptions.RequestException as exc:
            raise ShopifyConnectionError(
                f"Verbindungsfehler: {exc}"
            ) from exc
        self._last_link_header = response.headers.get("Link", "")
        return self._handle_response(
            response, _method="GET", _url=url, _kwargs=kwargs
        )

    def _put(self, endpoint: str, data: dict) -> dict:
        url = self.base_url + endpoint
        kwargs = {"headers": self.headers, "json": data, "timeout": 30}
        try:
            response = requests.put(url, **kwargs)
        except requests.exceptions.RequestException as exc:
            raise ShopifyConnectionError(
                f"Verbindungsfehler: {exc}"
            ) from exc
        return self._handle_response(
            response, _method="PUT", _url=url, _kwargs=kwargs
        )

    def _post(self, endpoint: str, data: dict) -> dict:
        url = self.base_url + endpoint
        kwargs = {"headers": self.headers, "json": data, "timeout": 30}
        try:
            response = requests.post(url, **kwargs)
        except requests.exceptions.RequestException as exc:
            raise ShopifyConnectionError(
                f"Verbindungsfehler: {exc}"
            ) from exc
        return self._handle_response(
            response, _method="POST", _url=url, _kwargs=kwargs
        )

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------

    def test_connection(self) -> tuple[bool, str]:
        """Verify that the credentials are valid.

        Returns a ``(success, message)`` tuple.
        """
        try:
            data = self._get("shop.json")
            shop_name = data.get("shop", {}).get("name", "Unbekannt")
            return True, f"Verbunden mit {shop_name}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    # ------------------------------------------------------------------
    # Paginated list helper
    # ------------------------------------------------------------------

    def _get_paginated(
        self,
        endpoint: str,
        params: dict,
        resource_key: str,
    ) -> list[dict]:
        """Fetch all pages for a list endpoint using Link header pagination.

        Returns the concatenated list of raw dicts from the ``resource_key``
        array across all pages.  Uses ``_last_link_header`` set by ``_get``
        so no double request is needed.
        """
        all_items: list[dict] = []

        while True:
            data = self._get(endpoint, params=params)
            all_items.extend(data.get(resource_key, []))

            # _get already stored the Link header — parse it for "next"
            next_url = self._parse_link_next(self._last_link_header)
            if not next_url:
                break
            endpoint, params = self._parse_paginated_url(next_url)
            params = params or {}

        return all_items

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------

    def list_products(self, limit: int = 250) -> list[ShopifyProduct]:
        """Return a lightweight list of all products (paginated)."""
        raw = self._get_paginated(
            "products.json",
            {"limit": limit, "fields": "id,title,handle,updated_at"},
            "products",
        )
        return [
            ShopifyProduct(
                id=p["id"],
                title=p.get("title", ""),
                handle=p.get("handle", ""),
                updated_at=p.get("updated_at", ""),
            )
            for p in raw
        ]

    def get_product(self, product_id: int) -> ShopifyProduct:
        """Fetch a single product including SEO metafields."""
        data = self._get(f"products/{product_id}.json")
        p = data.get("product", {})

        seo_title, meta_description = self._get_seo_metafields(
            "products", product_id
        )

        return ShopifyProduct(
            id=p["id"],
            title=p.get("title", ""),
            handle=p.get("handle", ""),
            body_html=p.get("body_html", "") or "",
            vendor=p.get("vendor", ""),
            product_type=p.get("product_type", ""),
            tags=p.get("tags", ""),
            images=p.get("images", []),
            seo_title=seo_title,
            meta_description=meta_description,
            updated_at=p.get("updated_at", ""),
        )

    # ------------------------------------------------------------------
    # Collections
    # ------------------------------------------------------------------

    def list_collections(self) -> list[ShopifyCollection]:
        """Return custom and smart collections merged into a single list (paginated)."""
        collections: list[ShopifyCollection] = []

        for ctype in ("custom", "smart"):
            raw = self._get_paginated(
                f"{ctype}_collections.json",
                {"limit": 250, "fields": "id,title,handle,updated_at"},
                f"{ctype}_collections",
            )
            for c in raw:
                collections.append(
                    ShopifyCollection(
                        id=c["id"],
                        title=c.get("title", ""),
                        handle=c.get("handle", ""),
                        collection_type=ctype,
                        updated_at=c.get("updated_at", ""),
                    )
                )

        return collections

    def get_collection(
        self, collection_id: int, collection_type: str
    ) -> ShopifyCollection:
        """Fetch a single collection including SEO metafields."""
        data = self._get(
            f"{collection_type}_collections/{collection_id}.json"
        )
        key = f"{collection_type}_collection"
        c = data.get(key, {})

        seo_title, meta_description = self._get_seo_metafields(
            f"{collection_type}_collections", collection_id
        )

        return ShopifyCollection(
            id=c["id"],
            title=c.get("title", ""),
            handle=c.get("handle", ""),
            body_html=c.get("body_html", "") or "",
            collection_type=collection_type,
            image=c.get("image"),
            seo_title=seo_title,
            meta_description=meta_description,
            updated_at=c.get("updated_at", ""),
        )

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    def list_pages(self) -> list[ShopifyPage]:
        """Return a lightweight list of all static pages (paginated)."""
        raw = self._get_paginated(
            "pages.json",
            {"limit": 250, "fields": "id,title,handle,updated_at"},
            "pages",
        )
        return [
            ShopifyPage(
                id=p["id"],
                title=p.get("title", ""),
                handle=p.get("handle", ""),
                updated_at=p.get("updated_at", ""),
            )
            for p in raw
        ]

    def get_page(self, page_id: int) -> ShopifyPage:
        """Fetch a single page including SEO metafields."""
        data = self._get(f"pages/{page_id}.json")
        p = data.get("page", {})

        seo_title, meta_description = self._get_seo_metafields(
            "pages", page_id
        )

        return ShopifyPage(
            id=p["id"],
            title=p.get("title", ""),
            handle=p.get("handle", ""),
            body_html=p.get("body_html", "") or "",
            seo_title=seo_title,
            meta_description=meta_description,
            updated_at=p.get("updated_at", ""),
        )

    # ------------------------------------------------------------------
    # Write verification helper
    # ------------------------------------------------------------------

    def _verify_resource(
        self,
        endpoint: str,
        resource_key: str,
        expected_title: str,
        expected_body_html: str,
    ) -> bool:
        """Re-read a resource after update and compare key fields.

        Returns *True* when the remote state matches expectations.
        """
        data = self._get(endpoint)
        resource = data.get(resource_key, {})
        remote_title = resource.get("title", "")
        remote_body = resource.get("body_html", "") or ""

        title_ok = remote_title == expected_title
        body_ok = remote_body == expected_body_html

        if not title_ok or not body_ok:
            logger.warning(
                "Write verification failed for %s: title_ok=%s, body_ok=%s",
                endpoint,
                title_ok,
                body_ok,
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Updates (with optimistic-concurrency safety)
    # ------------------------------------------------------------------

    def update_product(
        self,
        product_id: int,
        seo_data: SEOData,
        original_updated_at: str = "",
        verify_write: bool = True,
    ) -> bool:
        """Update product title, body, SEO metafields and image alt texts.

        If *original_updated_at* is provided the current ``updated_at`` is
        compared first so that concurrent edits are detected.

        When *verify_write* is True (default), the product is re-read after
        the update and key fields are compared with the sent data.
        """
        if original_updated_at:
            current = self._get(f"products/{product_id}.json")
            remote_ts = current.get("product", {}).get("updated_at", "")
            if remote_ts and remote_ts != original_updated_at:
                raise ShopifyConnectionError(
                    "Produkt wurde zwischenzeitlich geändert. Bitte neu laden."
                )

        # 1. Update product title and body
        self._put(
            f"products/{product_id}.json",
            {
                "product": {
                    "id": product_id,
                    "title": seo_data.h1,
                    "body_html": seo_data.body_html,
                }
            },
        )

        # 2. SEO metafields
        self._set_seo_metafields(
            "products",
            product_id,
            seo_data.seo_title,
            seo_data.meta_description,
        )

        # 3. Image alt texts
        for img in seo_data.images:
            if img.suggested_alt:
                self._put(
                    f"products/{product_id}/images/{img.image_id}.json",
                    {"image": {"id": img.image_id, "alt": img.suggested_alt}},
                )

        # 4. Write verification
        if verify_write:
            verified = self._verify_resource(
                f"products/{product_id}.json",
                "product",
                expected_title=seo_data.h1,
                expected_body_html=seo_data.body_html,
            )
            if not verified:
                logger.warning("Product %d: write verification mismatch", product_id)

        return True

    def update_collection(
        self,
        collection_id: int,
        collection_type: str,
        seo_data: SEOData,
        original_updated_at: str = "",
        verify_write: bool = True,
    ) -> bool:
        """Update a collection's title, body and SEO metafields."""
        resource = f"{collection_type}_collections"

        if original_updated_at:
            current = self._get(f"{resource}/{collection_id}.json")
            key = f"{collection_type}_collection"
            remote_ts = current.get(key, {}).get("updated_at", "")
            if remote_ts and remote_ts != original_updated_at:
                raise ShopifyConnectionError(
                    "Kategorie wurde zwischenzeitlich geändert. Bitte neu laden."
                )

        self._put(
            f"{resource}/{collection_id}.json",
            {
                f"{collection_type}_collection": {
                    "id": collection_id,
                    "title": seo_data.h1,
                    "body_html": seo_data.body_html,
                }
            },
        )

        self._set_seo_metafields(
            resource,
            collection_id,
            seo_data.seo_title,
            seo_data.meta_description,
        )

        # Collection image alt text
        for img in seo_data.images:
            if img.suggested_alt:
                self._put(
                    f"{resource}/{collection_id}.json",
                    {
                        f"{collection_type}_collection": {
                            "id": collection_id,
                            "image": {
                                "alt": img.suggested_alt,
                            },
                        }
                    },
                )

        # Write verification
        if verify_write:
            verified = self._verify_resource(
                f"{resource}/{collection_id}.json",
                f"{collection_type}_collection",
                expected_title=seo_data.h1,
                expected_body_html=seo_data.body_html,
            )
            if not verified:
                logger.warning(
                    "Collection %d: write verification mismatch", collection_id
                )

        return True

    def update_page(
        self,
        page_id: int,
        seo_data: SEOData,
        original_updated_at: str = "",
        verify_write: bool = True,
    ) -> bool:
        """Update a page's title, body and SEO metafields."""
        if original_updated_at:
            current = self._get(f"pages/{page_id}.json")
            remote_ts = current.get("page", {}).get("updated_at", "")
            if remote_ts and remote_ts != original_updated_at:
                raise ShopifyConnectionError(
                    "Seite wurde zwischenzeitlich geändert. Bitte neu laden."
                )

        self._put(
            f"pages/{page_id}.json",
            {
                "page": {
                    "id": page_id,
                    "title": seo_data.h1,
                    "body_html": seo_data.body_html,
                }
            },
        )

        self._set_seo_metafields(
            "pages",
            page_id,
            seo_data.seo_title,
            seo_data.meta_description,
        )

        # Write verification
        if verify_write:
            verified = self._verify_resource(
                f"pages/{page_id}.json",
                "page",
                expected_title=seo_data.h1,
                expected_body_html=seo_data.body_html,
            )
            if not verified:
                logger.warning("Page %d: write verification mismatch", page_id)

        return True

    # ------------------------------------------------------------------
    # Redirects
    # ------------------------------------------------------------------

    def create_redirect(self, old_path: str, new_path: str) -> bool:
        """Create a URL redirect. Returns *True* on success, *False* on failure."""
        try:
            self._post(
                "redirects.json",
                {"redirect": {"path": old_path, "target": new_path}},
            )
            return True
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------
    # SEO metafield helpers
    # ------------------------------------------------------------------

    def _get_seo_metafields(
        self, resource: str, resource_id: int
    ) -> tuple[str, str]:
        """Return ``(seo_title, meta_description)`` for a resource."""
        data = self._get(f"{resource}/{resource_id}/metafields.json")
        seo_title = ""
        meta_description = ""
        for mf in data.get("metafields", []):
            if mf.get("namespace") == "global":
                if mf.get("key") == "title_tag":
                    seo_title = mf.get("value", "")
                elif mf.get("key") == "description_tag":
                    meta_description = mf.get("value", "")
        return seo_title, meta_description

    def _set_seo_metafields(
        self,
        resource: str,
        resource_id: int,
        seo_title: str,
        meta_description: str,
    ) -> None:
        """Create or update the SEO title and description metafields."""
        data = self._get(f"{resource}/{resource_id}/metafields.json")
        existing: dict[str, int] = {}  # key -> metafield id
        for mf in data.get("metafields", []):
            if mf.get("namespace") == "global" and mf.get("key") in (
                "title_tag",
                "description_tag",
            ):
                existing[mf["key"]] = mf["id"]

        fields = {
            "title_tag": seo_title,
            "description_tag": meta_description,
        }

        for key, value in fields.items():
            if not value:
                continue
            if key in existing:
                self._put(
                    f"metafields/{existing[key]}.json",
                    {
                        "metafield": {
                            "id": existing[key],
                            "value": value,
                            "type": "single_line_text_field",
                        }
                    },
                )
            else:
                self._post(
                    f"{resource}/{resource_id}/metafields.json",
                    {
                        "metafield": {
                            "namespace": "global",
                            "key": key,
                            "value": value,
                            "type": "single_line_text_field",
                        }
                    },
                )

    # ------------------------------------------------------------------
    # Pagination helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_link_next(link_header: str) -> Optional[str]:
        """Extract the *next* URL from a ``Link`` header value."""
        if not link_header:
            return None
        # Link: <https://...>; rel="next", <https://...>; rel="previous"
        for part in link_header.split(","):
            if 'rel="next"' in part:
                match = re.search(r"<([^>]+)>", part)
                if match:
                    return match.group(1)
        return None

    def _parse_paginated_url(
        self, full_url: str
    ) -> tuple[str, Optional[dict]]:
        """Split an absolute paginated URL into an endpoint and params dict.

        The Shopify ``Link`` header returns full URLs.  We strip the base to
        get back to the endpoint format that ``_get`` expects and parse any
        query-string parameters.
        """
        from urllib.parse import urlparse, parse_qs

        parsed = urlparse(full_url)
        # The path looks like /admin/api/2024-01/products.json
        # We need just "products.json" (the part after the base).
        path = parsed.path
        # Remove the base path prefix
        base_path = self.base_url.replace("https://", "").split("/", 1)[-1]
        # base_path is like "admin/api/2024-01/"
        idx = path.find(base_path)
        if idx >= 0:
            endpoint = path[idx + len(base_path):]
        else:
            endpoint = path.rsplit("/", 1)[-1]

        params = {}
        for key, values in parse_qs(parsed.query).items():
            params[key] = values[0] if len(values) == 1 else values

        return endpoint, params or None
