# PillSpark — Build Log (append-only)

Purpose: durable memory across sessions/compactions. Append entries; never rewrite history.
Format: `## [YYYY-MM-DD HH:MM] <topic>` then bullets. Decisions get a `DECISION:` prefix.

## [2026-10-10 11:05] Session 1 — kickoff
- Hackathon track: faxed prescription images → structured, verified orders (patient, drug, dose, directions, prescriber); uncertain fields flagged for a pharmacist, never guessed.
- Required sponsors: **Nicrron Ninoo** (LLM gateway) and **Block Convey** (PRISM reliability/observability).
- Reference frontend to imitate: `/Users/rodela/Desktop/Desktop/GitProjects/YC/frontend` (BioHarmonize). Static HTML + React UMD + Babel, DM Sans / DM Mono / Playfair, light theme (#FAFAF8 bg, accent teal #0D9488). Pipeline screen = left agent stepper + center live log + right metrics; polls FastAPI `/api/pipeline/run` + `/api/pipeline/status/{id}` and falls back to a scripted demo timeline if API is offline.
- Phase order agreed with user: (1) backend engine running, (2) frontend, (3) polish/demo.

## [2026-10-10 11:12] Research results
- **Nicrron** (https://nicrron.ai, marketing site https://nicrronninoo.ai): OpenAI-compatible gateway. Base URL `https://api.nicrron.ai/v1`, env `NICRRON_API_KEY` (format `sk-af-...`), model ids `provider/model` e.g. `anthropic/claude-sonnet-5`, `openai/gpt-5.4-mini`, routing slugs `nicrron/auto|fastest|cheapest|reasoning|coding`. `GET /v1/models` is public (82 models). Vision-capable per catalog descriptions: Anthropic + OpenAI chat models (standard vision), `mistral/*` ("with vision"), `moonshot/kimi-k3`, `xai/grok-4.6/4.5/4.20`. $10 starter credit on signup.
- **Block Convey PRISM** (https://blockconvey.com/docs): Python SDK `pip install "prismtrace-sdk>=0.4.3"` (installed 0.5.1). Env: `PRISMTRACE_HOST=https://prism.blockconvey.com`, `PRISMTRACE_PROJECT_ID` (UUID), `PRISMTRACE_API_KEY` (`pt-sk-...`). REST: `POST /api/traces` with header `X-PRISMtrace-Key`; required body: project_id, model, input_messages, output_message, latency_ms; optional session_id, agent_id, agent_name, metadata, token counts. Zero-code proxy: `https://prism.blockconvey.com/proxy/openai/v1` with same header. Automatic scoring per trace incl. "flagged for review". Free tier 100 credits/mo. Handshake: `POST /api/setup-doctor/handshake`.
- **Free verification registries (no key):** RxNav `https://rxnav.nlm.nih.gov/REST/approximateTerm.json?term=...` (fuzzy drug match, tested: "Amoxicilin 500" → amoxicillin 500 MG rxcui 317616), `spellingsuggestions.json?name=...` (tested: metformn → metformin). NPPES NPI registry `https://npiregistry.cms.hhs.gov/api/?version=2.1&first_name=&last_name=&state=&limit=` (tested OK).
- **Datasets:** No public full-page *faxed* prescription dataset with ground truth exists. Found: `tavishm/100-handwritten-medical-records` on HF (100 real Indian clinic prescription pages, printed+handwritten drug orders, no labels) — downloaded 6 to `data/real_samples/`. Kaggle/Mendeley "Doctor's Handwritten Prescription BD" and RxHandBD are cropped single-word images (not useful for full-order extraction). IEEE DataPort set requires login.
- DECISION: Generate our own synthetic US-style fax prescriptions with Pillow (Noteworthy/MarkerFelt fonts for handwriting, Courier for typewritten) + fax degradation (grayscale, blur, noise, skew, JPEG, 200dpi). Each has a ground-truth JSON → lets us measure accuracy AND calibration of the uncertainty flags. User will also print/photograph some for realism. HF pages are the "real-world" stress set.
- Environment: macOS, system Python 3.9.6, Node 25, poppler (pdftoppm) present, no tesseract. Venv at `backend/.venv` with fastapi, uvicorn, openai, pillow, httpx, numpy, pydantic, python-multipart, prismtrace-sdk. No API keys in env yet (~/.zshrc has none). User must supply `NICRRON_API_KEY`, `PRISMTRACE_API_KEY`, `PRISMTRACE_PROJECT_ID` in `backend/.env`.

## [2026-10-10 11:22] Hackathon participant guide (Google Doc from user)
- "NicrronNinoo Columbia Hackathon" — promo code **COLUMBIA26**, $250 + $10 signup = **$260 credit**, redeem by Nov 30 2026 at https://nicrron.ai/redeem?code=COLUMBIA26 (or app.ninoo.ai). Three paths: Ninoo Builder (no-code), **Nicrron API (we use this)**, Ninoo Code (CLI agent).
- ACTION for user: redeem code → create API key (`sk-af-...`) → put in `backend/.env` as `NICRRON_API_KEY`. Also sign up at https://prism.blockconvey.com/signup → Settings → Project tab → copy Project ID + create key (`pt-sk-...`) → `PRISMTRACE_PROJECT_ID`, `PRISMTRACE_API_KEY`.

## [2026-10-10 11:25] Architecture decisions (Phase 1 backend)
- DECISION: Six-agent pipeline mirroring BioHarmonize's stepper UX: Intake → Extraction (Nicrron vision, K independent passes) → Consensus (per-field vote) → Verification (RxNav drug/strength, NPPES prescriber, DEA/NPI checksum, sig parser, LASA look-alike list, dose range) → Triage (final confidence, flag/never-guess) → Order (structured JSON + PRISM trajectory).
- DECISION: Per-field confidence = blend of model self-report, cross-pass agreement, registry match; thresholds ≥0.90 verified, 0.70–0.89 needs_review, <0.70 unreadable (value withheld, candidates shown). Hard caps: any pass says illegible → ≤0.69; LASA risk w/o unanimous agreement → ≤0.69; dose outside range → needs_review regardless.
- DECISION: PRISM integration = `trace_llm` per vision call (image replaced by placeholder text in the logged prompt; field confidences in metadata) + `submit_trajectory` per order with one step per agent and final_status reflecting review outcome. No-op when keys absent.
- DECISION: `LLM_MODE=mock` (auto when no key) perturbs ground truth so the whole pipeline + gates run offline; `live` uses Nicrron. Default live model `anthropic/claude-sonnet-5` with `openai/gpt-5.4-mini` as second opinion (configurable).

## [2026-10-10 11:50] Backend engine built + first live run
- Files written: `backend/app/{config,schemas,registries,prism,llm,pipeline,main}.py`, `backend/scripts/{gen_fax,run_batch,eval,check_dataset,check_registries,check_api,check_live,check_prism}.py`, `GATES.md`, `PLAN.md`.
- `.env` at repo root: user wrote the key as `API_PillSpark = sk-af-…` → config accepts aliases (NICRRON_API_KEY, API_PillSpark). Live mode resolves. PRISM keys still absent → tracing is a no-op until `PRISMTRACE_PROJECT_ID` + `PRISMTRACE_API_KEY` are added (site: https://prism.blockconvey.com).
- Synthetic set: 24 faxes in `data/synthetic/` (typed pad / handwritten / EHR printout × clean / light / heavy), each with ground-truth JSON incl. `ambiguous` + `expected_flags`. NPIs are Luhn-valid but fake → NPPES correctly reports "not found" → prescriber flagged on every synthetic order (expected; real faxes with real NPIs will verify).
- Mock eval (24 orders): verified_precision 1.00 (205 verified fields, 0 guesses), flag_recall 1.00 (20/20 ambiguous fields flagged), value_accuracy 0.992.
- Live smoke test on rx_004_hand_light: `openai/gpt-5.4-mini` read all 12 fields correctly (conf 0.98–0.99, refills correctly null). `anthropic/claude-sonnet-5` via Nicrron returned 502 "`temperature` is deprecated for this model" → FIX: omit temperature for `anthropic/*` models.
- FIXES after reason tally: unit-aware RxNorm strength check (75 mcg == 0.075 MG); LASA pairs advisory-only when unanimous + RxNorm-confirmed; NPI field now flagged alongside prescriber when NPPES has no record.
- Run commands: `backend/.venv/bin/uvicorn app.main:app --app-dir backend --port 8000` · `LLM_MODE=mock backend/.venv/bin/python backend/scripts/run_batch.py` · gates: `node ~/.claude/skills/unlazy/scripts/gate-check.mjs --approve GATES.md --timeout 900`.

## [2026-10-10 12:15] First full gate run + live findings
- Gate run 1: 7/9 met. G2 failed on sig duration regex (`d` matched before `days`) → fixed, now 8/9. G7 (PRISM) unmet: keys not configured.
- Live synthetic (3 faxes incl. heavy degradation): 10/12 fields verified on each, all correct vs ground truth; only prescriber name + NPI flagged (fictitious NPI not in NPPES — by design).
- Live real clinic pages (6 HF images): pipeline never errored, every order `blocked`; models found 0–3 fields because those sheets are multi-drug Indian clinic forms without patient/prescriber blocks. Exposed 3 weaknesses, all fixed:
  1. Models sometimes emit malformed JSON (unescaped quotes) → passes dropped. FIX: `json_repair` fallback + `response_format=json_object` for openai/* models.
  2. A perfectly read NPI that isn't in NPPES was withheld as "unreadable". FIX: triage now separates *reading* confidence (withhold value only when we can't read the page) from *registry/safety* confidence (show value as needs_review with the doubt).
  3. A single surviving pass could auto-verify. FIX: n<2 passes caps every field below verified; consensus tie-break prefers legible > illegible > absent.
- GitHub: user's repo https://github.com/AUW160150/PillSpark (was empty). Local `git init -b main`, remote `origin` set, user.name AUW160150. `.env`, `.venv`, `output/`, `data/.cache` are ignored.
- TODO phase 1 wrap: reverify gates → commit + push → user adds PRISM keys → G7.
- TODO phase 2 (frontend, BioHarmonize style): landing → upload/choose fax → pipeline screen (6-agent stepper + live log fed by `/api/orders/{id}/status?since=`) → review screen (fields table with status pills, candidates, pharmacist resolve via `/api/orders/{id}/resolve`) → PRISM panel.
- TODO phase 3: multi-line-item orders (real clinic sheets list several drugs), user's phone photos in `data/user_photos/`, PRISM dashboard screenshots, demo script.
