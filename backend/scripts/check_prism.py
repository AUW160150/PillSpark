"""Gate G7: PRISM handshake + a live order that produced trace ids and a trajectory."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app import config  # noqa: E402
from app.prism import prism  # noqa: E402
from app.pipeline import run_order, load_ground_truth  # noqa: E402
from app.schemas import Order  # noqa: E402


def main():
    if not prism.enabled:
        print(f"PRISM CHECK FAILED: not configured (PRISMTRACE_PROJECT_ID / PRISMTRACE_API_KEY missing)"); sys.exit(1)
    h = prism.handshake()
    print("handshake:", json.dumps(h)[:400])
    assert h.get("ok"), h
    p = sorted(config.SYNTHETIC_DIR.glob("*.jpg"))[0]
    o = Order(order_id=f"prism_{int(time.time())}", source_image=str(p), created_at=time.time())
    run_order(o, p, ground_truth=load_ground_truth(p), emit=None)
    prism.flush()
    assert o.status in ("blocked", "ready"), o.error
    assert len(o.prism.get("trace_ids", [])) >= 1, o.prism
    assert o.prism.get("trajectory"), o.prism
    print(json.dumps({"traces": len(o.prism["trace_ids"]), "trajectory": o.prism["trajectory"], "mode": o.llm_mode}))
    print("PRISM CHECK PASSED")


if __name__ == "__main__":
    main()
