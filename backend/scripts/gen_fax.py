"""Generate synthetic faxed prescriptions + ground-truth JSON sidecars.
Three looks (typed Rx pad w/ handwritten orders, fully handwritten, EHR printout), three degradation levels,
and deliberate ambiguities (smudged digit, qd abbreviation, missing refills/DOB, LASA drug, scribbled qty).
Usage: python scripts/gen_fax.py [--n 24] [--seed 7] [--out ../data/synthetic]"""
import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.registries import npi_valid  # noqa: E402

FONT_DIR = Path("/System/Library/Fonts")
FONTS = {
    "hand": [FONT_DIR / "Noteworthy.ttc", FONT_DIR / "MarkerFelt.ttc"],
    "type": [FONT_DIR / "Courier.ttc"],
    "print": [FONT_DIR / "Helvetica.ttc", FONT_DIR / "HelveticaNeue.ttc"],
}


def font(kind, size, idx=0):
    for p in FONTS[kind]:
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size, index=idx)
            except Exception:
                try:
                    return ImageFont.truetype(str(p), size)
                except Exception:
                    continue
    return ImageFont.load_default()


DRUGS = [  # name, strengths, form, typical sig pieces, qty
    ("Amoxicillin", ["500 mg"], "capsule", ["1 cap PO TID x 10 days"], "30"),
    ("Metformin", ["500 mg", "1000 mg"], "tablet", ["1 tab PO BID with meals"], "60"),
    ("Lisinopril", ["10 mg", "20 mg"], "tablet", ["1 tab PO daily"], "30"),
    ("Atorvastatin", ["20 mg", "40 mg"], "tablet", ["1 tab PO QHS"], "90"),
    ("Amlodipine", ["5 mg", "10 mg"], "tablet", ["1 tab PO daily"], "30"),
    ("Levothyroxine", ["50 mcg", "75 mcg", "100 mcg"], "tablet", ["1 tab PO daily before breakfast"], "90"),
    ("Omeprazole", ["20 mg"], "capsule", ["1 cap PO daily x 14 days"], "14"),
    ("Sertraline", ["50 mg"], "tablet", ["1 tab PO daily"], "30"),
    ("Gabapentin", ["300 mg"], "capsule", ["1 cap PO TID"], "90"),
    ("Prednisone", ["10 mg"], "tablet", ["2 tabs PO daily x 5 days"], "10"),
    ("Azithromycin", ["250 mg"], "tablet", ["2 tabs PO day 1 then 1 tab daily x 4 days"], "6"),
    ("Hydrochlorothiazide", ["25 mg"], "tablet", ["1 tab PO daily"], "30"),
    ("Losartan", ["50 mg"], "tablet", ["1 tab PO daily"], "30"),
    ("Metoprolol tartrate", ["25 mg"], "tablet", ["1 tab PO BID"], "60"),
    ("Ibuprofen", ["600 mg"], "tablet", ["1 tab PO q6h PRN pain"], "30"),
    ("Cephalexin", ["500 mg"], "capsule", ["1 cap PO QID x 7 days"], "28"),
    ("Fluoxetine", ["20 mg"], "capsule", ["1 cap PO daily"], "30"),
    ("Montelukast", ["10 mg"], "tablet", ["1 tab PO QHS"], "30"),
    ("Pantoprazole", ["40 mg"], "tablet", ["1 tab PO daily before breakfast"], "30"),
    ("Escitalopram", ["10 mg"], "tablet", ["1 tab PO daily"], "30"),
    ("Hydroxyzine", ["25 mg"], "tablet", ["1 tab PO TID PRN anxiety"], "30"),      # LASA
    ("Hydralazine", ["25 mg"], "tablet", ["1 tab PO TID"], "90"),                  # LASA
    ("Tramadol", ["50 mg"], "tablet", ["1 tab PO q6h PRN pain"], "20"),            # LASA
    ("Clonidine", ["0.1 mg"], "tablet", ["1 tab PO BID"], "60"),                   # LASA
]
FIRST = ["Maria", "James", "Aisha", "Daniel", "Priya", "Robert", "Elena", "Samuel", "Grace", "Omar", "Linda", "Kevin", "Fatima", "Thomas", "Sofia", "Ahmed"]
LAST = ["Garcia", "Johnson", "Khan", "Nguyen", "Patel", "Williams", "Rossi", "Brown", "Chen", "Hassan", "Martinez", "Lee", "Okafor", "Smith", "Reyes", "Cohen"]
DOCS = [("Sarah", "Mitchell"), ("David", "Park"), ("Rachel", "Goldberg"), ("Michael", "Torres"), ("Anita", "Rao"), ("John", "Smith"), ("Laura", "Bennett"), ("Carlos", "Mendez")]
CLINICS = ["Riverside Family Medicine", "Harlem Internal Medicine Group", "Brooklyn Heights Primary Care", "Morningside Pediatrics & Family", "Queens Boulevard Medical Associates"]


