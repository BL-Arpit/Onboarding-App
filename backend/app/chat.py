"""The conversation. Sheet in -> one employee at a time -> any image fills the record (placeholders for now) ->
duplicate check -> verify -> confirm publishes to the master sheet. Understands plain sentences (see nlu.py)."""
import hashlib
import hmac
import re
import secrets
import uuid
from pathlib import Path

from rapidfuzz import fuzz

from . import nlu, sheet, validate as V
from .config import Settings
from .reader import DocumentReader, PlaceholderReader
from .schema import new_employee, now_iso, set_path
from .sessions import Sessions
from .store import Duplicate, MasterStore

SHEET_EXT = (".xlsx", ".xlsm", ".xls", ".csv")
DOC_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic", ".heif", ".pdf")
ALIASES = {
    "name": "full_name", "email": "email", "phone": "phone", "dob": "aadhaar.dob", "gender": "aadhaar.gender", "father_name": "pan.father_name",
    "address": "address.full", "pincode": "address.pincode", "aadhaar": "aadhaar.number", "aadhaar_name": "aadhaar.name", "pan": "pan.number",
    "pan_name": "pan.name", "account": "bank.account_number", "ifsc": "bank.ifsc", "holder": "bank.account_holder", "bank": "bank.bank_name",
    "branch": "bank.branch",
}
GROUP = {"aadhaar": "aadhaar", "address": "aadhaar", "pan": "pan", "bank": "bank", "other": "other"}
STEPS = ("pan", "aadhaar", "bank", "other")            # the four images asked for, in this order
STEP_LABEL = {"pan": "PAN card", "aadhaar": "Aadhaar card", "bank": "cancelled cheque", "other": "any other document"}
STEP_GROUPS = {"pan": ("pan",), "aadhaar": ("aadhaar", "aadhaar_back"), "bank": ("bank",), "other": ("other",)}
HELP = ("**What I can do**\n"
        "• Upload a sheet (.xlsx, .xls or .csv) with name, email and phone.\n"
        "• For each person I ask for 4 images, one at a time: **PAN, Aadhaar, cancelled cheque, any other document**. Any picture works for now; I fill that document's details with placeholders.\n"
        "• Or type real details: `PAN ABCDE1234F`, `IFSC SBIN0001234`, `account 123456789012`, `dob 15/08/1990`.\n"
        "• Ask me things: `how many are left?`, `show Asha`, `what's wrong with the last one?`, `who is next?`\n"
        "• Change anything in plain words: `change Asha's phone to 9845012345`, `her email is a@b.com`, `fix 2 pan ABCDE1234F`.\n"
        "• `skip`, `verify`, `confirm` (publish the verified ones), `download`, `reset`.")
EXPLAIN_PLACEHOLDER = ("We're building bottom-up, so document reading is switched off. I don't look at the images: each one fills that document's fields "
                       "with placeholder values that have valid formats and are unique per employee, so the whole flow can be tested. "
                       "They are marked as placeholders in the record and in the sheet's Data column. Overwrite any of them, e.g. `change Asha's pan to ABCDE1234F`.")


def R(text: str, card: dict | None = None) -> dict:
    return {"role": "assistant", "text": text, "card": card}


