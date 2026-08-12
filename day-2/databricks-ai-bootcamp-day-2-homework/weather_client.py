import requests
import os
from typing import Any
from collections.abc import Iterable
import time
import logging
import re

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry


_BASE_URL = os.environ.get("WEATHER_API_BASE_URL", "https://api.weather.gov")
_DEFAULT_TIMEOUT = 30
_SECONDS_BETWEEN_REQUESTS = float(os.environ.get("WEATHER_REQUEST_SPACING", "0.2"))

# api.weather.gov asks callers to identify themselves with an app name and
# a contact address. Override WEATHER_USER_AGENT with your own email in app.yaml
_USER_AGENT = os.environ.get(
    "WEATHER_USER_AGENT",
    "databricks-ai-bootcamp-day-2-homework (contact: {your email in app.yaml})"
)


SOURCE_TYPES = ("alert", "forecast", "discussion")

# converts "41.88,-87.63" to "41.88 -87.63"
_LATLON_RE = re.compile(
    r"^\s*(-?\d{1,3}(?:\.\d+)?)\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)\s*$"
)

KNOWN_LOCATIONS: dict[str, tuple[float, float]] = {
    "albuquerque, nm": (35.0844, -106.6504),
    "anchorage, ak": (61.2181, -149.9003),
    "atlanta, ga": (33.7490, -84.3880),
    "austin, tx": (30.2672, -97.7431),
    "baltimore, md": (39.2904, -76.6122),
    "boise, id": (43.6150, -116.2023),
    "boston, ma": (42.3601, -71.0589),
    "buffalo, ny": (42.8864, -78.8784),
    "charlotte, nc": (35.2271, -80.8431),
    "chicago, il": (41.8781, -87.6298),
    "cleveland, oh": (41.4993, -81.6944),
    "columbus, oh": (39.9612, -82.9988),
    "dallas, tx": (32.7767, -96.7970),
    "denver, co": (39.7392, -104.9903),
    "detroit, mi": (42.3314, -83.0458),
    "honolulu, hi": (21.3069, -157.8583),
    "houston, tx": (29.7604, -95.3698),
    "indianapolis, in": (39.7684, -86.1581),
    "jacksonville, fl": (30.3322, -81.6557),
    "kansas city, mo": (39.0997, -94.5786),
    "las vegas, nv": (36.1699, -115.1398),
    "los angeles, ca": (34.0522, -118.2437),
    "memphis, tn": (35.1495, -90.0490),
    "miami, fl": (25.7617, -80.1918),
    "milwaukee, wi": (43.0389, -87.9065),
    "minneapolis, mn": (44.9778, -93.2650),
    "nashville, tn": (36.1627, -86.7816),
    "new orleans, la": (29.9511, -90.0715),
    "new york, ny": (40.7128, -74.0060),
    "oklahoma city, ok": (35.4676, -97.5164),
    "omaha, ne": (41.2565, -95.9345),
    "philadelphia, pa": (39.9526, -75.1652),
    "phoenix, az": (33.4484, -112.0740),
    "pittsburgh, pa": (40.4406, -79.9959),
    "portland, or": (45.5152, -122.6784),
    "raleigh, nc": (35.7796, -78.6382),
    "sacramento, ca": (38.5816, -121.4944),
    "salt lake city, ut": (40.7608, -111.8910),
    "san antonio, tx": (29.4241, -98.4936),
    "san diego, ca": (32.7157, -117.1611),
    "san francisco, ca": (37.7749, -122.4194),
    "seattle, wa": (47.6062, -122.3321),
    "st. louis, mo": (38.6270, -90.1994),
    "tampa, fl": (27.9506, -82.4572),
    "tulsa, ok": (36.1540, -95.9928),
    "washington, dc": (38.9072, -77.0369),
}


class UnknownLocationError(ValueError):
    """Raised when a location string is neither a known city nor a lat/lon pair."""


def _normalize_place_key(text: str) -> str:
    """Fold 'Chicago,IL' / 'chicago , il' / 'CHICAGO, IL' to one lookup key"""
    collapsed = re.sub(r"\s+", " ", text.strip().lower())
    collapsed = re.sub(r"\s*,\s*", ", ", collapsed)
    return collapsed


def resolve_location(text: str) -> tuple[float, float]:
    """Turn a user-supplied location string into (latitude, longitude)

    Accepts either a raw coordinate pair ("41.88,-87.63") or a city/state name
    present in KNOWN_LOCATIONS. Raises UnknownLocationError otherwise
    """
    if not isinstance(text, str) or not text.strip():
        raise UnknownLocationError("Location must be a non-empty string")
    
    match = _LATLON_RE.match(text)
    if match:
        lat, lon = float(match.group(1)), float(match.group(2))
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            raise UnknownLocationError(f"Coordinates out of range: {text!r}")
        return lat, lon

    key = _normalize_place_key(text)
    if key in KNOWN_LOCATIONS:
        return KNOWN_LOCATIONS[key]

    raise UnknownLocationError(
        f"Unknown location {text!r}. Pass 'lat,lon' coordinates, or add the "
        "city to KNOWN_LOCATIONS in weather_client.py."
    )