def make_npi(rng):
    while True:
        base = "".join(str(rng.randint(0, 9)) for _ in range(9))
        for d in range(10):
            if npi_valid(base + str(d)):
                return base + str(d)


def make_dea(rng, last):
    digits = [rng.randint(0, 9) for _ in range(6)]
    check = ((digits[0] + digits[2] + digits[4]) + 2 * (digits[1] + digits[3] + digits[5])) % 10
    return rng.choice("ABFM") + last[0].upper() + "".join(map(str, digits)) + str(check)


def rand_date(rng, y0, y1):
    import datetime as dt
    d = dt.date(rng.randint(y0, y1), rng.randint(1, 12), rng.randint(1, 28))
    return d


def scribble(draw, x, y, w, h, rng, color=20):
    pts = [(x + rng.random() * w, y + rng.random() * h) for _ in range(14)]
    draw.line(pts, fill=color, width=rng.randint(3, 5), joint="curve")


def ink_blot(im, x, y, r, rng):
    d = ImageDraw.Draw(im)
    for _ in range(6):
        dx, dy = rng.randint(-r, r), rng.randint(-r // 2, r // 2)
        d.ellipse([x + dx - r, y + dy - r, x + dx + r, y + dy + r], fill=rng.randint(30, 90))


def render(spec, style, rng):
    W, H = 1275, 1650
    im = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(im)
    f = spec["fields"]
    # fax header (every fax has one)
    fh = font("type", 22)
    d.text((40, 20), f"FROM: {spec['clinic'].upper()[:28]}   FAX NO. : {spec['fax']}   {spec['fax_date']}  {spec['fax_time']}  P. 01", font=fh, fill=0)
    d.line([(30, 56), (W - 30, 56)], fill=0, width=2)
    amb = spec["ambiguous"]
    if style == "ehr":
        hf, bf, mono = font("print", 30, 1), font("print", 26), font("type", 26)
        d.text((60, 90), spec["clinic"], font=hf, fill=0)
        d.text((60, 130), f"{spec['address']}  ·  Tel {spec['phone']}  ·  Fax {spec['fax']}", font=bf, fill=0)
        d.text((60, 190), "ELECTRONIC PRESCRIPTION — FAX COPY", font=hf, fill=0)
        y = 260
        rows = [("Patient", f["patient_name"]), ("DOB", f["patient_dob"] and _us(f["patient_dob"])), ("Address", spec["pt_address"]),
                ("Date written", _us(f["date_written"])), ("Prescriber", f["prescriber_name"]), ("NPI", f["prescriber_npi"]), ("DEA", f["prescriber_dea"])]
        for k, v in rows:
            if v is None:
                continue
            d.text((60, y), f"{k}:", font=bf, fill=0); d.text((300, y), str(v), font=mono, fill=0); y += 40
        y += 30; d.line([(60, y), (W - 60, y)], fill=0, width=2); y += 25
        d.text((60, y), "Rx", font=font("print", 40, 1), fill=0); y += 55
        d.text((60, y), f"{f['drug_name']} {f['strength']} {f['dosage_form']}", font=font("print", 30, 1), fill=0); y += 45
        d.text((60, y), f"Sig: {f['sig']}", font=bf, fill=0); y += 40
        d.text((60, y), f"Disp: #{f['quantity']} ({f['dosage_form']}s)", font=bf, fill=0); y += 40
        if f["refills"] is not None:
            d.text((60, y), f"Refills: {f['refills']}", font=bf, fill=0); y += 40
        d.text((60, y + 40), "Electronically signed by " + f["prescriber_name"], font=bf, fill=0)
    else:
        pad = font("type", 26) if style == "typed" else font("hand", 30, 1)
        head = font("type", 30) if style == "typed" else font("hand", 34, 1)
        hand = font("hand", 38, rng.randint(0, 1))
        d.text((60, 90), spec["clinic"], font=head, fill=0)
        d.text((60, 135), f"{spec['address']}", font=pad, fill=0)
        d.text((60, 170), f"Tel {spec['phone']}   Fax {spec['fax']}", font=pad, fill=0)
        d.text((60, 215), f"{f['prescriber_name']}, MD", font=pad, fill=0)
        d.text((700, 215), f"NPI {f['prescriber_npi']}" if f["prescriber_npi"] else "", font=pad, fill=0)
        d.text((700, 250), f"DEA {f['prescriber_dea']}" if f["prescriber_dea"] else "", font=pad, fill=0)
        d.line([(60, 300), (W - 60, 300)], fill=0, width=3)
        d.text((60, 320), "Name", font=pad, fill=0); d.text((180, 310), f["patient_name"], font=hand, fill=10)
        d.line([(170, 360), (760, 360)], fill=0, width=1)
        d.text((790, 320), "DOB", font=pad, fill=0)
        if f["patient_dob"]:
            d.text((880, 310), _us(f["patient_dob"]), font=hand, fill=10)
        d.line([(870, 360), (1200, 360)], fill=0, width=1)
        d.text((60, 385), "Address", font=pad, fill=0); d.text((200, 375), spec["pt_address"], font=hand, fill=10)
        d.text((60, 440), "Date", font=pad, fill=0); d.text((160, 430), _us(f["date_written"]), font=hand, fill=10)
        d.text((60, 520), "Rx", font=font("type", 60), fill=0)
        y = 540
        d.text((200, y), f"{f['drug_name']}  {f['strength']}", font=font("hand", 44, 0), fill=5); y += 70
        d.text((200, y), f"{f['dosage_form']}s   #{f['quantity']}", font=hand, fill=5); y += 60
        d.text((200, y), f"Sig: {f['sig']}", font=hand, fill=5); y += 70
        d.text((200, y), "Refills: " + (str(f["refills"]) if f["refills"] is not None else ""), font=hand, fill=5); y += 70
        d.text((60, 1150), "☐ Dispense as written     ☒ Substitution permitted", font=pad, fill=0)
        d.text((60, 1250), "Signature", font=pad, fill=0)
        scribble(d, 230, 1215, 320, 70, rng, color=15)
        d.line([(220, 1290), (640, 1290)], fill=0, width=1)
    # --- deliberate ambiguities (ground truth records which fields are expected to be flagged)
    if "strength" in amb:   # blot over a digit of the strength
        bx = 200 + rng.randint(40, 120) if style != "ehr" else 60 + rng.randint(160, 260)
        by = 540 + 20 if style != "ehr" else 260 + 7 * 40 + 55 + 110 + 15
        ink_blot(im, bx + len(f["drug_name"]) * (22 if style != "ehr" else 15) + 20, by, 11, rng)
    if "quantity" in amb and style != "ehr":   # scribble through the quantity
        scribble(d, 420, 600, 140, 50, rng, color=40)
    if "quantity" in amb and style == "ehr":
        ink_blot(im, 170, 260 + 7 * 40 + 55 + 110 + 95, 10, rng)
    return im


def _us(iso):
    y, m, dd = iso.split("-")
    return f"{int(m):02d}/{int(dd):02d}/{y}"


def degrade(im, level, rng):
    im = im.convert("L")
    if level == "clean":
        im = im.filter(ImageFilter.GaussianBlur(0.4))
        return im.convert("L")
    angle = rng.uniform(-1.2, 1.2) if level == "light" else rng.uniform(-2.5, 2.5)
    im = im.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=255)
    im = im.filter(ImageFilter.GaussianBlur(0.8 if level == "light" else 1.4))
    a = np.asarray(im, dtype=np.float32)
    noise = rng.uniform(6, 12) if level == "light" else rng.uniform(14, 24)
    a = a + np.random.default_rng(rng.randint(0, 10**6)).normal(0, noise, a.shape)
    # fax tends to crush contrast then re-threshold
    a = np.clip((a - 128) * (1.25 if level == "light" else 1.6) + 128, 0, 255)
    im = Image.fromarray(a.astype(np.uint8))
    if level == "heavy":
        w, h = im.size
        im = im.resize((w // 2, int(h / 2.2)), Image.BILINEAR).resize((w, h), Image.NEAREST)   # 100-dpi fax look
        d = ImageDraw.Draw(im)
        for _ in range(rng.randint(2, 5)):                                                     # streaks
            y = rng.randint(80, h - 80)
            d.line([(0, y), (w, y)], fill=rng.choice([0, 255]), width=rng.randint(1, 3))
        # speckle
        sp = np.asarray(im).copy()
        mask = np.random.default_rng(rng.randint(0, 10**6)).random(sp.shape) < 0.004
        sp[mask] = 0
        im = Image.fromarray(sp)
    im = ImageOps.autocontrast(im, cutoff=1)
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=str(ROOT / "data" / "synthetic"))
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    styles = ["typed", "hand", "ehr"]
    levels = ["clean", "light", "heavy"]
    amb_menu = [[], [], ["strength"], ["quantity"], ["refills"], ["patient_dob"], ["sig"], ["strength", "quantity"], ["drug_name"]]
    manifest = []
    for i in range(args.n):
        style = styles[i % 3]; level = levels[(i // 3) % 3]
        amb = list(amb_menu[i % len(amb_menu)])
        drug = rng.choice(DRUGS) if "drug_name" not in amb else rng.choice([d for d in DRUGS if d[0] in ("Hydroxyzine", "Hydralazine", "Tramadol", "Clonidine")])
        name, strengths, form, sigs, qty = drug
        first, last = rng.choice(FIRST), rng.choice(LAST)
        df, dl = rng.choice(DOCS)
        sig = sigs[0]
        if "sig" in amb:
            sig = sig.replace("daily", "q.d.").replace("BID", "q.d.") if ("daily" in sig or "BID" in sig) else sig + " q.d."
        dob = rand_date(rng, 1940, 2015).isoformat() if "patient_dob" not in amb else None
        refills = str(rng.choice([0, 0, 1, 2, 3, 5])) if "refills" not in amb else None
        written = rand_date(rng, 2026, 2026)
        if written.month > 10:
            written = written.replace(month=rng.randint(7, 10))
        fields = {
            "patient_name": f"{first} {last}", "patient_dob": dob,
            "drug_name": name, "strength": rng.choice(strengths), "dosage_form": form, "quantity": qty, "sig": sig, "refills": refills,
            "prescriber_name": f"Dr. {df} {dl}", "prescriber_npi": make_npi(rng), "prescriber_dea": make_dea(rng, dl),
            "date_written": written.isoformat(),
        }
        if style == "hand" and rng.random() < 0.5:
            fields["prescriber_dea"] = None
        spec = {"id": f"rx_{i:03d}_{style}_{level}", "style": style, "degradation": level, "ambiguous": amb, "fields": fields,
                "clinic": rng.choice(CLINICS), "address": f"{rng.randint(100, 999)} {rng.choice(['Amsterdam Ave', 'Broadway', 'Atlantic Ave', 'Court St', 'Lexington Ave'])}, New York, NY 1{rng.randint(0, 1)}0{rng.randint(10, 99)}",
                "phone": f"(212) 555-{rng.randint(1000, 9999)}", "fax": f"(212) 555-{rng.randint(1000, 9999)}",
                "pt_address": f"{rng.randint(10, 999)} {rng.choice(['W 110th St', 'Flatbush Ave', 'Steinway St', 'Riverside Dr'])}, NY",
                "fax_date": written.strftime("%b %d %Y").upper(), "fax_time": f"{rng.randint(8, 17):02d}:{rng.randint(0, 59):02d}",
                "expected_flags": amb + (["drug_name"] if name in ("Hydroxyzine", "Hydralazine", "Tramadol", "Clonidine") and "drug_name" not in amb else [])}
        im = render(spec, style, rng)
        im = degrade(im, level, rng)
        img_path = out / f"{spec['id']}.jpg"
        im.save(img_path, quality=55 if level != "clean" else 80)
        (out / f"{spec['id']}.json").write_text(json.dumps(spec, indent=2))
        manifest.append({"image": img_path.name, "style": style, "degradation": level, "ambiguous": amb})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"generated {len(manifest)} faxes → {out}")


if __name__ == "__main__":
    main()