class Chat:
    def __init__(self, store: MasterStore, sessions: Sessions, settings: Settings, reader: DocumentReader | None = None):
        self.store, self.sessions, self.cfg = store, sessions, settings
        self.reader: DocumentReader = reader or PlaceholderReader()
        self.uploads = Path(store.dir) / "uploads"
        self.uploads.mkdir(parents=True, exist_ok=True)
        key = Path(store.dir) / ".hash_key"
        if not key.exists():
            key.write_text(secrets.token_hex(32))
            key.chmod(0o600)
        self._key = key.read_text().strip().encode()

    # ================================================================ public
    def history(self, sid: str) -> dict:
        sess = self.sessions.load(sid)
        return {"messages": sess["messages"], "progress": self._progress(sess["state"]), "chips": self._chips(sess["state"])}

    def handle(self, sid: str, text: str, files: list[tuple[str, bytes]]) -> dict:
        with self.sessions.lock(sid):
            sess = self.sessions.load(sid)
            st = sess["state"]
            sess["messages"].append({"role": "user", "text": text, "files": [n for n, _ in files]})
            try:
                replies = self._route(st, text.strip(), files)
            except Exception as e:  # noqa: BLE001  keep the chat alive whatever happens
                replies = [R(f"Something went wrong on my side ({type(e).__name__}). Your saved data is safe; please try that again.")]
            sess["messages"].extend(replies)
            self.sessions.save(sid, sess)
            return {"messages": replies, "progress": self._progress(st), "chips": self._chips(st)}

    # ================================================================ routing
    def _route(self, st: dict, text: str, files: list[tuple[str, bytes]]) -> list[dict]:
        sheets = [f for f in files if f[0].lower().endswith(SHEET_EXT)]
        docs = [f for f in files if f[0].lower().endswith(DOC_EXT)]
        other = [f[0] for f in files if f not in sheets and f not in docs]
        out: list[dict] = []
        if other:
            out.append(R("I can't use: " + ", ".join(other) + ". Send a sheet (.xlsx/.xls/.csv) or document images (JPG, PNG, PDF…)."))
        if sheets:
            out += self._ingest_sheet(st, *sheets[0])
            if len(sheets) > 1:
                out.append(R("One sheet at a time. I used the first one."))
        elif docs:
            out += self._documents(st, docs)
        elif not other:
            out += self._talk(st, text)
        return out

    def _talk(self, st: dict, text: str) -> list[dict]:
        it = nlu.parse(text)
        n = it.name
        if n == "empty":
            return [R("Attach a sheet or an image, or just tell me what you need. " + self._where(st))]
        if n == "edit":
            return self._edit(st, it)
        if n == "details":
            return self._details(st, text)
        if n == "status":
            return self._status(st, it.ref)
        if n == "show":
            return self._show(st, it.ref, text)
        if n == "issues":
            return self._issues(st, it.ref)
        if n == "verify":
            return self._verify(st)
        if n == "confirm":
            return self._confirm(st)
        if n == "skip":
            return self._skip(st)
        if n == "download":
            return self._download()
        if n == "reset":
            st.update(phase="idle", queue=[], idx=0, focus=None, awaiting=None, published=False)
            return [R("Cleared this batch. Employees already saved in the master list stay there. Upload a new sheet whenever you're ready.")]
        if n == "help":
            return [R(HELP)]
        if n == "placeholder":
            return [R(EXPLAIN_PLACEHOLDER)]
        if n == "greet":
            return [R("Hi! " + self._where(st))]
        if n == "thanks":
            return [R("Anytime. " + self._where(st))]
        if n == "affirm":
            if st.get("awaiting") == "confirm":
                return self._confirm(st)
            return [R("👍 " + self._where(st))]
        if n == "deny":
            if st.get("awaiting") == "confirm":
                st["awaiting"] = None
                return [R("Okay, I won't publish yet. Say `confirm` when you're ready.")]
            return [R("Okay. " + self._where(st))]
        return self._unknown(st, it, text)

    def _where(self, st: dict) -> str:
        ph, q = st.get("phase", "idle"), st.get("queue", [])
        if ph == "collecting" and q:
            e = q[st["idx"]]["emp"]
            return f"I'm on **{e['full_name']}** ({st['idx'] + 1} of {len(q)}). {self._ask(e)} Or say `skip`."
        if ph == "review":
            if st.get("awaiting") == "confirm":
                return "Everything is checked. Say `confirm` to publish the verified employees, or ask `what's wrong?`."
            return "The batch is processed. Say `what's wrong?` to see issues or `verify` to re-check."
        return "Upload an employee sheet (name, email, phone) to begin, or type `help`."

    def _unknown(self, st: dict, it: nlu.Intent, text: str) -> list[dict]:
        if len(text.split()) <= 4:                                     # maybe just a name: "asha", "emp-0002"
            kind, obj = self._target(st, it.ref or text, allow_default=False)
            if kind in ("queue", "master"):
                return self._show(st, it.ref or text, text)
        return [R("I didn't quite get that. " + self._where(st) + " Type `help` to see what I understand.")]

    # ================================================================ references
    def _qname(self, q: dict) -> str:
        e = self._emp(q)
        return e["full_name"] if e else ""

    def _target(self, st: dict, ref: str, allow_default: bool = True) -> tuple[str, object]:
        """Who is the user talking about? -> ("queue", idx) | ("master", id) | ("ambiguous", [names]) | ("none", None)"""
        q = st.get("queue", [])
        r = (ref or "").strip().lower()
        r = re.sub(r"\b(employee|the|person|guy|please|one|for|of|about)\b|'s\b|’s\b", " ", r)
        r = re.sub(r"\s+", " ", r).strip(" .?!,")
        cur = st["idx"] if st.get("phase") == "collecting" and q else None
        if r in ("", "current", "this", "that", "him", "her", "them", "he", "she", "they"):
            f = st.get("focus")
            if r in ("him", "her", "them", "he", "she", "they") and f and allow_default:
                return f[0], f[1]                      # pronouns follow whoever we were just talking about
            if cur is not None:
                return "queue", cur
            if f and allow_default:
                return f[0], f[1]
            return "none", None
        m = re.fullmatch(r"emp-?(\d{1,4})", r)
        if m:
            eid = f"EMP-{int(m.group(1)):04d}"
            return ("master", eid) if self.store.get(eid) else ("none", None)
        if r == "last" and q:
            return "queue", len(q) - 1
        m = re.fullmatch(r"#?(\d{1,3})", r)
        if m and q:
            i = int(m.group(1)) - 1
            return ("queue", i) if 0 <= i < len(q) else ("none", None)
        cands: list[tuple[float, str, object, str]] = []
        for i, item in enumerate(q):
            nm = self._qname(item)
            if nm:
                cands.append((max(fuzz.WRatio(r, nm.lower()), fuzz.ratio(r, nm.lower().split()[0])), "queue", i, nm))
        for e in self.store.all():
            if not any(c[3] == e["full_name"] for c in cands):
                cands.append((max(fuzz.WRatio(r, e["full_name"].lower()), fuzz.ratio(r, e["full_name"].lower().split()[0])), "master", e["employee_id"], e["full_name"]))
        cands = sorted([c for c in cands if c[0] >= 82], key=lambda c: -c[0])
        if not cands:
            return "none", None
        top = [c for c in cands if c[0] >= cands[0][0] - 3 and c[3] != cands[0][3]]
        if top:
            return "ambiguous", [cands[0][3]] + [c[3] for c in top]
        return cands[0][1], cands[0][2]

    def _load(self, kind: str, obj, st: dict) -> dict | None:
        if kind == "queue":
            return self._emp(st["queue"][obj])
        return self.store.get(obj)

    def _persist(self, kind: str, obj, st: dict, emp: dict) -> None:
        if kind == "queue" and not st["queue"][obj]["emp_id"]:
            st["queue"][obj]["emp"] = emp
        else:
            self.store.update(emp)

    def _resolve_or_say(self, st: dict, ref: str, what: str) -> tuple[tuple[str, object] | None, list[dict]]:
        kind, obj = self._target(st, ref)
        if kind == "ambiguous":
            return None, [R(f"Which one do you mean: {', '.join(obj)}?")]  # type: ignore[arg-type]
        if kind == "none":
            return None, [R(f"I couldn't tell who to {what}. " + (f"I looked for “{ref}”. " if ref else "") + "Say a name, a number from `status`, or an ID like EMP-0001.")]
        return (kind, obj), []

    # ================================================================ sheet
    def _ingest_sheet(self, st: dict, fname: str, data: bytes) -> list[dict]:
        if st.get("phase") == "collecting" and any(q["state"] in ("pending", "collecting") for q in st["queue"]):
            return [R("A batch is still in progress. Finish it, or say `reset` to discard it, then upload the new sheet.")]
        try:
            rows, bad = sheet.parse_sheet(data, fname)
        except sheet.SheetError as e:
            return [R(str(e))]
        total_rows, queue = len(rows) + len(bad), []
        for r in rows:
            emp = new_employee(r["name"], r["email"], r["phone"], fname)
            conf = self.store.find_conflicts(emp)
            if conf:
                bad.append({"row": "-", "name": r["name"], "reason": f"already in the master list as {conf[0]['employee_id']} ({conf[0]['name']}), same {conf[0]['field']}"})
                continue
            queue.append({"emp": emp, "state": "pending", "emp_id": None, "tmp": uuid.uuid4().hex[:8]})
        st.update(queue=queue, idx=0, phase="collecting" if queue else "idle", focus=None, awaiting=None, published=False)
        card = {"kind": "skipped", "rows": [[str(b["row"]), b["name"], b["reason"]] for b in bad[:15]]} if bad else None
        out = [R(f"Read **{fname}**: {total_rows} rows, **{len(queue)} accepted**, {len(bad)} skipped.", card)]
        if not queue:
            return out + [R("Nobody to onboard from this sheet. Fix the rows above and upload again.")]
        return out + self._next(st)

    # ================================================================ flow
    def _emp(self, entry: dict) -> dict | None:
        return self.store.get(entry["emp_id"]) if entry["emp_id"] else entry["emp"]

    def _next(self, st: dict) -> list[dict]:
        for i, q in enumerate(st["queue"]):
            if q["state"] == "pending":
                q["state"], st["idx"], st["focus"] = "collecting", i, None
                e = q["emp"]
                return [R(f"**Employee {i + 1} of {len(st['queue'])}: {e['full_name']}**\n{self._ask(e)}")]
        st["phase"] = "review"
        return [R("All employees in this sheet are processed. Running verification…")] + self._verify(st)

    def _skip(self, st: dict) -> list[dict]:
        if st.get("phase") != "collecting":
            return [R("Nothing to skip right now. " + self._where(st))]
        q = st["queue"][st["idx"]]
        q["state"], q["note"] = "skipped", "skipped by user"
        return [R(f"Skipped **{q['emp']['full_name']}**; they were not added to the master list.")] + self._next(st)

    def _step(self, emp: dict) -> str | None:
        miss = V.missing_fields(emp)
        return next((t for t in STEPS if any(g in miss for g in STEP_GROUPS[t])), None)

    def _ask(self, emp: dict) -> str:
        t = self._step(emp)
        return f"Send image {STEPS.index(t) + 1} of 4: **{STEP_LABEL[t]}**." if t else "Everything is filled."

    def _documents(self, st: dict, docs: list[tuple[str, bytes]]) -> list[dict]:
        if st.get("phase") != "collecting":
            return [R("I got the image, but there's no employee waiting for documents. Upload the employee sheet first.")]
        out: list[dict] = []
        for fname, data in docs:
            if st.get("phase") != "collecting":
                out.append(R(f"Ignored {fname}: everyone in this sheet is already done."))
                continue
            if not data:
                out.append(R(f"{fname} is empty, please send it again."))
                continue
            q = st["queue"][st["idx"]]
            emp = q["emp"]
            step = self._step(emp)
            d = self.uploads / q["tmp"]
            d.mkdir(parents=True, exist_ok=True)
            p = d / f"{step}_{uuid.uuid4().hex[:6]}_{re.sub(r'[^A-Za-z0-9._-]', '_', Path(fname).name)[:80]}"
            p.write_bytes(data)
            self._fill(emp, step, self.reader.read(step, [str(p)], emp), str(p.relative_to(self.store.dir)))
            q["emp"] = emp
            out += self._after_change(st, q, prefix=f"Yes ✓ {STEP_LABEL[step][0].upper() + STEP_LABEL[step][1:]} filled ({self.reader.source}): {self._brief(emp, step)}.")
        return out

    @staticmethod
    def _brief(emp: dict, step: str) -> str:
        if step == "pan":
            return emp["pan"]["number"]
        if step == "aadhaar":
            return emp["aadhaar"]["number_masked"]
        if step == "bank":
            return f"{emp['bank']['ifsc']}, a/c …{emp['bank']['account_number'][-4:]}"
        return emp["other"]["reference"]

    def _fill(self, emp: dict, step: str, data: dict, rel_path: str) -> None:
        """Fill only this step's empty fields; typed (real) values are never overwritten."""
        from .schema import get_path
        touched = False

        def put(path: str, value: str) -> None:
            nonlocal touched
            if not get_path(emp, path):
                set_path(emp, path, value)
                touched = True

        if step == "aadhaar":
            a = data["aadhaar"]
            if not emp["aadhaar"]["number_masked"]:
                self._set_aadhaar(emp, a["number"])
                touched = True
            for k in ("name", "dob", "gender", "address"):
                put(f"aadhaar.{k}", a[k])
            put("address.pincode", data["pincode"])
        else:
            for k, v in data[step].items():
                put(f"{step}.{k}", v)
        doc = emp["documents"][step]
        doc["files"].append(rel_path)
        doc["source"] = self.reader.source if touched else (doc["source"] or "entered")
        doc["filled_at"] = now_iso()
        self._consolidate(emp)

    def _set_aadhaar(self, emp: dict, number: str) -> None:
        d = re.sub(r"\D", "", number)
        a = emp["aadhaar"]
        a["number_masked"] = V.mask_aadhaar(d)
        a["hash"] = hmac.new(self._key, f"aadhaar:{d}".encode(), hashlib.sha256).hexdigest()
        a["checksum_valid"] = V.valid_aadhaar(d)
        if self.cfg.store_full_aadhaar:
            a["number"] = d

    @staticmethod
    def _consolidate(emp: dict) -> None:
        a, p = emp["aadhaar"], emp["pan"]
        emp["dob"] = a["dob"] or p["dob"]
        emp["age"] = V.calc_age(emp["dob"])
        emp["gender"] = a["gender"] or emp["gender"]
        emp["father_name"] = p["father_name"] or emp["father_name"]
        if a["address"]:
            emp["address"]["full"] = a["address"]

    def _after_change(self, st: dict, q: dict, nag: bool = True, prefix: str = "") -> list[dict]:
        """After the in-progress employee's data changed: duplicate check, then complete or ask for the next image."""
        emp = q["emp"]
        pre = (prefix + " ") if prefix else ""
        conf = self.store.find_conflicts(emp)
        if conf:
            c = conf[0]
            q["state"], q["note"] = "duplicate", f"{c['field']} matches {c['employee_id']}"
            return [R(f"{pre}🚫 **Duplicate:** this {c['field']} is already registered to {c['employee_id']} ({c['name']}). **{emp['full_name']}** was not added.")] + self._next(st)
        if V.missing_fields(emp):
            if not nag:
                return [R(prefix)] if prefix else []
            return [R(f"{pre}{self._ask(emp)}")]
        return self._complete(st, q, prefix)

    def _complete(self, st: dict, q: dict, prefix: str = "") -> list[dict]:
        pre = (prefix + " ") if prefix else ""
        try:
            saved = self.store.add(q["emp"])
        except Duplicate as d:
            c = d.conflicts[0]
            q["state"], q["note"] = "duplicate", f"{c['field']} matches {c['employee_id']}"
            return [R(f"{pre}🚫 **Duplicate:** {c['field']} already registered to {c['employee_id']} ({c['name']}). Not added.")] + self._next(st)
        q["state"], q["emp_id"], q["emp"] = "complete", saved["employee_id"], {}
        return [R(f"{pre}✅ **{saved['full_name']}** saved as **{saved['employee_id']}**.")] + self._next(st)

    # ================================================================ typed details & edits
    def _details(self, st: dict, text: str) -> list[dict]:
        if st.get("phase") != "collecting":
            return [R("Whose details are those? Say e.g. `Asha's PAN is ABCDE1234F`.")]
        q = st["queue"][st["idx"]]
        emp = q["emp"]
        msgs, errs = [], []
        rest = text
        for m in nlu.ACCOUNT_T.finditer(text):
            ok, msg = self._apply_fix(emp, "bank.account_number", m.group(1))
            (msgs if ok else errs).append(msg)
            rest = rest.replace(m.group(0), " ")
        for path, rx in (("pan.number", nlu.PAN_T), ("bank.ifsc", nlu.IFSC_T), ("aadhaar.dob", nlu.DOB_T)):
            m = rx.search(rest)
            if m:
                ok, msg = self._apply_fix(emp, path, m.group(1) if rx is nlu.DOB_T else m.group(0))
                (msgs if ok else errs).append(msg)
        for m in nlu.AADHAAR_T.finditer(rest):
            ok, msg = self._apply_fix(emp, "aadhaar.number", m.group(0))
            (msgs if ok else errs).append(msg)
        q["emp"] = emp
        out = [R(" ".join(errs))] if errs else []
        return out + (self._after_change(st, q, prefix="Got it: " + "; ".join(msgs) + ".") if msgs else [])

    def _edit(self, st: dict, it: nlu.Intent) -> list[dict]:
        res, err = self._resolve_or_say(st, it.ref, "change")
        if res is None:
            return err
        kind, obj = res
        emp = self._load(kind, obj, st)
        if emp is None:
            return [R("I can't find that record.")]
        ok, msg = self._apply_fix(emp, ALIASES[it.field], it.value)
        if not ok:
            return [R(msg)]
        st["focus"] = [kind, obj]
        in_progress = kind == "queue" and not st["queue"][obj]["emp_id"]
        if in_progress:
            st["queue"][obj]["emp"] = emp
            if st["queue"][obj] is st["queue"][st["idx"]]:
                return self._after_change(st, st["queue"][obj], nag=False, prefix=f"Done: {msg}.")
            return [R(f"Done: {msg}.")]
        if emp["status"] == "VERIFIED":
            emp["status"], emp["verification"]["passed"] = "COMPLETE", None
            st["published"] = False
        try:
            self.store.update(emp)
        except Duplicate as d:
            return [R(f"Not changed: {d}.")]
        st["awaiting"] = None
        return [R(f"Done: **{emp['full_name']}** ({emp['employee_id']}) {msg}. Say `verify` to re-check.")]

    def _apply_fix(self, emp: dict, path: str, v: str) -> tuple[bool, str]:
        label = path.replace(".", " ").replace("_", " ")
        if path == "email":
            if not V.valid_email(v):
                return False, "That email doesn't look valid."
        elif path == "phone":
            v = V.normalize_phone(v)
            if not v:
                return False, "That isn't a valid 10-digit Indian mobile number."
        elif path == "pan.number":
            v = v.upper().replace(" ", "")
            if not V.valid_pan(v):
                return False, f"“{v}” isn't a valid PAN. It looks like ABCDE1234F."
        elif path == "bank.ifsc":
            v = v.upper().replace(" ", "")
            if not V.valid_ifsc(v):
                return False, f"“{v}” isn't a valid IFSC. It looks like SBIN0001234."
        elif path == "bank.account_number":
            v = re.sub(r"\s", "", v)
            if not V.valid_account(v):
                return False, "An account number is 9 to 18 digits."
        elif path == "aadhaar.number":
            d = re.sub(r"\D", "", v)
            if not V.valid_aadhaar(d):
                return False, f"{d or v} isn't a valid Aadhaar (the checksum fails). Please check the digits."
            self._set_aadhaar(emp, d)
            self._mark(emp, "aadhaar")
            self._consolidate(emp)
            return True, f"Aadhaar is now {emp['aadhaar']['number_masked']}"
        elif path == "aadhaar.dob":
            dt = V.parse_date(v)
            if not dt and not re.fullmatch(r"\d{4}", v):
                return False, "Please give the date like 15/08/1990."
            v = dt.strftime("%d/%m/%Y") if dt else v
        elif path == "aadhaar.gender":
            g = {"m": "Male", "male": "Male", "f": "Female", "female": "Female"}.get(v.lower())
            if not g:
                return False, "Gender should be Male or Female."
            v = g
        set_path(emp, path, v)
        if path == "address.full":
            emp["aadhaar"]["address"] = v
            pin = re.search(r"(?<!\d)(\d{6})(?!\d)", v)
            if pin:
                emp["address"]["pincode"] = pin.group(1)
        self._mark(emp, GROUP.get(path.split(".")[0], ""))
        self._consolidate(emp)
        return True, f"{label} set to {v}" if path != "phone" else f"phone set to {v}"

    @staticmethod
    def _mark(emp: dict, group: str) -> None:
        if group and emp["documents"][group]["source"] in ("", "placeholder"):
            emp["documents"][group]["source"] = "entered" if emp["documents"][group]["source"] == "" else "placeholder"

    # ================================================================ report / verify / confirm
    def _report_rows(self, st: dict, write: bool) -> tuple[list[dict], int, int]:
        rows, ok_n, done = [], 0, 0
        for i, q in enumerate(st["queue"], 1):
            if q["state"] == "complete":
                emp = self.store.get(q["emp_id"])
                res = V.verify(emp, self.store.find_conflicts(emp, emp["employee_id"]))
                if write:
                    emp["verification"] = {**res, "checked_at": now_iso()}
                    self.store.update(emp, publish=False)
                done += 1
                ok_n += res["passed"]
                rows.append({"n": i, "name": emp["full_name"], "id": emp["employee_id"], "result": "PASS" if res["passed"] else "FAIL",
                             "issues": res["issues"], "warnings": res["warnings"]})
            else:
                e = q["emp"] or {}
                rows.append({"n": i, "name": e.get("full_name", ""), "id": "", "result": q["state"].upper(),
                             "issues": [q["note"]] if q.get("note") else [], "warnings": []})
        return rows, ok_n, done

    def _verify(self, st: dict) -> list[dict]:
        rows, ok_n, done = self._report_rows(st, write=True)
        st["published"] = False
        if not done:
            st["awaiting"] = None
            return [R("No completed employees to verify yet.")]
        st["awaiting"] = "confirm" if ok_n else None
        tail = (f"**{ok_n} of {done}** passed. Say `confirm` to publish the verified ones to the master sheet." if ok_n
                else "None passed yet. Ask `what's wrong?`, fix the issues (e.g. `change 2 pan to ABCDE1234F`), then `verify` again.")
        if 0 < ok_n < done:
            tail += " The others need fixing first."
        return [R(tail, {"kind": "report", "rows": rows})]

    def _confirm(self, st: dict) -> list[dict]:
        done = [q for q in st.get("queue", []) if q["state"] == "complete"]
        if not done:
            return [R("There are no completed employees to publish yet. " + self._where(st))]
        passed, failed = [], []
        for q in done:
            emp = self.store.get(q["emp_id"])
            res = V.verify(emp, self.store.find_conflicts(emp, emp["employee_id"]))
            emp["verification"] = {**res, "checked_at": now_iso()}
            if res["passed"]:
                emp["status"] = "VERIFIED"
                passed.append(emp["full_name"])
            else:
                failed.append(f"{emp['full_name']} ({'; '.join(res['issues'][:2])})")
            self.store.update(emp, publish=False)
        total = self.store.publish_excel()
        st["awaiting"], st["published"] = None, bool(total)
        msg = f"Published **{len(passed)}** verified employee(s) to the master sheet ({total} in total)."
        if failed:
            msg += "\nNot published, fix them and `verify` again:\n• " + "\n• ".join(failed)
        return [R(msg, {"kind": "download"} if total else None)]

    def _download(self) -> list[dict]:
        if not self.store.xlsx_path.exists():
            return [R("The master sheet is empty so far. Verify a batch and `confirm` to publish it first.")]
        return [R("Here's the master sheet.", {"kind": "download"})]

    # ================================================================ questions
    def _status(self, st: dict, ref: str = "") -> list[dict]:
        q = st.get("queue", [])
        if ref and self._target(st, ref, allow_default=False)[0] in ("queue", "master"):
            return self._show(st, ref, "")
        if not q:
            n = len(self.store.all())
            return [R(f"No batch in progress. The master list has {n} employee(s). " + self._where(st))]
        label = {"pending": "waiting", "collecting": "in progress", "complete": "saved", "skipped": "skipped", "duplicate": "duplicate"}
        rows = []
        for i, item in enumerate(q, 1):
            e = self._emp(item) or {}
            rows.append([str(i), e.get("full_name", ""), e.get("employee_id", "") or "—", label[item["state"]] + (f" ({e['status'].lower()})" if item["emp_id"] and e else "")])
        saved = sum(x["state"] == "complete" for x in q)
        left = sum(x["state"] in ("pending", "collecting") for x in q)
        text = f"**{saved} of {len(q)}** saved" + (f", {left} left." if left else ".")
        if st.get("phase") == "collecting":
            cur = q[st["idx"]]["emp"]["full_name"]
            nxt = next((self._qname(x) for x in q[st["idx"] + 1:] if x["state"] == "pending"), "")
            text += f" Now on **{cur}**" + (f", next up: {nxt}." if nxt else ", the last one.")
        return [R(text, {"kind": "table", "head": ["#", "Name", "ID", "State"], "rows": rows})]

    def _show(self, st: dict, ref: str, text: str) -> list[dict]:
        res, err = self._resolve_or_say(st, ref, "show")
        if res is None:
            return err
        kind, obj = res
        emp = self._load(kind, obj, st)
        if emp is None:
            return [R("I can't find that record.")]
        st["focus"] = [kind, obj]
        where = "saved as " + emp["employee_id"] if emp["employee_id"] else "in progress, not saved yet"
        return [R(f"Here's **{emp['full_name']}** ({where}).", self._profile_card(emp, emp["full_name"]))]

    def _issues(self, st: dict, ref: str) -> list[dict]:
        if ref:
            res, err = self._resolve_or_say(st, ref, "check")
            if res is None:
                return err
            kind, obj = res
            emp = self._load(kind, obj, st)
            st["focus"] = [kind, obj]
            if emp is None:
                return [R("I can't find that record.")]
            if not emp["employee_id"]:
                miss = V.missing_fields(emp)
                return [R(f"**{emp['full_name']}** is still in progress. " + (("Missing: " + ", ".join(V.LABELS[f] for fs in miss.values() for f in fs) + ".") if miss else "Nothing missing."))]
            res_v = V.verify(emp, self.store.find_conflicts(emp, emp["employee_id"]))
            if res_v["passed"]:
                return [R(f"No problems with **{emp['full_name']}**." + (f" Note: {res_v['warnings'][0]}" if res_v["warnings"] else ""))]
            return [R(f"**{emp['full_name']}** has {len(res_v['issues'])} issue(s):\n" + "\n".join("✗ " + i for i in res_v["issues"]))]
        rows, _, done = self._report_rows(st, write=False)
        bad = [r for r in rows if r["result"] != "PASS"]
        if st.get("phase") == "collecting":
            e = st["queue"][st["idx"]]["emp"]
            miss = V.missing_fields(e)
            pre = f"**{e['full_name']}** (in progress) is missing: " + ", ".join(V.LABELS[f] for fs in miss.values() for f in fs) + ".\n" if miss else ""
            return [R(pre + ("Nothing wrong with the saved ones." if not bad else f"{len(bad)} saved/processed employee(s) need attention:"), {"kind": "report", "rows": bad} if bad else None)]
        if not rows:
            return [R("There's no batch yet. " + self._where(st))]
        if not bad:
            return [R("Nothing wrong. Everyone passed. " + ("Say `confirm` to publish." if st.get("awaiting") == "confirm" else ""))]
        return [R(f"{len(bad)} of {len(rows)} need attention:", {"kind": "report", "rows": bad})]

    def _profile_card(self, emp: dict, title: str) -> dict:
        a, p, b = emp["aadhaar"], emp["pan"], emp["bank"]
        src = sorted({d["source"] for d in emp["documents"].values() if d.get("source")})
        rows = [["Employee ID", emp["employee_id"] or "not saved yet"], ["Email", emp["email"]], ["Phone", emp["phone"]],
                ["Date of birth", emp["dob"] + (f" (age {emp['age']})" if emp["age"] is not None else "")], ["Gender", emp["gender"]],
                ["Father's name", emp["father_name"]], ["Address", emp["address"]["full"]], ["Aadhaar", a["number_masked"]],
                ["PAN", p["number"]], ["Account holder", b["account_holder"]], ["Account number", b["account_number"]], ["IFSC", b["ifsc"]],
                ["Bank", ", ".join(x for x in (b["bank_name"], b["branch"]) if x)], ["Other document", emp["other"]["reference"]]]
        rows = [[k, v or "not provided"] for k, v in rows]
        if src:
            rows.append(["Values", ", ".join(src)])
        return {"kind": "fields", "title": title, "rows": rows}

    # ================================================================ progress / chips
    def _chips(self, st: dict) -> list[str]:
        ph = st.get("phase", "idle")
        if ph == "collecting":
            return ["Status", "Skip"]
        if ph == "review":
            if st.get("awaiting") == "confirm":
                return ["Confirm", "What's wrong?", "Status"]
            if st.get("published"):
                return ["Download", "Status"]
            return ["What's wrong?", "Verify"]
        return ["Help"]

    def _progress(self, st: dict) -> dict:
        q = st.get("queue") or []
        cur = q[st["idx"]] if st.get("phase") == "collecting" and q else None
        return {"phase": st.get("phase", "idle"), "total": len(q), "index": (st["idx"] + 1) if cur else 0,
                "name": cur["emp"].get("full_name", "") if cur else "", "done": sum(x["state"] == "complete" for x in q)}
