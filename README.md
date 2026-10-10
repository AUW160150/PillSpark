# PillSpark — faxed prescriptions → verified orders, and honest about what it can't read

Demo Video: https://www.youtube.com/watch?v=l0NVlg1GJfI 

Pharmacies still receive prescriptions as blurry faxes that someone retypes by hand. PillSpark turns a fax image into a
structured order (patient, drug, strength, form, quantity, directions, refills, prescriber, date) and **flags every
uncertain field for a pharmacist instead of guessing**.

Built at the NicrronNinoo Columbia Hackathon with **Nicrron** (one key, many vision models) and **Block Convey PRISM**
(tracing, scoring, failure detection).

## How it handles uncertainty

Every field carries `value · confidence · status · reasons · candidates · evidence`.

| status | meaning | what the pharmacist sees |
|---|---|---|
| `verified` | all extraction passes agree, registry confirms, no safety rule tripped | green check |
| `needs_review` | value shown with the specific doubt | "2 of 3 passes read **10 mg**, one read 40 mg" |
| `unreadable` | **value withheld** (null); candidates listed | "pick one or call the prescriber" |
| `missing` | not on the fax | "required field missing" |

Confidence = blend of the model's self-reported confidence, agreement across independent passes (two vision models,
repeated sampling via Nicrron), and registry match score. Hard rules: any pass marking a token illegible caps the
field below the review line; a look-alike/sound-alike drug with non-unanimous readings caps it too; a dose outside the
usual range, an ISMP error-prone abbreviation (`q.d.`), a failed NPI/DEA checksum or a prescriber not in NPPES all
block auto-verification. An order is `blocked` until every flagged field is resolved by a pharmacist.

## Pipeline (six agents)

```
fax image ─► Intake (quality score) ─► Extraction (Nicrron vision, K passes) ─► Consensus (per-field vote)
          ─► Verification (RxNorm drug+strength · NPPES prescriber · Luhn/DEA · sig parser · LASA · dose range)
          ─► Triage (confidence, flag, never guess) ─► Order (JSON + PRISM trajectory)
```

Every vision call is logged to PRISM with `trace_llm` (image bytes replaced by a placeholder; per-field confidences in
metadata) and every order is submitted as a PRISM trajectory whose `final_status` is `needs_review` when anything was
flagged, so PRISM's scoring and failure detection see exactly where the pipeline was unsure.

## Run it

```bash
python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt
cp backend/.env.example .env            # add NICRRON_API_KEY, PRISMTRACE_PROJECT_ID, PRISMTRACE_API_KEY
backend/.venv/bin/python backend/scripts/gen_fax.py --n 24     # synthetic faxes + ground truth → data/synthetic
backend/.venv/bin/uvicorn app.main:app --app-dir backend --port 8000
curl -X POST localhost:8000/api/orders -H 'content-type: application/json' -d '{"sample":"rx_004_hand_light.jpg"}'
curl localhost:8000/api/orders/latest/status
```

No `NICRRON_API_KEY` → `LLM_MODE=mock` (perturbed ground truth) so the whole pipeline and gates run offline.

## Evaluate

```bash
LLM_MODE=mock backend/.venv/bin/python backend/scripts/run_batch.py --quiet && backend/.venv/bin/python backend/scripts/eval.py
```
Reports `verified_precision` (of fields we auto-verified, how many were exactly right — the promise), `flag_recall`
(of deliberately ambiguous fields, how many we refused to auto-verify) and `guesses` (should be 0).

## Data

No public full-page faxed-prescription dataset with labels exists, so `scripts/gen_fax.py` renders US-style faxes in
three looks (typed Rx pad with handwritten orders, fully handwritten, EHR printout) at three degradation levels, with
deliberate ambiguities (ink blot on a strength digit, scribbled quantity, `q.d.`, missing refills/DOB, look-alike drug).
`data/real_samples/` holds six real *handwritten Indian hospital case notes* (`tavishm/100-handwritten-medical-records`) —
not faxes, multi-drug, two without any prescription — kept only as a handwriting stress test that must end `blocked`.
`data/print_pack/pillspark_print_pack.pdf` is the clean set for printing → faxing/photographing (`data/user_photos/`). NPIs in synthetic data are Luhn-valid but fictitious, so NPPES flags them — by design.

## Layout
See `PLAN.md`. `LOG.md` is the append-only build log; `GATES.md` is the completion ledger.
