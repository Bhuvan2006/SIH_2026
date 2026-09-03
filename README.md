# Arogya — working prototype

This is a running implementation of the Phase‑1 MVP described in `Arogya_Build_Plan.md`: multilingual prescription OCR with mandatory patient confirmation, medication reminders, patient history, a grounded (RAG) medical chatbot, price comparison, and a pharmacy locator.

**What's real vs. mocked**, in one line: OCR (Tesseract), the chatbot's retrieval/grounding, reminders/scheduling, and all business logic are genuinely working code you can exercise end-to-end. This checkout also has a real LLM wired up (`LLM_PROVIDER=google`, Gemini, via a `GOOGLE_API_KEY` in `backend/.env`) so chatbot answers are composed by Gemini on top of the curated grounding facts, not just the deterministic template. Other paid third-party services (a cloud OCR vendor, Bhashini, Google Places, SMS) are abstracted behind swappable interfaces and default to free local/mock implementations, documented inline in each `app/services/*.py` file — the app still runs with zero API keys if you unset `LLM_PROVIDER`/`GOOGLE_API_KEY` — see "Swapping in real services" below.

## Quickstart

### Option A — Docker Compose (easiest)

```bash
docker compose up --build
```

Backend: http://localhost:8000 (interactive API docs at `/docs`)
Frontend: http://localhost:5173

### Option B — Run locally

**Backend:**
```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

**Frontend** (separate terminal):
```bash
cd frontend
npm install
npm run dev
```

#### Installing Tesseract (needed only for prescription OCR)

Tesseract is the OCR engine itself — a system package, not a pip install. Everything
except prescription scanning works without it; if it's missing, upload still succeeds
and falls back to manual medicine entry (with a clear message) rather than erroring.

- **Debian/Ubuntu:** `sudo apt-get install tesseract-ocr`
- **macOS:** `brew install tesseract`
- **Windows, with admin rights:** run PowerShell **as Administrator**, then
  `choco install tesseract -y`. Running this from a normal (non-elevated) shell
  fails with a misleading *"Unable to obtain lock file access"* error — that's
  really a permission denial on `C:\ProgramData\chocolatey\lib`, which grants
  `Users` read-only access. Elevation is the fix.
- **Windows, without admin rights:** install it into a user-owned conda env, then
  point the app at it via `TESSERACT_CMD` in `.env`:
  ```bash
  conda create -p "$HOME/.conda/envs/tesseract" -c conda-forge tesseract -y --solver=libmamba
  ```
  then set `TESSERACT_CMD=C:\Users\<you>\.conda\envs\tesseract\Library\bin\tesseract.exe`

If `tesseract` isn't on PATH after installing, set `TESSERACT_CMD` in `backend/.env`
to its full path (see the commented example in that file).

Open http://localhost:5173. There's no real SMS: request an OTP on the login screen and either use the code shown in the dev response, or type `000000` (always accepted in dev mode — see `OTP_DEV_MODE` in `backend/app/core/config.py`).

### Running tests

```bash
cd backend && source venv/bin/activate
pytest -v
```

11 tests cover the full flow: auth, OCR upload + extraction, confirm → reminders → history, chatbot grounding + emergency escalation + no-hallucination, price comparison, pharmacy locator, consent grant/withdraw.

## What you can actually do in the running app

1. **Log in** with any phone number (OTP is mocked).
2. **Upload a prescription photo.** Printed text is read with real Tesseract OCR, fuzzy-matched against a curated 24‑drug knowledge base, and parsed into drug/dosage/frequency/duration. You **must** review and confirm every field before anything is saved — there is no auto-confirm path, even for high-confidence OCR (see "Safety guardrails" below).
3. **Set reminder times** per medicine; the dashboard shows today's schedule, and a background job (APScheduler, ticking every minute) fires a (mock) notification and creates an adherence log entry when a scheduled time arrives. Mark doses taken/skipped/snoozed.
4. **View history** — a timeline of confirmed prescriptions.
5. **Ask the chatbot** things like "How should I store insulin?" or "What should I eat if I have diabetes?" — answers are composed only from the curated knowledge base, every claim is cited, and emergency-sounding messages ("severe chest pain") get redirected to seek real help instead of an answer.
6. **Compare prices** — search a medicine (e.g. "Paracetamol") and see branded vs. generic (including a Jan-Aushadhi-style entry) options sorted cheapest-first, with % savings.
7. **Find nearby pharmacies** — allow location access (or it falls back to a sample Bengaluru location) and see a sorted-by-distance list from a bundled sample directory.
8. **Switch language** (English / Hindi / Tamil in this prototype) from the top bar — UI strings, not drug names, are translated (see "Multilingual approach" below for why).

## Repository layout

```
backend/
  app/
    main.py                 FastAPI app, CORS, startup (seed DB, start scheduler)
    core/config.py           Central settings — every external integration's on/off switch
    core/security.py         OTP + JWT auth
    db/                      SQLAlchemy engine/session, seed script
    models/models.py         All data model entities (Patient, Prescription, Medication, ...)
    schemas/schemas.py       Pydantic request/response models
    services/
      ocr_service.py          Real Tesseract OCR + structured extraction
      chatbot_service.py      RAG-lite answer composition + safety guardrails
      translation_service.py  Mock dictionary translator; Bhashini swap-in point
      notification_service.py Mock notifier; FCM/Twilio/MSG91 swap-in point
      places_service.py       Mock nearby-pharmacy lookup; Google Places swap-in point
      diet_service.py         Loads curated diet guidance
    rag/knowledge_retriever.py  Retrieval logic + emergency-keyword detection
    scheduler/reminder_scheduler.py  Background reminder tick (APScheduler)
    api/routers/              One file per feature area (auth, patients, prescriptions, ...)
    data/                     Curated JSON: drug knowledge, prices, diet guidance, pharmacies
    tests/test_api.py         11 end-to-end pytest tests
