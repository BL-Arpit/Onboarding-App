"""Field validators and the employee verification rules. Pure functions, no I/O."""
import re
from datetime import date

from rapidfuzz import fuzz

from .config import get_settings

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_TITLES = {"MR", "MRS", "MS", "MISS", "DR", "SHRI", "SMT", "SRI", "KUMARI", "LATE"}


def compact(s: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


# ---------------- contact ----------------
def valid_email(v: str) -> bool:
    return bool(EMAIL_RE.match((v or "").strip())) and ".." not in v


def normalize_phone(v: str) -> str:
    """Returns a 10-digit Indian mobile, or '' if it is not one."""
    d = re.sub(r"\D", "", str(v or ""))
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    elif len(d) == 11 and d.startswith("0"):
        d = d[1:]
    return d if re.fullmatch(r"[6-9]\d{9}", d) else ""


# ---------------- ids ----------------
def valid_pan(v: str) -> bool:
    return bool(PAN_RE.match((v or "").strip().upper()))


def valid_ifsc(v: str) -> bool:
    return bool(IFSC_RE.match((v or "").strip().upper()))


def valid_account(v: str) -> bool:
    return bool(re.fullmatch(r"\d{9,18}", (v or "").strip()))


_D = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],[3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],
      [5,9,8,7,6,0,4,3,2,1],[6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],[9,8,7,6,5,4,3,2,1,0]]
_P = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],[8,9,1,6,0,4,3,5,2,7],
      [9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],[2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]]
_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def verhoeff_valid(n: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(n)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def verhoeff_digit(n: str) -> str:
    c = 0
    for i, ch in enumerate(reversed(n)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return str(_INV[c])


def valid_aadhaar(v: str) -> bool:
    d = re.sub(r"\D", "", v or "")
    return len(d) == 12 and d[0] not in "01" and verhoeff_valid(d)


def mask_aadhaar(v: str) -> str:
    d = re.sub(r"\D", "", v or "")
    return f"XXXX XXXX {d[-4:]}" if len(d) >= 4 else ""


# ---------------- dates ----------------
def parse_date(v: str | None) -> date | None:
    m = re.search(r"(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4})", v or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def calc_age(dob: str | None, today: date | None = None) -> int | None:
    today = today or date.today()
    d = parse_date(dob)
    if d:
        return today.year - d.year - ((today.month, today.day) < (d.month, d.day))
    m = re.fullmatch(r"\s*(\d{4})\s*", dob or "")
    return today.year - int(m.group(1)) if m else None


# ---------------- names ----------------
def _norm_name(n: str | None) -> str:
    t = re.sub(r"[^A-Za-z ]", " ", (n or "").upper()).split()
    return " ".join(x for x in t if x not in _TITLES)


def name_score(a: str | None, b: str | None) -> float | None:
    """0-100. Ignores titles, word order and lost spaces (OCR often glues words: MANOHARLAL)."""
    na, nb = _norm_name(a), _norm_name(b)
    if not na or not nb:
        return None
    return round(float(max(fuzz.token_sort_ratio(na, nb), fuzz.ratio(na.replace(" ", ""), nb.replace(" ", "")))), 1)


def name_status(a: str | None, b: str | None) -> tuple[str, float | None]:
    s = get_settings()
    sc = name_score(a, b)
    if sc is None:
        return "MISSING", None
    return ("PASS" if sc >= s.name_pass else "WARN" if sc >= s.name_warn else "FAIL"), sc


# ---------------- completeness ----------------
# group -> required dotted fields. Order = the order we ask for documents.
REQUIRED = {
    "aadhaar": ["aadhaar.number_masked", "aadhaar.name", "dob"],
    "aadhaar_back": ["address.full"],
    "pan": ["pan.number", "pan.name"],
    "bank": ["bank.account_number", "bank.ifsc", "bank.account_holder"],
    "other": ["other.reference"],
}
LABELS = {
    "aadhaar.number_masked": "Aadhaar number", "aadhaar.name": "name on Aadhaar", "dob": "date of birth",
    "address.full": "address", "pan.number": "PAN number", "pan.name": "name on PAN",
    "bank.account_number": "account number", "bank.ifsc": "IFSC", "bank.account_holder": "account holder",
    "other.reference": "other document",
}


def missing_fields(emp: dict) -> dict[str, list[str]]:
    from .schema import get_path
    out = {}
    for g, fields in REQUIRED.items():
        miss = [f for f in fields if not get_path(emp, f)]
        if miss:
            out[g] = miss
    return out


# ---------------- verification ----------------
def verify(emp: dict, conflicts: list[dict] | None = None) -> dict:
    """Returns {passed, issues, warnings}. FAIL-level problems go to issues and block publishing."""
    issues: list[str] = []
    warns: list[str] = []
    for g, miss in missing_fields(emp).items():
        issues.append("Missing: " + ", ".join(LABELS[m] for m in miss))
    if not valid_email(emp["email"]):
        issues.append("Email is not valid")
    if not normalize_phone(emp["phone"]):
        issues.append("Phone is not a valid 10-digit Indian mobile")
    p, a, b = emp["pan"], emp["aadhaar"], emp["bank"]
    if p["number"]:
        if not valid_pan(p["number"]):
            issues.append(f"PAN {p['number']} has an invalid format")
        elif p["number"][3] != "P":
            warns.append("PAN is not an individual PAN")
    if a["number_masked"] and not a["checksum_valid"]:
        issues.append("Aadhaar number fails the checksum (likely a misread digit)")
    if b["ifsc"] and not valid_ifsc(b["ifsc"]):
        issues.append(f"IFSC {b['ifsc']} has an invalid format")
    if b["account_number"] and not valid_account(b["account_number"]):
        issues.append("Account number must be 9 to 18 digits")
    for label, other in (("Aadhaar", a["name"]), ("PAN", p["name"]), ("bank account holder", b["account_holder"])):
        if other:
            st, sc = name_status(emp["full_name"], other)
            if st == "FAIL":
                issues.append(f"Name on {label} ('{other}') does not match the sheet name ('{emp['full_name']}', {sc:.0f}%)")
            elif st == "WARN":
                warns.append(f"Name on {label} ('{other}') is close to the sheet name but not identical ({sc:.0f}%)")
    if a["name"] and p["name"]:
        st, sc = name_status(a["name"], p["name"])
        if st == "FAIL":
            issues.append(f"Aadhaar name and PAN name differ ({sc:.0f}%)")
    da, dp = parse_date(a["dob"]), parse_date(p["dob"])
    if da and dp and da != dp:
        issues.append(f"Date of birth differs: Aadhaar {a['dob']} vs PAN {p['dob']}")
    elif re.fullmatch(r"\d{4}", a["dob"] or "") and dp and dp.year != int(a["dob"]):
        issues.append(f"Birth year differs: Aadhaar {a['dob']} vs PAN {p['dob']}")
    if emp.get("age") is not None and emp["age"] < 18:
        issues.append(f"Age is {emp['age']}; must be at least 18")
    ph = [k for k, d in emp["documents"].items() if d.get("source") == "placeholder"]
    if ph:
        warns.append("Placeholder values (document reading is not enabled yet): " + ", ".join(ph))
    for c in conflicts or []:
        issues.append(f"Duplicate {c['field']}: already registered to {c['employee_id']} ({c['name']})")
    return {"passed": not issues, "issues": issues, "warnings": warns}
