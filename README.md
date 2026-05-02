# UrbanFabric

**Automated Site Analysis Tool for Architects and Urban Planners**

UrbanFabric generates production-ready CAD drawings of any location on Earth from a bounding box — buildings and roads — delivered as `.dxf` files that open directly in AutoCAD and Civil 3D.

No manual tracing. No paid GIS software. Just coordinates → DXF.

---

## Demo

| Input | Output |
|---|---|
| Bounding box coordinates | `.dxf` file with buildings + roads |
| Scale: 1:1000 | Layers: `BUILDINGS`, `ROAD_MAJOR`, `ROAD_MINOR`, `ROAD_FOOT` |
| 2D or 3D mode | Opens directly in AutoCAD |

**Cities tested:** Jalandhar · Borivali Mumbai · Delhi

---

## Architecture

```
┌─────────────┐    POST /generate     ┌──────────────┐
│   Client    │ ────────────────────► │   FastAPI    │
│  (Swagger / │                       │  hello_api   │
│   curl /    │ ◄────────────────────  │              │
│  frontend)  │    { task_id }        └──────┬───────┘
└─────────────┘                             │
                                            │ .delay()
                                            ▼
                                     ┌──────────────┐
                                     │    Celery    │
                                     │    Worker    │
                                     └──────┬───────┘
                                            │
                                            ▼
                                    finalexporter.py
                                    OSM → DXF bytes
                                            │
                                            ▼
                                       ┌─────────┐
                                       │  Redis  │
                                       │ base64  │
                                       │  result │
                                       └─────────┘
```

**Three Docker services — nothing else needed:**

| Service | Role | Port |
|---|---|---|
| `redis` | Message broker + result store | 6379 |
| `api` | FastAPI — receives requests, returns task_id | 8000 |
| `worker` | Celery — runs OSM fetch + DXF export | — |

---

## Project structure

```
urban_fabric/
├── docker-compose.yml
└── backend/
    ├── Dockerfile
    ├── requirements.txt
    ├── celery_app.py        ← Redis broker config
    ├── hello_api.py         ← All FastAPI endpoints
    ├── tasks.py             ← Celery task definitions
    └── finalexporter.py     ← OSM → DXF export engine
```

---

## Quickstart

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running

### 1. Clone the repository

```bash
git clone https://github.com/your-username/urban_fabric.git
cd urban_fabric
```

### 2. Start all services

```bash
docker compose up --build
```

Wait until all three services are ready:

```
redis-1   | Ready to accept connections
api-1     | Uvicorn running on http://0.0.0.0:8000
worker-1  | celery@... ready.
```

### 3. Open Swagger UI

```
http://localhost:8000/docs
```

All endpoints are interactive — no curl needed to test.

---

## API

The API follows a **queue → poll → download** pattern. Every job returns a `task_id` immediately. The file is ready when status is `SUCCESS`.

```
POST /generate          ← start job, get task_id
GET  /status/{task_id}  ← poll until SUCCESS
GET  /download/{task_id}← download the .dxf file
```

---

### `POST /generate`

Start a DXF export job.

**Request body:**

