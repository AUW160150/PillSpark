"""PillSpark API — FastAPI. Mirrors the BioHarmonize contract the reference frontend polls:
  GET  /api/health
  GET  /api/samples                      list demo images (synthetic / real / user photos)
  POST /api/orders                       multipart 'file' OR json {"sample": "<name>"} → {order_id}
  GET  /api/orders                       list
  GET  /api/orders/{id}/status           {status, stage, progress, events[since], metrics}
  GET  /api/orders/{id}                  full order (fields, candidates, reasons, evidence, prism)
  POST /api/orders/{id}/resolve          {field, value, note, pharmacist} → pharmacist decision
  GET  /api/files/{name}                 serve a sample image
Run: backend/.venv/bin/uvicorn app.main:app --app-dir backend --port 8000 --reload"""
import json
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .pipeline import AGENTS, AGENT_LABELS, load_ground_truth, run_order
from .prism import prism
from .schemas import Order

app = FastAPI(title="PillSpark API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

orders: Dict[str, Order] = {}
_lock = threading.Lock()
UPLOAD_DIR = config.DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
SAMPLE_DIRS = {"synthetic": config.SYNTHETIC_DIR, "real": config.REAL_DIR, "photo": config.PHOTO_DIR, "upload": UPLOAD_DIR}


class ResolveRequest(BaseModel):
    field: str
    value: Optional[Any] = None
    note: Optional[str] = None
    pharmacist: str = "RPh"
    action: str = "accept"          # accept | reject | call_prescriber


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.1.0", "llm_mode": config.LLM_MODE, "llm_mode_reason": config.LLM_MODE_REASON,
            "models": [config.MODEL_PRIMARY, config.MODEL_SECOND], "passes": config.PASSES, "prism_enabled": prism.enabled,
            "agents": [{"key": a, "label": AGENT_LABELS[a]} for a in AGENTS],
            "thresholds": {"verified_min": config.VERIFIED_MIN, "review_min": config.REVIEW_MIN}}


@app.get("/api/samples")
def samples():
    out = []
    for kind, d in SAMPLE_DIRS.items():
        for p in sorted(d.glob("*")):
            if p.suffix.lower() in (".jpg", ".jpeg", ".png"):
                gt = p.with_suffix(".json")
                meta = {}
                if gt.exists():
                    try:
                        g = json.loads(gt.read_text()); meta = {"style": g.get("style"), "degradation": g.get("degradation"), "ambiguous": g.get("ambiguous")}
                    except Exception:
                        pass
                out.append({"name": p.name, "kind": kind, "size_kb": p.stat().st_size // 1024, "has_ground_truth": gt.exists(), **meta})
    return {"samples": out}


def _find_sample(name: str) -> Path:
    for d in SAMPLE_DIRS.values():
        p = d / name
        if p.exists():
            return p
    raise HTTPException(404, f"sample {name} not found")


@app.get("/api/files/{name}")
def get_file(name: str):
    return FileResponse(_find_sample(name))


def _start(path: Path) -> Order:
    order = Order(order_id=f"rx_{uuid.uuid4().hex[:8]}", source_image=str(path), created_at=time.time(), llm_mode=config.LLM_MODE)
    with _lock:
        orders[order.order_id] = order
    gt = load_ground_truth(path)
    threading.Thread(target=run_order, args=(order, path, gt), kwargs={"seed": int(time.time()) % 1000}, daemon=True).start()
    return order


@app.post("/api/orders")
async def create_order(request: Request, file: Optional[UploadFile] = File(None)):
    if file is not None and file.filename:
        suffix = Path(file.filename).suffix.lower() or ".jpg"
        dest = UPLOAD_DIR / f"{int(time.time())}_{uuid.uuid4().hex[:6]}{suffix}"
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        path = dest
    else:
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict) or not body.get("sample"):
            raise HTTPException(400, "send multipart 'file' or json {'sample': '<name>'}")
        path = _find_sample(body["sample"])
    order = _start(path)
    return {"order_id": order.order_id, "status": order.status, "llm_mode": order.llm_mode}


@app.get("/api/orders")
def list_orders():
    return {"orders": [{"order_id": o.order_id, "status": o.status, "stage": o.stage, "progress": o.progress, "source_image": Path(o.source_image).name,
                        "created_at": o.created_at, "review_queue": o.review_queue, "metrics": o.metrics} for o in sorted(orders.values(), key=lambda o: -o.created_at)]}


def _get(order_id: str) -> Order:
    if order_id == "latest":
        if not orders:
            raise HTTPException(404, "no orders yet")
        return max(orders.values(), key=lambda o: o.created_at)
    o = orders.get(order_id)
    if not o:
        raise HTTPException(404, "order not found")
    return o


@app.get("/api/orders/{order_id}/status")
def order_status(order_id: str, since: int = 0):
    o = _get(order_id)
    return {"order_id": o.order_id, "status": o.status, "stage": o.stage, "progress": o.progress, "llm_mode": o.llm_mode, "models": o.models,
            "events": o.events[since:], "next": len(o.events), "metrics": o.metrics, "review_queue": o.review_queue, "error": o.error,
            "prism": {"enabled": o.prism.get("enabled", prism.enabled), "traces": len(o.prism.get("trace_ids", [])), "trajectory": bool(o.prism.get("trajectory"))}}


@app.get("/api/orders/{order_id}")
def order_detail(order_id: str):
    return _get(order_id).model_dump()


@app.post("/api/orders/{order_id}/resolve")
def resolve(order_id: str, req: ResolveRequest):
    o = _get(order_id)
    if req.field not in o.fields:
        raise HTTPException(400, f"unknown field {req.field}")
    fr = o.fields[req.field]
    if req.action == "accept":
        if req.value is None and fr.value is None:
            raise HTTPException(400, "a value is required to accept an unreadable field")
        if req.value is not None:
            fr.value = req.value
        fr.status = "resolved"; fr.confidence = 1.0
    elif req.action == "reject":
        fr.status = "unreadable"; fr.value = None
    elif req.action == "call_prescriber":
        fr.status = "needs_review"
    fr.resolved_by = req.pharmacist
    fr.resolution_note = f"[{req.action}] {req.note or ''}".strip()
    o.events.append({"t": o.events[-1]["t"] + 1 if o.events else 0, "agent": "pharmacist", "kind": "resolution",
                     "text": f"{req.pharmacist} {req.action} {req.field}" + (f" → {req.value!r}" if req.value is not None else "") + (f" ({req.note})" if req.note else "")})
    o.review_queue = [f for f in o.review_queue if o.fields[f].status not in ("verified", "resolved")]
    o.status = "blocked" if o.review_queue else "ready"
    (config.OUTPUT_DIR / f"{o.order_id}.order.json").write_text(o.model_dump_json(indent=2))
    return {"order_id": o.order_id, "status": o.status, "review_queue": o.review_queue, "field": fr.model_dump()}


@app.get("/api/prism/handshake")
def prism_handshake():
    return prism.handshake()


FRONTEND_DIR = config.ROOT / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
