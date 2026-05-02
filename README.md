# UrbanFabric

**Automated Site Analysis Tool for Architects and Urban Planners**

UrbanFabric generates production-ready CAD drawings of any location on Earth from a bounding box — buildings, roads, and elevation contour lines — delivered as `.dxf` files that open directly in AutoCAD and Civil 3D.

---

## What it does

| Feature | Source | Output |
|---|---|---|
| Buildings (2D filled) | OpenStreetMap | `BUILDINGS` layer — DXF |
| Buildings (3D extruded) | OpenStreetMap + OSM levels | `BUILDINGS_3D` layer — DXF |
| Roads (major / minor / footway) | OpenStreetMap | `ROAD_MAJOR`, `ROAD_MINOR`, `ROAD_FOOT` layers — DXF |
| Elevation contour lines | Copernicus GLO-30 (30m, ESA 2023) | `CONTOURS`, `CONTOURS_MAJOR` layers — DXF or GeoJSON |

All processing runs in the background via Celery. The API returns a `task_id` immediately and the file is ready to download when the job completes.

---

## Architecture

```
┌─────────────┐     POST /generate      ┌──────────────┐
│   Client    │ ──────────────────────► │   FastAPI    │
│  (Swagger / │                         │  hello_api   │
│   curl)     │ ◄────────────────────── │              │
└─────────────┘     { task_id }         └──────┬───────┘
                                               │ .delay()
                                               ▼
                                        ┌──────────────┐
                                        │    Celery    │
                                        │    Worker    │
                                        └──────┬───────┘
                                               │
                              ┌────────────────┼────────────────┐
                              ▼                ▼                ▼
                       finalexporter      elevation.py      (future)
                       OSM → DXF          COP30 → DXF       terrain
                              │                │
                              └────────────────┘
                                       │
                                       ▼
                                  ┌─────────┐
                                  │  Redis  │  ← stores base64 DXF result
                                  └─────────┘
```

**Three Docker services:**
- `redis` — message broker + result backend
- `api` — FastAPI on port 8000
- `worker` — Celery worker that runs all processing jobs

---

## Project structure

```
urban_fabric/
├── docker-compose.yml
└── backend/
    ├── Dockerfile
    ├── requirements.txt
    ├── celery_app.py          ← Redis broker config
    ├── hello_api.py           ← All FastAPI endpoints
    ├── tasks.py               ← Celery task definitions
    ├── finalexporter.py       ← OSM → DXF (buildings + roads)
    └── elevation.py           ← COP30 → contours (GeoJSON + DXF)
```

---

