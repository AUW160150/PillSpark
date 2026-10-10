"""Build a printable PDF of the synthetic prescriptions (clean renders, letter size, one per page) plus an index page.
Print it, fax it or photograph it, drop the photos in data/user_photos/ named after the rx id (e.g. rx_004.jpg) and the
pipeline will pick up the matching ground truth for evaluation.
Usage: python scripts/make_print_pack.py [--ids rx_000,rx_004,...]"""
import argparse
import json
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))
from gen_fax import render, font  # noqa: E402
from app.config import SYNTHETIC_DIR  # noqa: E402

OUT_DIR = ROOT / "data" / "print_pack"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    specs = sorted(SYNTHETIC_DIR.glob("rx_*.json"))
    if args.ids:
        keep = {i.strip() for i in args.ids.split(",")}
        specs = [s for s in specs if any(s.stem.startswith(k) for k in keep)]
    pages, index_rows = [], []
    for sp in specs:
        spec = json.loads(sp.read_text())
        rng = random.Random(hash(spec["id"]) & 0xFFFF)
        im = render(spec, spec["style"], rng).convert("L")          # clean: the printer/fax/camera adds the degradation
        d = ImageDraw.Draw(im)
        d.text((40, im.height - 40), f"PillSpark test sheet {spec['id']}  ·  synthetic, not a real prescription", font=font("type", 18), fill=120)
        pages.append(im)
        f = spec["fields"]
        index_rows.append(f"{spec['id']:28s} {spec['style']:6s} ambiguous={','.join(spec['ambiguous']) or '-':22s} {f['drug_name']} {f['strength']} #{f['quantity']}  {f['sig']}")
        im.save(OUT_DIR / f"{spec['id']}_print.png")
    idx = Image.new("L", (1275, 1650), 255)
    d = ImageDraw.Draw(idx)
    d.text((60, 60), "PillSpark print pack — index (keep this page, do not fax it)", font=font("type", 28), fill=0)
    y = 120
    for row in index_rows:
        d.text((60, y), row, font=font("type", 15), fill=0); y += 26
    d.text((60, y + 30), "Photograph each sheet flat under even light, or fax it to yourself. Save as data/user_photos/<rx_id>.jpg", font=font("type", 16), fill=0)
    pdf = OUT_DIR / "pillspark_print_pack.pdf"
    idx.save(pdf, save_all=True, append_images=pages, resolution=150.0)
    (OUT_DIR / "index.txt").write_text("\n".join(index_rows))
    print(f"{len(pages)} sheets + index → {pdf} ({pdf.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
