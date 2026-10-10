# PillSpark — Plan

**Track:** Faxed prescription images → structured, verified orders; uncertain fields go to a pharmacist, never guessed.
**Sponsors in use:** Nicrron (LLM gateway, vision extraction) · Block Convey PRISM (tracing, scoring, trajectories, failure detection).
**Reference UI:** `../YC/frontend` (BioHarmonize) — stepper + live log + metrics, FastAPI polling.

## Phases
| Phase | Deliverable | Status |
|---|---|---|
| 1 | Backend engine: synthetic fax generator w/ ground truth, 6-agent pipeline, verification registries, uncertainty triage, PRISM tracing, FastAPI, eval script | in progress |
| 2 | Frontend in BioHarmonize style: upload fax → live agent log → order review screen with flagged fields + pharmacist resolve actions | todo |
| 3 | Live run with real keys, user-photographed faxes, PRISM dashboard screenshots, demo script, README | todo |

## Repo layout
```
PillSpark/
  LOG.md            append-only build log (read first after any compaction)
  PLAN.md           this file
  GATES.md          unlazy completion ledger for phase 1
  backend/
    .env.example    keys to fill
    app/            FastAPI + pipeline
      config.py     env + thresholds
      schemas.py    Field / Order models
      llm.py        Nicrron client (OpenAI SDK), mock mode
      prism.py      PRISM wrapper (no-op without keys)
      registries.py RxNav / NPPES / checksum / sig parser / LASA / dose ranges
      pipeline.py   six agents + event log
      main.py       API: /api/health /api/orders (POST upload) /api/orders/{id} /api/orders/{id}/status /api/orders/{id}/resolve /api/samples
    scripts/
      gen_fax.py    synthetic fax prescriptions + ground truth
      run_batch.py  run pipeline over data/synthetic, write outputs
      eval.py       accuracy of verified fields + flag recall on ambiguous fields
      check_*.py    gate oracles
  data/
    synthetic/      generated faxes (*.png) + ground truth (*.json)
    real_samples/   HF clinic prescription pages (no labels)
    user_photos/    user's phone photos of printed faxes
  output/           order JSON per run
```

## Uncertainty contract (the demo story)
Every field carries `value`, `confidence`, `status`, `reasons`, `candidates`, `evidence`.
- **verified**: all passes agree, registry confirms, no safety rule tripped. Pharmacist sees a green check.
- **needs_review**: value shown with the specific doubt ("2 of 3 passes read 10 mg, 1 read 40 mg"; "RxNorm fuzzy match 0.72"; "look-alike pair hydroxyzine/hydralazine").
- **unreadable / missing**: value withheld (null). Candidates listed. Pharmacist must choose or call the prescriber.
The order is `blocked` until every flagged field is resolved via `/api/orders/{id}/resolve`.
