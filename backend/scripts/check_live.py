"""Gates G6/G8: run the LIVE pipeline on N images and assert the never-guess contract.
With ground truth: no verified field may contradict truth. Without: every order must end blocked/ready and unreadable fields carry no value."""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app import config  # noqa: E402
from app.config import FIELDS  # noqa: E402
from app.pipeline import run_order, load_ground_truth, normalize  # noqa: E402
from app.schemas import Order  # noqa: E402
from app.prism import prism  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(config.SYNTHETIC_DIR))
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--no-ground-truth", action="store_true")
    args = ap.parse_args()
    if config.LLM_MODE != "live":
        print(f"LIVE CHECK FAILED: mode is {config.LLM_MODE} ({config.LLM_MODE_REASON})"); sys.exit(1)
    d = (ROOT / args.dir) if not Path(args.dir).is_absolute() else Path(args.dir)
    imgs = sorted(p for p in d.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if not args.no_ground_truth:
        imgs = [p for p in imgs if p.with_suffix(".json").exists()]
        # spread across styles/levels: take every k-th
        step = max(1, len(imgs) // args.limit)
        imgs = imgs[::step][: args.limit]
    else:
        imgs = imgs[: args.limit]
    bad, verified, checked = [], 0, 0
    for i, p in enumerate(imgs):
        gt = None if args.no_ground_truth else load_ground_truth(p)
        o = Order(order_id=f"live_{p.stem}", source_image=str(p), created_at=time.time())
        run_order(o, p, ground_truth=gt, emit=None, seed=i)
        if o.status not in ("blocked", "ready"):
            bad.append(f"{p.name}: status {o.status} {o.error}"); continue
        live_passes = [rp for rp in o.raw_passes if rp.get("mode") == "live" and rp.get("parsed")]
        if not live_passes:
            bad.append(f"{p.name}: no successful live pass"); continue
        for f in FIELDS:
            fr = o.fields[f]
            if fr.status == "unreadable" and fr.value is not None:
                bad.append(f"{p.name}: {f} unreadable but value shown")
            if gt and fr.status == "verified":
                verified += 1
                if normalize(f, fr.value) != normalize(f, gt["fields"].get(f)):
                    bad.append(f"{p.name}: {f} VERIFIED {fr.value!r} but truth {gt['fields'].get(f)!r}")
        checked += 1
        print(f"{p.name:34s} {o.status:8s} models={o.models} V={o.metrics.get('verified')} flagged={o.review_queue}")
    prism.flush()
    print(json.dumps({"orders": checked, "verified_fields": verified, "problems": bad}, indent=2))
    if checked and not bad:
        print("LIVE CHECK PASSED")
    else:
        print("LIVE CHECK FAILED"); sys.exit(1)


if __name__ == "__main__":
    main()
