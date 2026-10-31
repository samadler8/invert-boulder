# Boulder Inversion Outlook — public-data release

## Product design

- One **Boulder-to-Green-Mountain opportunity index** is the public headline. First Flatiron (7,258 ft) and Green Mountain (8,133 ft) remain useful **elevations and map locations**, not competing scorecards.
- There are **no fabricated demo weather conditions** in the shipped application. Empty/stale forecasts appear as missing, not invented.
- One forecast-time slider updates the score, atmosphere drawing, ten HRRR samples, vertical humidity, raw fields and sunrise information. The time axis is sparse—only downloaded forecast hours exist.
- Real NOAA HRRR GRIB inventories and timestamp/lead are linked with the readings; NWS hourly guidance and IEM METARs are labeled separately.
- History keeps the historical forecast run/vintage and whether a result was captured then or reconstructed later. It never silently converts retrospective reconstructions into contemporaneous predictions.

## Storage policy

| Dataset | Normal retention | How it is handled |
| --- | --- | --- |
| Temporary GRIB subsets | Deleted immediately after decoding | Stale partials older than four hours cleaned on refresh |
| HRRR forecast caches | Seven days | Dedupe by issued-run/lead, atomic replacement |
| Recent airport reports | 30 days | Short-lived cache for website; historical observation CSV untouched |
| Nearby METAR, NWS hourly | Latest good snapshot | Atomic overwrite only after successful retrieval |
| SQLite forecast prediction ledger | Indefinite | Never automatically deleted; optional explicit retention CLI |
| Historical ML-era HRRR JSONL | Indefinite | Preserved; optional user-led archive outside app |

Use `python -m scripts.storage status`, `python -m scripts.storage cleanup` (preview), and `python -m scripts.storage cleanup --apply` to clean disposable caches. No scheduled deletion of the forecast ledger. Manual history pruning requires `--history-days 365` (minimum 30).

## Scientific honesty

An inversion is formally a positive vertical temperature gradient, but a visually useful *sea of clouds* also requires actual low cloud near Boulder, a cloud top below chosen viewpoints, and clearer higher sky. The single index combines physical indicators of this **opportunity**, not a probability. HRRR's sparse pressure-level RH is not a measured fog top; cloud fractions are not direct sunrise visibility, and ten map markers may correspond to fewer distinct 3 km model grid cells. A high index merits checking actual webcams and mountain conditions before travel.

## Operations and verification

- `python -m uvicorn inversion.server:app --reload` serves cached information immediately at localhost:8000.
- The **Refresh forecast** button sequentially attempts recent HRRR data, selected T-24/18/12/6/0 history, KBDU METAR, other airport METAR, and separate NWS hourly guidance; errors are per-source.
- The Mac must remain awake and online to fetch new data. No cloud service is provisioned by this release.
- Offline tests exercise decoding fixtures, score provenance, caching, nearby station parsing, NWS endpoints, migrations, and UI invariants. A live NOAA/Herbie download and hosted deployment remain unverified and are not required to open cached data.

## Upgrade from previous ZIP overlays

1. Make a Git commit or backup to protect local code edits.
2. Unzip this release's overlay into `~/github/invert-boulder`.
3. Run `python -m scripts.finalize_checkout` to archive now-retired root files. Existing archived copies are not overwritten.
4. Run `python -m pytest -q` and start `uvicorn`.
5. Use the UI refresh when connected to the internet; existing datasets and ledger remain on disk.
