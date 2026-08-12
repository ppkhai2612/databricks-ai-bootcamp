# Weather Intelligence (Unstructured Data -> Lakebase Vector Search -> REST API)

This end-to-end pipline includes three stages: **harvest** -> **vectorize** -> **retrieve** - over an unstructured source: National Weather Service free text

```text
api.weather.gov ──▶ weather_client.py ──▶ weather_documents  (raw narrative + payload)
                                                  │
                          ingest_weather_embeddings.py  (chunk 800/100, MiniLM-L6-v2)
                                                  ▼
                                          weather_embeddings  (VECTOR(384) + HNSW)
                                                  │
                                       POST /weather/search   (pgvector <=>)
```

## Which data source, and why

**The National Weather Service API (https://api.weather.gov)**

- **No API key, no auth plumbing**: All the NWS API asks for is a descriptive `User-Agent` naming the app and a contact address (`WEATHER_USER_AGENT`)
- **It's genuinely unstructured**. Three different products, three different text shapes, which is what makes semantic search worth doing rather than a `LIKE '%flood%'`

This project harvests **all three**, tagged with a `source_type` you can filter on:

| `source_type` | **Endpoint** | **What the text looks like** | **Typical length** |
|-|-|-|-|
| `alert` | `GET /alerts/active?area={ST}` | `description` + `instruction`: "At 509 PM MDT, Doppler radar was tracking a strong thunderstorm… HAZARD…Wind gusts up to 50 mph and penny size hail" | 300-1,500 chars |
| `forecast` | `GET /gridpoints/{office}/{x},{y}/forecast` | One `detailedForecast` per period: "Isolated rain showers before 9pm. Mostly cloudy, with a low around 70..." | ~200 chars × 14 periods |
| `discussion` | `GET /products/types/AFD/locations/{office}` -> `GET /products/{id}` | The forecaster's own Area Forecast Discussion — free-form technical prose about the synoptic setup | ~5,500 chars |

The Area Forecast Discussion is the reason all three are included. Alerts and forecast periods are short enough that chunking is a no-op; the AFD is the one product long enough that the sliding window actually does something (a real 5,536-char AFD splits into 8 chunks), which is what the chunking half of the assignment is meant to exercise

**Things learned from the live API that shaped the code**
- **`/points` is the hub**. `GET /points/{lat},{lon}` returns the forecast office (`gridId`, e.g. `LOT`), the grid `x,y`, and a `relativeLocation` giving the two-letter state. That state is what `/alerts/active?area=` needs, so passing raw `"41.88,-87.63"` coordinates works just as well as a city name. Grid assignments never move, so responses are cached per client instance
- **`/products/types/AFD/locations/{office}` silently ignores `?limit=N`** — passing one returns an empty `@graph`. The slice is done client-side in `get_latest_discussions()`
- **The forecast response has no `properties.updated` field**, so forecast documents are keyed on each period's `startTime` instead
- **Alerts are statewide, not per-point**. Two cities in the same state return the identical feed, so `/weather/sync` fetches each state's alerts once and de-duplicates documents by `id` before the insert

## Schema decisions

Two tables, `weather_documents` and `weather_embeddings`. DDL lives in `weather_db.ensure_weather_tables()` (run automatically on every weather request) with standalone copies in `sql/01_setup_weather_documents_table.sql` and `sql/02_setup_weather_embeddings_table.sql`

### `weather_documents` — raw normalized documents

Beyond the minimum fields (`id`, `location`, `source_type`, `headline`/`event`, `narrative_text`, `issued_at`/`effective_at`, `payload`, `synced_at`), it carries `latitude`/`longitude`/`state`/`grid_office`/`grid_x`/`grid_y` so a document can be traced back to the exact NWS grid cell it came from, plus `severity`, `expires_at`, and `source_url`

**`id` is derived from stable upstream identifiers**, which is what makes re-running /weather/sync an upsert rather than a duplicate-row generator:

| **source** | **id scheme** | **example** |
|-|-|-|
| alert | `alert:{properties.id}` | `alert:urn:oid:2.49.0.1.840.0.f0923…001.1` |
| forecast | `forecast:{office}:{x},{y}:{startTime}` | `forecast:LOT:76,73:2026-08-06T18:00:00-05:00` |
| discussion | `discussion:{product_uuid}` | `discussion:f84f7939-ed27-46b6-ad37-fab12a2664cd` |

****

### `weather_embeddings` — one row per chunk

`id` ({document_id}#{chunk_index}), `document_id` (FK refs to `weather_documents.id`, `ON DELETE CASCADE`), `chunk_index`, `chunk_text`, `embedding VECTOR(384)`, `model_name`, `created_at`, plus `source_type` and `content_hash`

- **`source_type` is denormalized** onto this table so a filtered search narrows before joining the documents table instead of after
- 

### Chunking and embedding parameters

### Why pg8000 rather than psycopg2


## Running the pipeline end to end

## Endpoints


## Stretch goals implemented


## Known limitations, and what I'd do with more time

## Appendix — verification queries