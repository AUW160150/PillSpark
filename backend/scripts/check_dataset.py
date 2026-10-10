"""Gate G1: synthetic set is complete, labelled, and varied. Negative control: a temp dir with a JSON-less image fails."""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import FIELDS, SYNTHETIC_DIR  # noqa: E402


def audit(d: Path):
    imgs = sorted(p for p in d.glob("*.jpg"))
    problems = []
    styles, levels, amb = set(), set(), 0
    for p in imgs:
        gt = p.with_suffix(".json")
        if not gt.exists():
            problems.append(f"{p.name}: no ground truth"); continue
        g = json.loads(gt.read_text())
        if set(g.get("fields", {}).keys()) != set(FIELDS):
            problems.append(f"{p.name}: field keys mismatch")
        styles.add(g.get("style")); levels.add(g.get("degradation")); amb += bool(g.get("ambiguous"))
        if p.stat().st_size < 20_000:
            problems.append(f"{p.name}: suspiciously small image")
    return imgs, problems, styles, levels, amb


def main():
    imgs, problems, styles, levels, amb = audit(SYNTHETIC_DIR)
    assert not problems, problems
    assert len(imgs) >= 24, f"only {len(imgs)} images"
    assert styles == {"typed", "hand", "ehr"}, styles
    assert levels == {"clean", "light", "heavy"}, levels
    assert amb >= 12, f"only {amb} images carry ambiguity labels"
    # negative control: an unlabeled image must be reported
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "x.jpg"; bad.write_bytes(b"\xff\xd8" + b"0" * 30000)
        _, probs, *_ = audit(Path(td))
        assert probs and "no ground truth" in probs[0], "negative control failed to fail"
    print(f"{len(imgs)} images · styles {sorted(styles)} · levels {sorted(levels)} · {amb} with ambiguity labels · negative control raised")
    print("DATASET OK")


if __name__ == "__main__":
    main()
