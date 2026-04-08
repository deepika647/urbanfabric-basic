"""
tasks.py — Celery worker
Returns DXF as base64-encoded bytes in the result dict.
No files are written to disk.
"""

import base64
from celery_app import celery_app
from finalexporter import export_to_dxf_bytes


@celery_app.task(bind=True, time_limit=300, soft_time_limit=280)
def run_export_task(
    self,
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    scale: int,
    include_buildings: bool,
    include_roads: bool,
    export_3d: bool,
):
    """
    Runs the DXF export in the background.

    Returns the DXF as base64 so it can be stored in Redis safely.
    Redis stores strings/bytes — raw bytes can cause encoding issues,
    base64 is always safe to store and decode.
    """
    dxf_bytes = export_to_dxf_bytes(
        min_lon=min_lon,
        min_lat=min_lat,
        max_lon=max_lon,
        max_lat=max_lat,
        scale=scale,
        include_buildings=include_buildings,
        include_roads=include_roads,
        export_3d=export_3d,
    )

    # Encode to base64 string for safe Redis storage
    encoded = base64.b64encode(dxf_bytes).decode("utf-8")

    mode = "3d" if export_3d else "2d"
    filename = f"vectomap_{mode}_{scale}.dxf"

    return {
        "status": "done",
        "filename": filename,
        "dxf_b64": encoded,          # base64 string stored in Redis
        "size_bytes": len(dxf_bytes),
    }