## Quickstart

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Free API key from [OpenTopography](https://opentopography.org) → My Account → API Key

### 1. Clone the repository

```bash
git clone https://github.com/your-username/urban_fabric.git
cd urban_fabric
```

### 2. Add your OpenTopography API key

Open `docker-compose.yml` and replace the key in both `api` and `worker` services:

```yaml
environment:
  - OPENTOPOGRAPHY_API_KEY=your_key_here
```

### 3. Start all services

```bash
docker compose up --build
```

Wait until you see all three services ready:
```
redis-1   | Ready to accept connections
api-1     | Uvicorn running on http://0.0.0.0:8000
worker-1  | celery@... ready.
```

### 4. Open the API docs

```
http://localhost:8000/docs
```

---

## API Reference

### Base Map — Buildings + Roads → DXF

#### `POST /generate`

Start a DXF export job.

```json
{
  "min_lat": 30.44,
  "min_lon": 78.07,
  "max_lat": 30.47,
  "max_lon": 78.10,
  "scale": 1000,
  "include_buildings": true,
  "include_roads": true,
  "export_3d": false
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `min_lat`, `min_lon`, `max_lat`, `max_lon` | float | required | WGS84 bounding box |
| `scale` | int | `1000` | Drawing scale (1:1000) |
| `include_buildings` | bool | `true` | Include building footprints |
| `include_roads` | bool | `true` | Include road network |
| `export_3d` | bool | `false` | Extrude buildings to 3D |

**Response:**
```json
{ "task_id": "abc-123", "status": "queued" }
```

#### `GET /status/{task_id}`

Poll job status. Returns `PENDING` → `STARTED` → `SUCCESS` or `FAILURE`.

```json
{
  "task_id": "abc-123",
  "state": "SUCCESS",
  "filename": "vectomap_2d_1000.dxf",
  "size_bytes": 245780
}
```

#### `GET /download/{task_id}`

Download the `.dxf` file. Opens directly in AutoCAD.

```bash
curl -o map.dxf http://localhost:8000/download/abc-123
```

---

### Elevation — Contour Lines → GeoJSON

#### `POST /elevation/generate`

Download Copernicus GLO-30 DEM and extract contour lines as GeoJSON.

```json
{
  "min_lat": 30.44,
  "min_lon": 78.07,
  "max_lat": 30.47,
  "max_lon": 78.10,
  "interval": 10.0
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `interval` | float | `5.0` | Contour interval in metres. Use `10`–`20` for hills, `1`–`2` for plains |

#### `GET /elevation/status/{task_id}`

```json
{
  "task_id": "xyz-456",
  "state": "SUCCESS",
  "contour_count": 312
}
```

#### `GET /elevation/result/{task_id}`

Returns a GeoJSON `FeatureCollection`. Each feature is a contour `LineString` with `elevation` in metres. Render in Mapbox, Leaflet, DeckGL, or QGIS.

```bash
# Save to file
Invoke-RestMethod "http://localhost:8000/elevation/result/xyz-456" |
  ConvertTo-Json -Depth 100 |
  Out-File -Encoding UTF8 contours.geojson

# Visualise: drag contours.geojson to geojson.io
```

---

### Elevation — Contour Lines → DXF

#### `POST /elevation/dxf/generate`

Same as above but outputs a `.dxf` file — opens directly in AutoCAD.

```json
{
  "min_lat": 30.44,
  "min_lon": 78.07,
  "max_lat": 30.47,
  "max_lon": 78.10,
  "interval": 10.0,
  "scale": 1000
}
```

> Use the same `scale` value as `/generate` so contours align with buildings when both files are overlaid in AutoCAD.

#### `GET /elevation/dxf/status/{task_id}`

#### `GET /elevation/dxf/download/{task_id}`

```bash
curl -o contours.dxf http://localhost:8000/elevation/dxf/download/TASK_ID
```

DXF layers produced:

| Layer | Colour | Description |
|---|---|---|
| `CONTOURS` | Yellow | All contour lines (thin) |
| `CONTOURS_MAJOR` | Cyan | Every ~5th level (thick) |

---

## Test coordinates

| Location | bbox | Best interval | Notes |
|---|---|---|---|
| **Mussoorie** | `30.44, 78.07 → 30.47, 78.10` | 10 m | 1900–2400 m range, ideal for testing |
| **Shimla** | `31.08, 77.15 → 31.12, 77.19` | 10 m | 2000–2300 m range |
| **Pune hills** | `18.36, 73.74 → 18.40, 73.78` | 20 m | 600–1300 m range |
| **Delhi** | `28.628, 77.210 → 28.635, 77.220` | 1 m | Very flat — use small interval |
| **Jalandhar** | `31.320, 75.570 → 31.340, 75.590` | 1 m | Plains — use small interval |

---

## Data sources

| Data | Source | License |
|---|---|---|
| Buildings & Roads | © OpenStreetMap contributors | ODbL |
| Elevation (GLO-30) | Copernicus DEM, ESA / DGED 2023_1 | [Copernicus License](https://spacedata.copernicus.eu/collections/copernicus-digital-elevation-model) |

---

## DXF layer reference

### Base map layers

| Layer | Colour | Content |
|---|---|---|
| `BUILDINGS` | White/7 | 2D building footprints + fill |
| `BUILDINGS_FILL` | 254 | Solid hatch inside buildings |
| `BUILDINGS_3D` | White/7 | 3D extruded building walls |
| `ROAD_MAJOR` | Cyan/5 | Motorway, trunk, primary, secondary |
| `ROAD_MINOR` | Green/4 | All other roads |
| `ROAD_FOOT` | Green/3 | Footways, paths, cycleways |

### Elevation layers

| Layer | Colour | Content |
|---|---|---|
| `CONTOURS` | Yellow/2 | All contour lines, thin |
| `CONTOURS_MAJOR` | Cyan/4 | Major contours (~every 5th level), thick |

---

## Limitations

- **Bbox size:** Max ~5 km² for base map (OSM limit), max ~4°² for elevation (OpenTopography limit)
- **Flat terrain:** Delhi and Punjab plains have <5 m elevation range — use `interval=1.0` for contours
- **OpenTopography rate limit:** Free tier allows limited requests per day. The API key is required for elevation endpoints
- **GLO-30 is a DSM:** Includes buildings and vegetation, not bare ground. Use NASADEM (`demtype=NASADEM`) for bare-ground contours if needed

---

## Roadmap

- [ ] `terrain.py` — slope percentage map
- [ ] `flow.py` — D8 drainage direction + flow accumulation
- [ ] `hydrology.py` — flood risk zones
- [ ] `soil.py` — soil type classification
- [ ] `rational.py` — peak discharge (Q = C·I·A)
- [ ] `scscn.py` — runoff volume (SCS-CN method)
- [ ] AI analyst — natural language site summary

---

## Tech stack

| Component | Technology |
|---|---|
| API | FastAPI + Uvicorn |
| Background jobs | Celery |
| Message broker | Redis 7 |
| OSM data | osmnx + geopandas |
| CAD export | ezdxf |
| Elevation data | rasterio + OpenTopography API |
| Contour extraction | matplotlib (Agg backend) |
| Containerisation | Docker + Docker Compose |

---

## License

MIT License — see [LICENSE](LICENSE) for details.

Data from OpenStreetMap is licensed under ODbL. Copernicus DEM usage is subject to the [Copernicus Data Space terms](https://spacedata.copernicus.eu/collections/copernicus-digital-elevation-model).