frontend/
  src/
    api/client.ts             Axios client + TypeScript types matching the backend schemas
    context/AuthContext.tsx   Token/session state
    i18n/index.ts              en/hi/ta string bundles
    pages/                    One file per screen (Login, Dashboard, UploadPrescription, ...)
    components/               Layout (nav + language switcher), ProtectedRoute
Arogya_Build_Plan.md          The original full plan this implements Phase 1 of
docker-compose.yml
smoke_test.py                 Playwright script that exercises the whole app in a real browser
screenshots/                  Output of the last smoke_test.py run
```

## Safety guardrails actually implemented (not just documented)

These map directly to the non-negotiables in the build plan (§2) and were verified by the test suite and a live browser run, not just written as comments:

- **No auto-confirm from OCR.** `prescriptions.py`'s upload endpoint always returns `confirmation_status: needs_review`; medications only become real, reminder-driving records after the patient calls `/confirm` with (edited, if needed) data. Verified by `test_prescription_upload_and_confirm_flow`.
- **Low-confidence / likely-handwritten flagging.** `OCR_LOW_CONFIDENCE_THRESHOLD` in config, checked in the upload handler; the frontend shows a visible warning banner and asks for extra care before confirming.
- **Chatbot answers only from retrieved, curated, cited facts** — never free-form generation. `knowledge_retriever.py` + `chatbot_service.py`'s `_compose_from_retrieval` build the answer purely out of `DrugKnowledge`/diet-guidance records; `test_chatbot_unknown_topic_does_not_hallucinate` confirms an out-of-scope question returns zero citations rather than a fabricated answer.
- **Emergency-language escalation.** Regex patterns in `knowledge_retriever.EMERGENCY_PATTERNS` (chest pain, suicidal language, overdose, anaphylaxis, etc.) short-circuit straight to "seek help now" — verified by `test_chatbot_emergency_escalation` and the live smoke test.
- **Price comparison is informational only**, never a purchase flow, with a standing disclaimer — see `prices.py`'s `PRICE_DISCLAIMER` and the build plan §0.2 on why (India's e-pharmacy regulatory gray zone).
- **Pharmacy locator never claims live stock** — `places_service.py`'s docstring and the frontend copy are explicit that this is a nearby-pharmacy directory, not an inventory check.
- **Consent is a first-class, revocable record**, not just a checkbox — `ConsentRecord` model + `/patients/me/consent` endpoints (grant, list, withdraw with timestamp), aligned with DPDP Rules 2025 expectations from the build plan §7.

## Swapping in real services

Every external integration is one file plus one config value away from being real. None of this requires touching a router or a page component.

| Capability | Config flag | Mock (default) | To go live |
|---|---|---|---|
| OCR | `OCR_PROVIDER` | `auto` — local Tesseract first, **Gemini vision fallback** when Tesseract is missing, errors, or reads no known medicine | Set `tesseract` (local only) or `gemini` (vision only). For a cloud OCR vendor, implement `OCRProvider` in `ocr_service.py` for Document AI / Textract |
| Translation | `TRANSLATION_PROVIDER` | `mock` (small phrase dictionary) | Implement the Bhashini ULCA API call in `BhashiniTranslationService`, set `BHASHINI_API_KEY` |
| Chatbot LLM | `LLM_PROVIDER` | `retrieval` (deterministic, grounded, no API key) | Set `LLM_PROVIDER=google` + `GOOGLE_API_KEY` (Gemini, wired up and live by default in this checkout) or `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` — retrieval always runs first as grounding context, the model composes the answer from it (plus general medical knowledge for questions outside the curated 24-drug set) |
| Pharmacy locator | `PLACES_PROVIDER` | `mock` (bundled sample directory) | Implement the Places Nearby Search call in `GooglePlacesProvider`, set `GOOGLE_PLACES_API_KEY` |
| Notifications | `NOTIFICATION_PROVIDER` | `mock` (logs to console/outbox) | Set `NOTIFICATION_PROVIDER=msg91` + `MSG91_AUTH_KEY`/`MSG91_FLOW_ID`/`MSG91_SENDER_ID` for real SMS reminders (MSG91's Flow API is wired up in `notification_service.py`; India's DLT rules require a pre-approved template, see comments there). FCM/Twilio remain swap-in points via `NotifierProvider`. |
| Drug/price data | — | 45 curated drugs (clinical) + 351k imported Indian products (names, composition, MRP) | Curated safety data still needs a licensed clinical source (see build plan §3, §6.8) — replace `app/data/*.json` + the seed script. The bulk catalogue is imported separately, see "Importing the Indian medicine catalogue" below |
| Database | `DATABASE_URL` | SQLite file | Point at a Postgres DSN — SQLAlchemy models are already portable |

All flags live in `backend/app/core/config.py`, settable via environment variables or a `.env` file.

## Importing the Indian medicine catalogue

The 45 curated drugs in `app/data/drug_knowledge.json` are the *clinical* dataset: contraindications, interactions, pregnancy warnings. They are deep but narrow.

The `medicine_products` table is the *commercial* dataset: ~351,000 real Indian branded medicines with their composition, pack size and printed MRP, imported from the MIT-licensed [Indian-Medicine-Dataset](https://github.com/junioralive/Indian-Medicine-Dataset). It is wide but shallow — no clinical fields at all.

```bash
curl -L -o indian_medicine_data.csv https://raw.githubusercontent.com/junioralive/Indian-Medicine-Dataset/main/DATA/indian_medicine_data.csv
python scripts/migrate_schema.py
python scripts/import_indian_medicines.py indian_medicine_data.csv
```

The import is idempotent (it replaces its own rows and leaves curated and patient data alone) and skips the 7,905 discontinued products by default.

**What the two datasets do together.** Every imported product whose composition matches a curated drug is linked to it, so scanning any of ~44,000 brand names still runs the full five-check safety screening. The other ~82% are searchable and priceable but have **no** safety verdict — the API returns `has_safety_data: false` for these and the UI says "not checked" rather than showing a reassuring "no flags found" badge. That distinction is load-bearing: an empty flag list must never be read as an all-clear.

**Price comparison compares like with like.** Products are grouped by `formulation_key` — molecules, strengths *and* dosage form — and sorted by price per dose, not per pack. Comparing 650mg tablets against a 500mg syrup, or a strip of 10 against a strip of 15, produces savings percentages that look impressive and mean nothing.

### Second source: the 1mg scrape

The Indian-Medicine-Dataset records only **two** active ingredients per product, so every three-ingredient combination was indexed as a two-ingredient one — meaning price comparison could offer an "equivalent" that was missing a molecule. Zerodol PT is the example that matters: it is aceclofenac + paracetamol + **tramadol**, an opioid combination, and the first source knew only the first two.

The "India Medicines and Drug Info Dataset" (a 1mg scrape, 348,211 rows) fixes that, and adds prescription status:

```bash
python scripts/import_1mg_dataset.py "India Medicines and Drug Info Dataset.csv"
```

Run it **after** `import_indian_medicines.py` — it reuses that import's ingredient vocabulary to disambiguate the CSV, and upgrades those rows rather than duplicating them. Results: +105,289 new medicines (catalogue now 351,357), 17,919 compositions corrected to three or more ingredients, and prescription-vs-OTC status recorded for 250,688 products.

That CSV's own columns are unusable — `Type of Medicine` and `Composition` are empty on ~30% of rows and mis-split on the rest, with the first ingredient glued to the end of the manufacturer name ("…Alpic Biotech Ltd**Aspirin**"). Everything is instead parsed out of the single `Product Name` blob by [`parse_1mg_blob.py`](backend/scripts/parse_1mg_blob.py), which reads 99.8% of rows; the remainder are counted and skipped rather than guessed at. Its image URLs are ignored (three distinct URLs across 348,211 rows) and so is its `Price` column (rounded to whole rupees — the blob's MRP is exact).

`prescription_required` is deliberately **nullable**. NULL means unrecorded, not over-the-counter, and the UI only renders an Rx/OTC tag when the value is actually known.

### The CDSCO prohibited-drugs list

`app/data/banned_drugs.json` holds 17 hand-curated entries with clinical detail (why a drug is restricted, at what dose). Alongside it, `app/data/banned_drugs_cdsco.json` holds the official section 26A prohibition list — 420 of the source document's 444 rows, extracted from the CDSCO PDF:

```bash
python scripts/parse_cdsco_banned_pdf.py path/to/banned_drugs.pdf
```

That PDF has no text layer — every glyph is a vector path — so pages are rasterised and OCR'd. Rows are cut on the **table's own ruled lines**, which are readable as vector paths even though the text is not; reconstructing rows from OCR line breaks instead gave 524 entries when the heuristic split too eagerly and 188 when it merged too eagerly. Damaged ingredient names are repaired against the medicine catalogue's ~1,700-molecule vocabulary (183 repairs), because a rule that silently keeps "Nimesstce" instead of "Nimesulide" would never match anything.

**Most of the list is fixed-dose combinations**, which is why the full-composition import matters: a combination rule only fires when *every* one of its molecules is present, so "Nimesulide + Paracetamol" flags that combination while leaving plain paracetamol alone. Matching needs the composition, so `screen_prescription` now takes it alongside the name.

Two deliberate limits, both visible in the data file:

- **Class rules are not matched.** "Corticosteroids with any other drug for internal use" needs drug-class data we hold for the 45 curated drugs only; applying it on a name match would flag half the catalogue. Those 46 entries are stored for reference and skipped.
- **Footnote markers could not be attributed per row.** The document marks entries that are stayed by the Madras High Court, revoked with conditions, or quashed by the Delhi High Court and under Supreme Court appeal — but the markers are asterisks the scan does not reproduce reliably. So every CDSCO warning says the legal status of some entries is unsettled rather than asserting a live ban.

### Every medicine gets screened, not just the scanned ones

Screening used to be tied to the upload response, so it covered only what OCR read from the image. A medicine typed in by hand, corrected after a misread, or added from a pack scan reached confirmation with **no check at all** — and nothing on screen admitted it.

The review step now lives in `app/services/review_service.py` and takes a plain list of names, so the upload path and the new `POST /prescriptions/screen` endpoint run identical logic. The page re-screens (debounced, with a stale-response guard) whenever a row is added, edited or removed.

A typed name alone cannot match a banned fixed-dose combination — "Zerodol PT" is a brand, and the prohibition is on the three molecules inside it — so each name is first resolved against the catalogue to recover its composition, using the same matcher that reads a smudged prescription line.

When any medicine carries a **critical** flag, saving requires one explicit tick ("I have read the serious warnings above"). It does not block: the doctor may have prescribed it deliberately, and Arogya never overrides a prescription. It just cannot be scrolled past silently, since saving also schedules reminders. Changing the medicine list resets the acknowledgement — agreeing to the previous set of warnings says nothing about a new one.

### Menopause and aromatase inhibitors

Anastrozole, letrozole and exemestane suppress oestrogen to very low levels, and their side effects — hot flushes, joint pain, bone density loss — land on top of symptoms a menopausal patient already has. When one is scanned and the patient has a menopause-related entry among their conditions (including free-text "other" ones), Arogya raises a **warning, never a critical flag**, and the wording leads with *keep taking it*: these are usually breast-cancer therapy where stopping is far more dangerous than the side effects, so the action is supportive care and a conversation with the doctor, not avoidance.

## Doctor interface

A second role, reachable at `/doctor/login` (OTP `000000`, same dev flow as patients). Architecture follows the role-guard pattern: one auth context that knows which role holds the session, and `ProtectedRoute requireRole="doctor"` on the doctor subtree — a signed-in doctor opening a patient route is redirected to their own home rather than left on a page whose every request 401s.

Doctors can set clinic hours per weekday (`DoctorAvailability`), block dates (`DoctorTimeOff`), work their diary, schedule follow-ups, and write consultation notes the patient sees.

**Access to patient records is gated on an appointment.** `GET /doctor/patients/{id}` previously had no check at all: anyone who registered as a doctor — registration is an OTP on any phone number — could read every patient's name, phone, allergies, conditions and medicines. It now requires an appointment between the two, and returns 404 rather than 403, since confirming a record exists is itself a disclosure.

Seed three doctors with genuinely different hours:

```bash
python scripts/seed_doctors.py            # create / refresh
python scripts/seed_doctors.py --clear    # remove
```

## Appointments

Slots are generated from each doctor's own availability, minus blocked dates, minus what is booked. They used to be a hardcoded list of twelve times, identical for every doctor and every date — so a patient could book Sunday evening with a doctor who only sits weekday mornings.

Times are stored 24-hour (`"17:30"`); the API sends a `time_slot_label` for display, so formatting stays in the UI where the reader's locale is known.

Booking rules live in `app/services/appointment_service.py`, shared by the patient and doctor routers so the two cannot drift. None of these existed before: the API accepted a booking on 2020-01-01, a `time_slot` of `"3am in the morning"`, and a `doctor_id` matching no doctor.

A partial unique index on `(doctor_id, date, time_slot)` where status is pending or confirmed settles the double-booking race the router's check-then-insert cannot. Cancelled appointments fall outside it, so the slot frees up again.

SQLite foreign keys are now enabled per connection (`PRAGMA foreign_keys=ON`). They are off by default, which is why the `ForeignKey` declarations on the models were documentation only.

## Demo data

Two seeders, both explicitly run and both reversible. Neither writes anything unless invoked.

```bash
python scripts/seed_pregnant_demo.py            # create / refresh
python scripts/seed_pregnant_demo.py --clear    # remove
python scripts/make_demo_prescription.py        # writes demo_prescriptions/*.png
```

`seed_pregnant_demo.py` creates **Priya Sharma** (`+919876500022`, OTP `000000`): 28, 26 weeks pregnant, gestational diabetes and hypothyroidism, B+, sulfa allergy, an appendectomy in 2019, two emergency contacts, 12 weeks of antenatal vitals and 30 days of dose history at ~85%.

Her current medicines are all **appropriate in pregnancy** — folic acid, iron, calcium, levothyroxine, metformin for GDM. That is deliberate: the record opens clean so the safety system has somewhere to fall from. The flags come from uploading `demo_prescriptions/pregnancy_unsafe.png` (doxycycline, diclofenac, fluconazole, ramipril — four critical pregnancy flags) or `banned_combination.png` (a CDSCO-prohibited fixed-dose combination).

**This is fabricated data and must be cleared before the database is used for anything real.**

## Multilingual approach (and its limit, honestly stated)

The frontend UI (buttons, labels, nav) is fully localized via `i18next` for English, Hindi, and Tamil as a demonstration of the launch-language pattern from the build plan §6.3 — pick your real launch set and extend the resource bundles in `frontend/src/i18n/index.ts`.

**Drug names and clinical facts are deliberately NOT translated** in this prototype (they're shown as extracted/canonical, e.g. "Insulin Glargine") — per the build plan's own guidance, mistranslating a drug identifier is a safety risk, so production should translate *explanatory text* freely while treating drug names as near-invariant, transliterated rather than translated. `translation_service.py`'s mock dictionary shows the intended pattern for a handful of phrases; a real deployment wires this through Bhashini for open-ended text.

## Known limitations of this prototype (be aware before treating it as more than a build)

- **Handwriting OCR is much better but still not "solved."** With `OCR_PROVIDER=auto`, uploads Tesseract can't read fall through to a Gemini vision model, which handles handwriting, rotation, blur, and noise far better (measured on a rotated/blurred sample: Tesseract 0.00 confidence and 0 medicines found, Gemini vision 0.98 and all 3 found). It can still misread a name or dose, so the mandatory patient-confirmation step (build plan §0.1) applies identically to vision output — nothing auto-confirms, and the review screen says explicitly when AI read the image.
- **Clinical drug knowledge and diet guidance are a 45-item curated SAMPLE dataset** (prices and brand names now come from a real 351k-product import — see above, but that import carries no clinical data), explicitly marked as such in the JSON files and in-app disclaimers. It is not clinically validated and must not be used for real patient care without a licensed data source and clinician review (build plan §3, §7).
- **The reminder scheduler is in-process** (APScheduler polling every minute) — fine for a prototype/single instance, not durable across restarts or multiple app instances. Build plan §3 already flags Celery/a cloud scheduler as the production path.
- **No real push/email** is sent. Real SMS reminders are supported via MSG91 (`NOTIFICATION_PROVIDER=msg91`, see the table above) but stay in mock/log-only mode until MSG91 credentials are configured. No real payment or purchase flow exists anywhere (intentionally — see the e-pharmacy regulatory discussion in the build plan §0.2 and §7).
- **Legal/compliance review has not happened** — this is a functioning technical prototype, not a compliance-reviewed product. Build plan §7's checklist (DPO, breach runbook, ToS, data localization, e-pharmacy legal opinion) is still outstanding before any real user data should touch this.

## Next steps

See `Arogya_Build_Plan.md` §8 (Phased roadmap) for what comes after this Phase‑1 prototype — expanding the drug/price dataset, native mobile apps for reliable push, caregiver accounts, more languages, pharmacy chain partnerships, and eventually ABDM/ABHA integration.
