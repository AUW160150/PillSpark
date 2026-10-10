# real_samples — what these are (and are not)

Six pages from the Hugging Face set `tavishm/100-handwritten-medical-records` (no license stated; used for local testing only).

They are **scanned handwritten clinic/hospital case notes from India** (history, examination, investigations, inpatient
drug orders in `Drug · dose · route · frequency` shorthand like `Cefepime 1g I.V BD`). They are **not faxed pharmacy
prescriptions**: no fax header, no patient/prescriber block, several drugs per page, and two pages (000, 004) carry no
prescription at all.

We keep them only as a **handwriting stress test** — the pipeline must end every one of them `blocked` with values
withheld, never a guessed `ready` order. Realistic fax data = `data/synthetic/` (ground truth) and `data/user_photos/`
(printed synthetic faxes photographed/faxed by us).
