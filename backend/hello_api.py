"""
hello_api.py — VectoMap FastAPI Backend
No files stored on disk. DXF streamed directly from Redis result.
"""

import base64
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from tasks import run_export_task
from celery_app import celery_app

app = FastAPI(title="VectoMap API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten to your domain in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request model ─────────────────────────────────────────────

class GenerateRequest(BaseModel):
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float
    scale: int           = 1000
    include_buildings: bool = True
    include_roads: bool     = True
    export_3d: bool         = False


# ── Endpoints ─────────────────────────────────────────────────

@app.get("/")
def root():
    return {"message": "VectoMap API v3 — no disk writes"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/generate")
def generate(req: GenerateRequest):
    """
    Start a DXF export job.
    Returns task_id immediately — export runs in Celery background.
    """
    job = run_export_task.delay(
        req.min_lon,
        req.min_lat,
        req.max_lon,
        req.max_lat,
        req.scale,
        req.include_buildings,
        req.include_roads,
        req.export_3d,
    )
    return {"task_id": job.id, "status": "queued"}


@app.get("/status/{task_id}")
def check_status(task_id: str):
    """
    Poll for job status.
    Returns: PENDING | STARTED | SUCCESS | FAILURE
    When SUCCESS: includes filename and size — but NOT the file data.
    Call /download/{task_id} to get the actual file.
    """
    task = celery_app.AsyncResult(task_id)

    response = {"task_id": task_id, "state": task.state}

    if task.state == "SUCCESS":
        result = task.result
        # Return metadata only — not the full base64 blob
        response["filename"]   = result["filename"]
        response["size_bytes"] = result["size_bytes"]

    elif task.state == "FAILURE":
        response["error"] = str(task.result)

    return response


@app.get("/download/{task_id}")
def download_file(task_id: str):
    """
    Stream the DXF file directly to the user.
    Decodes base64 from Redis result → returns as application/dxf.
    No file path, no disk — pure in-memory stream.
    """
    task = celery_app.AsyncResult(task_id)

    if not task.successful():
        raise HTTPException(
            status_code=400,
            detail=f"Task not ready. Current state: {task.state}",
        )

    result = task.result

    # Decode base64 → raw DXF bytes
    try:
        dxf_bytes = base64.b64decode(result["dxf_b64"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Decode error: {e}")

    filename = result.get("filename", "vectomap_export.dxf")

    # Stream bytes directly — no FileResponse, no disk path needed
    return Response(
        content=dxf_bytes,
        media_type="application/dxf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(dxf_bytes)),
        },
    )