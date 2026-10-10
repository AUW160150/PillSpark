# Gates: PillSpark phase 1 — backend engine

OWNS: backend/**, data/synthetic/**, output/**, LOG.md, PLAN.md, GATES.md

Scope: a runnable backend that turns a faxed prescription image into a structured order with per-field verification status, flags uncertain fields for a pharmacist instead of guessing, uses Nicrron for vision extraction and Block Convey PRISM for tracing, and exposes it over an API the phase-2 frontend can poll.

- [x] G0: this ledger states outcomes that can fail
  CHECK: node /Users/rodela/.claude/skills/unlazy/scripts/gate-lint.mjs GATES.md
  EXPECT: LINT OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=6a6e2175e849bc27f8c3d0d669512c06ccb7cecd9cdd35382d0dc4a91df50b50; exit=0; EXPECT=matched; output-sha256=48630b7361dd44ee870917b12c3d19b9d7bdea738aaca16bb04d4cab83b772d2; output-bytes=8; shell=/bin/sh; cwd=/Users/rodela/Desktop/Desktop/GitProjects/PillSpark; path=850bd16ad3bb/21 entries

- [x] G1: synthetic fax set exists with ground truth for every image (≥24 images, 3 styles × 3 degradation levels, ambiguity labels)
  CHECK: backend/.venv/bin/python backend/scripts/check_dataset.py
  EXPECT: DATASET OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=3a34c93232c81ab0af704d8f1a1c2e86dd4e146688e179a54ce050c533273cef; exit=0; EXPECT=matched; output-sha256=55d66b0af293f750a7cd6f76385f22e3edb39d7d2946c6a14a6d395f4b9214a3; output-bytes=149; shell=/bin/sh; cwd=/Users/rodela/Desktop/Desktop/GitProjects/PillSpark; path=850bd16ad3bb/21 entries

- [x] G2: registry verifiers work against live RxNav and NPPES, and reject a known-bad input (negative control)
  CHECK: backend/.venv/bin/python backend/scripts/check_registries.py
  EXPECT: REGISTRIES OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=1649137fbad413ef37c9efc4fb91b63d970b5d36265bb7b235fbab28f167fa2e; exit=0; EXPECT=matched; output-sha256=2b5d4cda82428514165c607bfefb0e77d4f3900ae1a7721e01c02f69f8bf09d3; output-bytes=110; shell=/bin/sh; cwd=/Users/rodela/Desktop/Desktop/GitProjects/PillSpark; path=850bd16ad3bb/21 entries

- [x] G3: pipeline completes on all synthetic faxes in mock mode and every order has 12 fields with valid statuses
  CHECK: env LLM_MODE=mock backend/.venv/bin/python backend/scripts/run_batch.py --quiet
  EXPECT: BATCH OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=2d6264e657233ad5cf8ef7e4c33e82d8509be5e4d250fa83ed94a83ab7e3e998; exit=0; EXPECT=matched; output-sha256=3e54a4b49a431b30a1f37bdb16d96d0523f2ba2f7005328d9f2696688e383c4d; output-bytes=3061; shell=/bin/sh; cwd=/Users/rodela/Desktop/Desktop/GitProjects/PillSpark; path=850bd16ad3bb/21 entries

- [x] G4: never-guess contract holds on ground truth (mock) — verified_precision ≥ 0.97 and every deliberately ambiguous field is flagged (flag_recall ≥ 0.90)
  CHECK: env LLM_MODE=mock backend/.venv/bin/python backend/scripts/eval.py
  EXPECT: EVAL OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=ed625cc892a83603a72239649508f421848b80c661c4104ff333692ad1bb3d1e; exit=0; EXPECT=matched; output-sha256=026f723692006bbd93e6524e060e1e17d119e16473b1df116df7f26a386091a3; output-bytes=1557; shell=/bin/sh; cwd=/Users/rodela/Desktop/Desktop/GitProjects/PillSpark; path=850bd16ad3bb/21 entries

- [x] G5: API boots, accepts a sample, streams agent events, returns an order whose unreadable fields carry no value, and a pharmacist can resolve a flagged field (mock)
  CHECK: env LLM_MODE=mock backend/.venv/bin/python backend/scripts/check_api.py
  EXPECT: API CHECK PASSED
  EVIDENCE: automatic-evidence=v1; definition-sha256=70f1472e3109de3ea0265bce3e76471cd3c0bc26ef8bae9fccb3da4bf17b9819; exit=0; EXPECT=matched; output-sha256=107b2f9b0d842b49c5f1395960eb88ee91fc649780e02f1634fa090e278d6287; output-bytes=398; shell=/bin/sh; cwd=/Users/rodela/Desktop/Desktop/GitProjects/PillSpark; path=850bd16ad3bb/21 entries

- [x] G6: live Nicrron extraction — pipeline runs on 3 synthetic faxes through api.nicrron.ai with two vision models, orders are produced in live mode, and no verified field contradicts ground truth
  CHECK: backend/.venv/bin/python backend/scripts/check_live.py --limit 3
  EXPECT: LIVE CHECK PASSED
  EVIDENCE: automatic-evidence=v1; definition-sha256=593141894e90b46f946d38cfc52cac20a7d6feb98070a082d05d3eb480a73dbf; exit=0; EXPECT=matched; output-sha256=b57caff3b074c19516acf105cff85bc521394c3ff9f30449bfa878d5c54e4c59; output-bytes=561; shell=/bin/sh; cwd=/Users/rodela/Desktop/Desktop/GitProjects/PillSpark; path=850bd16ad3bb/21 entries

- [ ] G7: Block Convey PRISM receives traces — handshake succeeds with the configured project and a live order reports ≥1 trace id and a trajectory
  CHECK: backend/.venv/bin/python backend/scripts/check_prism.py
  EXPECT: PRISM CHECK PASSED
  EVIDENCE: pending

- [x] G8: handwriting stress set — the 6 Hugging Face clinic case-note pages (NOT faxes; see data/real_samples/README.md) run through the live pipeline without error and every order is blocked or ready (never silently guessed into ready with unreadable fields)
  CHECK: backend/.venv/bin/python backend/scripts/check_live.py --dir data/real_samples --limit 6 --no-ground-truth
  EXPECT: LIVE CHECK PASSED
  EVIDENCE: automatic-evidence=v1; definition-sha256=cd5714d308ee3ab15c81304131750a493d38782798820e1428c8bf68a3fc7438; exit=0; EXPECT=matched; output-sha256=7f34e3e81cfff9016ed2ee0af95818bf6cf2b6b409b69f137be0e5b1d315615b; output-bytes=1522; shell=/bin/sh; cwd=/Users/rodela/Desktop/Desktop/GitProjects/PillSpark; path=850bd16ad3bb/21 entries