```json
{
  "min_lat": 28.628,
  "min_lon": 77.210,
  "max_lat": 28.635,
  "max_lon": 77.220,
  "scale": 1000,
  "include_buildings": true,
  "include_roads": true,
  "export_3d": false
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `min_lat` | float | required | South edge of bounding box |
| `min_lon` | float | required | West edge of bounding box |
| `max_lat` | float | required | North edge of bounding box |
| `max_lon` | float | required | East edge of bounding box |
| `scale` | int | `1000` | Drawing scale — `1000` means 1:1000 |
| `include_buildings` | bool | `true` | Include building footprints |
| `include_roads` | bool | `true` | Include road network |
| `export_3d` | bool | `false` | Extrude buildings to 3D using OSM level data |

**Response:**

```json
{
  "task_id": "3f2a1c8e-4b7d-4e2a-9f1b-abc123def456",
  "status": "queued"
}
```

---

### `GET /status/{task_id}`

Poll for job status.

**Possible states:**

| State | Meaning |
|---|---|
| `PENDING` | Job queued, worker hasn't picked it up yet |
| `STARTED` | Worker is fetching OSM data and building DXF |
| `SUCCESS` | Done — call `/download` to get the file |
| `FAILURE` | Error — check the `error` field |

**Response (SUCCESS):**

```json
{
  "task_id": "3f2a1c8e-4b7d-4e2a-9f1b-abc123def456",
  "state": "SUCCESS",
  "filename": "vectomap_2d_1000.dxf",
  "size_bytes": 245780
}
```

**Response (FAILURE):**

```json
{
  "task_id": "...",
  "state": "FAILURE",
  "error": "No OSM data returned for this bbox."
}
```

---

### `GET /download/{task_id}`

Download the `.dxf` file. Streams directly — no intermediate file on disk.

**PowerShell:**
```powershell
curl -o map.dxf http://localhost:8000/download/YOUR_TASK_ID
```

**curl:**
```bash
curl -OJ http://localhost:8000/download/YOUR_TASK_ID
```

Opens directly in AutoCAD, Civil 3D, BricsCAD, or any DXF-compatible software.

---

## DXF layers

Every exported file uses a consistent layer structure:

| Layer | Colour | Lineweight | Content |
|---|---|---|---|
| `BUILDINGS` | White | 0.25 mm | Building outlines + solid fill (2D) |
| `BUILDINGS_FILL` | 254 | 0 mm | Solid hatch inside buildings |
| `BUILDINGS_3D` | White | 0.13 mm | 3D extruded building walls + roof |
| `ROAD_MAJOR` | Cyan | 0.50 mm | Motorway, trunk, primary, secondary |
| `ROAD_MINOR` | Green | 0.25 mm | All other roads |
| `ROAD_FOOT` | Green | 0.13 mm | Footways, paths, cycleways, steps |

---

## Test coordinates

| City | min_lat | min_lon | max_lat | max_lon | Notes |
|---|---|---|---|---|---|
| **Delhi, Connaught Place** | 28.628 | 77.210 | 28.635 | 77.220 | Dense urban — good first test |
| **Jalandhar, City Centre** | 31.320 | 75.570 | 31.340 | 75.590 | Mid-size Indian city |
| **Borivali, Mumbai** | 19.228 | 72.854 | 19.242 | 72.868 | High-density residential |
| **Shimla, Ridge** | 31.098 | 77.168 | 31.108 | 77.180 | Hill station, organic road network |

> **Bbox limit:** Keep each side under ~0.05° (~5 km). Larger areas will be rejected with a clear error message.

---

## How the export works

1. **OSM fetch** — `osmnx` downloads building footprints and road centrelines for the bbox
2. **UTM projection** — all geometries are projected to the local UTM zone for accurate metric scaling
3. **Zero anchor** — the bottom-left corner of the bounding union becomes `(0, 0)` in DXF space
4. **DXF construction** — `ezdxf` writes each building as an `LWPOLYLINE` + `HATCH`, each road as an `LWPOLYLINE`
5. **In-memory delivery** — the DXF is encoded as base64 and stored in Redis. `/download` decodes and streams it. Nothing is written to disk at any point.

---

## Limitations

- **Bbox size:** Maximum ~5 km² per request. Larger areas return a `400` error
- **OSM coverage:** Quality depends on OpenStreetMap data for the region. Well-mapped cities produce better results
- **3D heights:** Building heights come from OSM `height` and `building:levels` tags. Where tags are missing, a default of 3 floors × 3.5 m is used
- **Road geometry:** Roads are exported as centrelines, not road-width polygons

---

## Roadmap

The following modules are under active development:

- [ ] `elevation.py` — Copernicus GLO-30 contour lines (DXF + GeoJSON)
- [ ] `terrain.py` — slope percentage map
- [ ] `flow.py` — D8 drainage direction + flow accumulation
- [ ] `hydrology.py` — flood risk zones
- [ ] `soil.py` — soil type classification
- [ ] `rational.py` — peak discharge (Q = C·I·A)
- [ ] `scscn.py` — runoff volume (SCS-CN method)
- [ ] AI analyst — natural language site summary

---

## Tech stack

| Layer | Technology |
|---|---|
| API framework | FastAPI + Uvicorn |
| Background jobs | Celery |
| Message broker | Redis 7 |
| OSM data | osmnx + geopandas + shapely |
| CAD export | ezdxf |
| Containerisation | Docker + Docker Compose |
| Language | Python 3.11 |

---

## Data source

Building and road data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, licensed under the [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/).

---

## License

MIT License — see [LICENSE](LICENSE) for details.
