"""The standard employee master record. Every employee in master.json has exactly this shape."""
import copy
from datetime import datetime, timezone

STATUSES = ("PENDING", "COMPLETE", "VERIFIED")

TEMPLATE: dict = {
    "employee_id": "",                 # EMP-0001, assigned when the employee is added to the master list
    "status": "PENDING",               # PENDING -> COMPLETE (all documents read) -> VERIFIED (checks passed, in master sheet)
    "full_name": "",                   # from the uploaded sheet
    "email": "",                       # from the uploaded sheet
    "phone": "",                       # from the uploaded sheet, normalised to 10 digits
    "dob": "",                         # dd/mm/yyyy (Aadhaar first, else PAN)
    "age": None,
    "gender": "",
    "father_name": "",                 # from PAN
    "address": {"full": "", "pincode": ""},          # from Aadhaar (back side)
    "aadhaar": {"number_masked": "", "hash": "", "checksum_valid": None, "name": "", "dob": "", "gender": "", "address": ""},
    "pan": {"number": "", "name": "", "father_name": "", "dob": ""},
    "bank": {"account_holder": "", "account_number": "", "ifsc": "", "bank_name": "", "branch": ""},
    "other": {"description": "", "reference": ""},   # the 4th document: any other supporting document
    "documents": {                     # uploaded files kept on disk + where the values came from
        "aadhaar": {"files": [], "source": "", "filled_at": ""},     # source: placeholder | entered | scanned (later)
        "pan": {"files": [], "source": "", "filled_at": ""},
        "bank": {"files": [], "source": "", "filled_at": ""},      # the cancelled cheque
        "other": {"files": [], "source": "", "filled_at": ""},
    },
    "verification": {"passed": None, "checked_at": "", "issues": [], "warnings": []},
    "source": "",                      # uploaded sheet name
    "created_at": "",
    "updated_at": "",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_employee(name: str, email: str, phone: str, source: str = "") -> dict:
    e = copy.deepcopy(TEMPLATE)
    e.update(full_name=name, email=email, phone=phone, source=source, created_at=now_iso(), updated_at=now_iso())
    return e


def get_path(d: dict, path: str):
    for k in path.split("."):
        d = d.get(k) if isinstance(d, dict) else None
    return d


def set_path(d: dict, path: str, value) -> None:
    keys = path.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value
