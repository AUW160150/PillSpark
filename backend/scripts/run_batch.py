"""Run the pipeline over every image in a folder (default data/synthetic). Writes output/<id>.order.json.
Usage: python scripts/run_batch.py [--dir ../data/synthetic] [--limit N] [--quiet]"""
import argparse
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app import config  # noqa: E402
from app.pipeline import run_order, load_ground_truth  # noqa: E402
from app.schemas import Order  # noqa: E402
from app.prism import prism  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(config.SYNTHETIC_DIR))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    imgs = sorted(p for p in Path(args.dir).iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if args.limit:
        imgs = imgs[: args.limit]
    print(f"mode={config.LLM_MODE} ({config.LLM_MODE_REASON}) prism={'on' if prism.enabled else 'off'} images={len(imgs)}")
    rows = []
    for i, p in enumerate(imgs):
        gt = load_ground_truth(p)
        order = Order(order_id=f"batch_{p.stem}", source_image=str(p), created_at=time.time())
        run_order(order, p, ground_truth=gt, emit=None if args.quiet else (lambda e: print(f"   [{e['agent']}/{e['kind']}] {e['text']}")), seed=i)
        m = order.metrics
        rows.append((p.name, order.status, m.get("verified"), m.get("needs_review"), m.get("unreadable"), m.get("missing"), ",".join(order.review_queue)))
        print(f"{p.name:34s} {order.status:8s} V={m.get('verified')} R={m.get('needs_review')} U={m.get('unreadable')} M={m.get('missing')}  flagged: {', '.join(order.review_queue) or '-'}")
    prism.flush()
    print(f"done: {len(rows)} orders → {config.OUTPUT_DIR}")
    print("BATCH OK" if rows and all(r[1] != "error" for r in rows) else "BATCH FAILED")


if __name__ == "__main__":
    main()
