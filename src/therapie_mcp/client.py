"""Bounded, cached, rate-limited GET access to the public therapie.de website."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime, timezone
import time
from typing import Any
from urllib.parse import urlencode, urljoin

import httpx

from . import __version__
from .parsing import BASE_URL, FILTERS, SEARCH_PATH, TherapieError, parse_filters, parse_profile, parse_search, profile_url, site_url

MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class TherapieClient:
    def __init__(self, http: httpx.AsyncClient | None = None, *, interval: float = 1.0):
        self._http = http
        self._owns_http = http is None
        self._interval = interval
        self._lock = asyncio.Lock()
        self._last_request = 0.0
        self._cache: OrderedDict[str, tuple[float, str, str, str]] = OrderedDict()

    async def aclose(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()

    async def _get(self, url: str, *, ttl: float = 300) -> tuple[str, str, str]:
        url = site_url(url)
        async with self._lock:
            cached = self._cache.get(url)
            if cached and cached[0] > time.monotonic():
                self._cache.move_to_end(url)
                return cached[1:]
            if self._http is None:
                self._http = httpx.AsyncClient(timeout=20, follow_redirects=False, headers={
                    'User-Agent': f'therapie-mcp/{__version__} (+https://github.com/slopinger/therapie-mcp)',
                    'Accept': 'text/html', 'Accept-Language': 'de',
                })
            current = url
            try:
                for _ in range(5):
                    delay = self._interval - (time.monotonic() - self._last_request)
                    if delay > 0:
                        await asyncio.sleep(delay)
                    self._last_request = time.monotonic()
                    async with self._http.stream('GET', current, follow_redirects=False) as response:
                        if response.is_redirect:
                            target = response.headers.get('location')
                            if not target:
                                raise TherapieError('Therapie.de returned a redirect without a destination.')
                            current = site_url(urljoin(current, target))
                            continue
                        if response.status_code == 429:
                            raise TherapieError('Therapie.de rate limit reached. Wait before retrying.')
                        if response.status_code == 404:
                            raise TherapieError('Therapie.de page or therapist profile was not found (404).')
                        if response.status_code in (401, 403):
                            raise TherapieError('Therapie.de refused access. Open the source URL in a browser; access restrictions are not bypassed.')
                        response.raise_for_status()
                        if 'text/html' not in response.headers.get('content-type', '').lower():
                            raise TherapieError('Expected an HTML page from therapie.de.')
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > MAX_RESPONSE_BYTES:
                                raise TherapieError('Therapie.de response exceeded the 4 MiB size limit.')
                        html = body.decode(response.encoding or 'utf-8', errors='replace')
                        fetched = datetime.now(timezone.utc).isoformat()
                        self._cache[url] = (time.monotonic() + ttl, html, current, fetched)
                        self._cache.move_to_end(url)
                        while len(self._cache) > 32:
                            self._cache.popitem(last=False)
                        return html, current, fetched
                raise TherapieError('Therapie.de redirected too many times.')
            except httpx.HTTPError as error:
                # Do not leak the user's search URL into protocol error messages/logs.
                raise TherapieError(f'Therapie.de request failed ({type(error).__name__}). Try again later.') from error

    async def filters(self) -> dict[str, Any]:
        html, url, fetched = await self._get(BASE_URL + '/therapeutensuche/', ttl=3600)
        return {'source_url': url, 'retrieved_at': fetched, 'filters': parse_filters(html)}

    async def search(self, location: str, *, radius_km: int | None = None, page: int = 1,
                     keyword: str | None = None, **filters: str | None) -> dict[str, Any]:
        location = location.strip()
        if not location or len(location) > 200:
            raise TherapieError('Location must be a town or postcode, between 1 and 200 characters.')
        if type(page) is not int or not 1 <= page <= 1000:
            raise TherapieError('Page must be an integer between 1 and 1000.')
        if radius_km is not None and (type(radius_km) is not int or not 1 <= radius_km <= 200):
            raise TherapieError('Search radius must be an integer between 1 and 200 km.')
        if keyword is not None and len(keyword) > 200:
            raise TherapieError('Keyword must be at most 200 characters.')
        unknown = set(filters) - set(FILTERS)
        if unknown:
            raise TherapieError('Unknown search filter: ' + ', '.join(sorted(unknown)))
        params: dict[str, str | int] = {'ort': location, 'page': page}
        if radius_km is not None:
            params['search_radius'] = radius_km
        if keyword and keyword.strip():
            params['weiteres'] = keyword.strip()
        active = {key: value for key, value in filters.items() if value is not None}
        if active:
            definitions = (await self.filters())['filters']
            for key, value in active.items():
                options = definitions[key]['options']
                option = next((option for option in options if str(value).strip().casefold() in
                               {option['id'].casefold(), option['label'].casefold()}), None)
                if option is None:
                    raise TherapieError(f'Unknown {key} option. Use get_search_filters for supported IDs and German labels.')
                params[FILTERS[key][0]] = option['id']
        requested = BASE_URL + SEARCH_PATH + '?' + urlencode(params)
        html, url, fetched = await self._get(requested, ttl=60)
        result = parse_search(html, url)
        result.update(page=page, retrieved_at=fetched, requested_filters=params)
        result['availability_note'] = 'Reported availability and billing are directory statements, not a confirmed appointment or coverage decision.'
        return result

    async def profile(self, identifier: str) -> dict[str, Any]:
        html, url, fetched = await self._get(profile_url(identifier))
        result = parse_profile(html, url)
        result['retrieved_at'] = fetched
        return result