class NWSClient:
    """Thin wrapper around api.weather.gov with a retrying, identified session."""

    def __init__(self, base_url: str | None = None, timeout: int = _DEFAULT_TIMEOUT):

        self.base_url = (base_url or _BASE_URL).rstrip("/")
        self.timeout = timeout
        self._last_request_at = 0.0

        # /points responses are effectively static (a coordinate's grid cell
        # doesn't move), so cache them for the lifetime of the client instead
        # of re-resolving the same city on every sync
        self._point_cache: dict[tuple[float, float], dict[str, Any]] = {}

        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": _USER_AGENT,
                "Accept": "application/geo+json",
            }
        )
        # NWS occasionally 502/503s under load; retry a few times with backoff
        # rather than losing a whole location's documents to one blip.
        retry = Retry(
            total=3,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
        )
        self._session.mount("https://", HTTPAdapter(max_retries=retry))
    
    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET a path relative to the API base"""
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < _SECONDS_BETWEEN_REQUESTS:
            time.sleep(_SECONDS_BETWEEN_REQUESTS - elapsed)
        
        url = path if path.startswith("https") else f"{self.base_url}{path}"
        response = self._session.get(url, params=params, timeout=self.timeout)
        self._last_request_at = time.monotonic()
        response.raise_for_status()
        return response.json()

    def resolve_point(self, lat: float, lon: float) -> dict[str, Any]:
        """Map coordinates to the NWS forecast grid cell that covers them"""
        key = (round(lat, 4), round(lon, 4))
        if key in self._point_cache:
            return self._point_cache[key]

        data = self.get(f"/points/{key[0]},{key[1]}")
        props = data.get("properties", {})
        rel = props.get("relativeLocation", {})

        point = {
            "latitude": key[0],
            "longitude": key[1],
            "grid_office": props.get("gridId"),
            "grid_x": props.get("gridX"),
            "grid_y": props.get("gridY"),
            "city": rel.get("city"),
            "state": rel.get("state"),
            "forecast_url": props.get("forecast"),
        }
        self._point_cache[key] = point
        return point

    def get_active_alerts(self, state: str, limit: int = 50) -> list[dict]:
        """"""
        data = self.get("/alerts/active", params={"area": state.upper()})



# -----------------------------------------------------------------
# Normalization: raw API payloads -> flat weather_documents records

def normalize_alerts(
    
):



def normalize_forecast_periods(

):

def normalize_discussions(

):


def fetch_location_documents(
    nws_client: NWSClient,
    location: str,
    limit: int = 50,
    sources: Iterable[str] = SOURCE_TYPES,
    alert_features: list[dict] | None = None
) -> tuple[list[dict], dict[str, Any]]:

    requested = {s for s in sources if s in SOURCE_TYPES}
    lat, lon = resolve_location(location)
    point = nws_client.resolve_point(lat, lon)

    documents: list[dict] = []
    
    if "alert" in requested:
        try:
            features = alert_features
            if features is None:
                state = point.get("state")
                features = client.get_active_alerts(state, limit=limit) if state else []
            documents.extend(normalize_alerts(features[:limit], location, point))
        except requests.RequestException as exc:
            logger.warning("Alerts failed for %s: %s", location, exc)

    if "forecast" in requested:
        try:
            periods = client.get_forecast_periods(
                point["grid_office"], point["grid_x"], point["grid_y"]
            )
            documents.extend(normalize_forecast_periods(periods[:limit], location, point))
        except requests.RequestException as exc:
            logger.warning("Forecast failed for %s: %s", location, exc)

    if "discussion" in requested:
        try:
            # AFDs are long and slow to fetch (one extra call each), and the
            # latest one or two are what matter - cap well below `limit`.
            products = client.get_latest_discussions(
                point["grid_office"], limit=min(limit, 2)
            )
            documents.extend(normalize_discussions(products, location, point))
        except requests.RequestException as exc:
            logger.warning("Discussion failed for %s: %s", location, exc)

    return documents, point

   


if __name__ == "__main__":
    # Smoke test against the live API, no database required:
    #     python weather_client.py "Chicago, IL"
    # Run it twice - the printed ids must be identical, which is what makes
    # POST /weather/sync an upsert rather than a duplicate-row generator.
    import sys

    logging.basicConfig(level=logging.INFO)
    location = sys.argv[1] if len(sys.argv) > 1 else "Chicago, IL"

    nws_client = NWSClient()
    docs, resolved = fetch_location_documents(nws_client, location)

    print(f"Location: {location} -> {resolved}\n")
    by_type: dict[str, list[dict]] = {}
    for doc in docs:
        by_type.setdefault(doc["source_type"], []).append(doc)

    for source_type in SOURCE_TYPES:
        group = by_type.get(source_type, [])
        print(f"{source_type}: {len(group)} document(s)")
        for doc in group[:2]:
            preview = doc["narrative_text"][:160].replace("\n", " ")
            print(f"  id={doc['id']}")
            print(f"  chars={len(doc['narrative_text'])} headline={doc['headline']!r}")
            print(f"  text={preview}...")
        print()

    print(f"TOTAL: {len(docs)} documents")