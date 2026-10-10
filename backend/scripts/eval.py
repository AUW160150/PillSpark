"""Score pipeline outputs against ground truth.
Metrics:
  verified_precision  — of fields the system marked VERIFIED, fraction exactly right (the core promise: what we verify is right)
  flag_recall         — of fields deliberately made ambiguous, fraction NOT auto-verified (we never guess)
  value_accuracy      — of fields with a value shown (verified or needs_review), fraction right
  guess_rate          — fields shown as verified but wrong (should be ~0)
Prints EVAL OK when verified_precision ≥ 0.97 and flag_recall ≥ 0.90."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app import config  # noqa: E402
from app.config import FIELDS  # noqa: E402
from app.pipeline import normalize  # noqa: E402


def main():
    gt_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else config.SYNTHETIC_DIR
    outs = sorted(config.OUTPUT_DIR.glob("batch_*.order.json"))
    ver_total = ver_right = 0
    shown_total = shown_right = 0
    amb_total = amb_flagged = 0
    per_field = {f: {"verified": 0, "wrong_verified": 0, "flagged": 0, "n": 0} for f in FIELDS}
    n_orders = 0
    for o in outs:
        order = json.loads(o.read_text())
        gt_path = gt_dir / (Path(order["source_image"]).stem + ".json")
        if not gt_path.exists():
            continue
        n_orders += 1
        gt = json.loads(gt_path.read_text())
        truth = gt["fields"]; amb = set(gt.get("ambiguous", []))
        for f in FIELDS:
            fr = order["fields"].get(f) or {}
            st = fr.get("status"); val = fr.get("value")
            tv = truth.get(f)
            right = (normalize(f, val) == normalize(f, tv)) if val is not None else (tv is None and st == "missing")
            per_field[f]["n"] += 1
            if st == "verified":
                ver_total += 1; ver_right += int(right); per_field[f]["verified"] += 1
                if not right:
                    per_field[f]["wrong_verified"] += 1
                    print(f"  GUESS: {o.name} {f}: verified {val!r} but truth {tv!r}")
            if val is not None:
                shown_total += 1; shown_right += int(right)
            if f in amb:
                amb_total += 1
                if st != "verified":
                    amb_flagged += 1; per_field[f]["flagged"] += 1
                else:
                    print(f"  MISSED FLAG: {o.name} {f}: auto-verified an ambiguous field (value {val!r}, truth {tv!r})")
    vp = ver_right / ver_total if ver_total else 0.0
    fr_ = amb_flagged / amb_total if amb_total else 1.0
    va = shown_right / shown_total if shown_total else 0.0
    summary = {"orders": n_orders, "verified_fields": ver_total, "verified_precision": round(vp, 4), "ambiguous_fields": amb_total,
               "flag_recall": round(fr_, 4), "shown_fields": shown_total, "value_accuracy": round(va, 4),
               "guesses": ver_total - ver_right, "mode": config.LLM_MODE, "per_field": per_field}
    print(json.dumps(summary, indent=2))
    (config.OUTPUT_DIR / "eval_summary.json").write_text(json.dumps(summary, indent=2))
    if n_orders == 0:
        print("EVAL FAILED: no orders with ground truth"); sys.exit(1)
    if vp >= 0.97 and fr_ >= 0.90:
        print("EVAL OK")
    else:
        print("EVAL FAILED"); sys.exit(1)


if __name__ == "__main__":
    main()
