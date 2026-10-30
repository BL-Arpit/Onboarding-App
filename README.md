# Employee onboarding chat (bottom-up build)

One small chat window. Upload a sheet (name, email, phone) → send **any image** for each employee → the bot says yes and fills Aadhaar, PAN and bank details with **placeholder values** → verify → publish to the master Excel sheet. Document reading (OCR) and classification are removed for now; everything else is real.

```
backend/   FastAPI. No OCR, no LLM, no external calls.
frontend/  React + Vite chat window
```

## Run (local)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

cd frontend                       # second terminal
cp .env.example .env
npm install && npm run dev        # http://localhost:5173
```

There is no sample data. Make any `.xlsx`/`.xls`/`.csv` with three columns (name, email, phone) and use any picture as the "document".

## How it behaves

1. **Sheet**: three columns, header optional. Bad rows and duplicates are skipped and listed.
2. **Four images per employee**, in this order: PAN card, Aadhaar card, cancelled cheque, any other document (any picture or PDF works for now). Each one is acknowledged ("Yes ✓ PAN card filled: …") and fills only that document's details with placeholders (format-valid, unique per employee, marked as placeholders). After the 4th the employee is saved to `data/master.json` as `EMP-0001…` and the next one starts. Several images in one message are used one step each. Typed real details are kept; an image only fills what is still empty.
3. **After the last employee** the batch is verified automatically. `confirm` (or "looks good", "publish it") writes the passing employees to `data/master_employees.xlsx` and `.xls`; both download from the chat. The sheet has a `Data` column (`placeholder` / `entered`).
4. **Duplicates**: blocked on email, phone, PAN, Aadhaar or bank account, at sheet upload, on typed details, on edits and on save.

## The bot understands plain sentences

No LLM: rules plus fuzzy matching (`app/nlu.py`), so it is instant, free and predictable.

| You say | It does |
|---|---|
| `how many are left?` / `who is next?` | progress sentence and table |
| `show Asha` / `tell me about #2` / `show EMP-0001` | profile card (name typos tolerated; asks if two people match) |
| `change Asha's phone to 9845012345` / `her email is a@b.com` / `fix 2 pan ABCDE1234F` | edits with validation; "her/him" = last person mentioned |
| `PAN ABCDE1234F, ifsc SBIN0001234, account 123456789012, dob 15/08/1990` | fills those fields from free text |
| `what's wrong with the last one?` / `why did it fail` | issues for one person or everyone |
| `skip`, `verify` (`verfiy` works), `confirm`, `download the excel`, `start over`, `help` | the obvious things |
| `what is a placeholder?` | 

## Standard employee JSON

`backend/schema/employee_master.template.json`, also `GET /api/schema`. `GET /api/master` returns the master list. Statuses: PENDING → COMPLETE → VERIFIED. `documents.<type>.source` says where the values came from.

## Plugging OCR back in later

`backend/app/reader.py` defines `DocumentReader.read(paths, emp)`. The placeholder reader is the only implementation. A real reader returns the same dict shape and gets passed to `Chat(...)`; nothing else changes.

## Limits

- Placeholders are fake by design. Do not use the master sheet as real data.
- Full Aadhaar numbers are not stored (masked value and keyed hash only). `STORE_FULL_AADHAAR=true` changes that.
- No login; files are unencrypted in `backend/data/`. One backend process. Add auth and a database before real use.
- Frontend deploys on Vercel as is (`VITE_API_URL`); the backend goes on any container host (`CORS_ORIGINS` = the Vercel URL).

## Tests

`cd backend && pytest -q` (63 tests: validators, sheets, store, language understanding, full end-to-end flow).
