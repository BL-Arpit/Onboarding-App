"""Document reader seam. Today: placeholders only (no OCR, no classification). Later: drop in a real reader
that implements the same `read` and returns the same dict shape, and nothing else in the app changes."""
import hashlib
from typing import Protocol

from .validate import verhoeff_digit

STEPS = ("pan", "aadhaar", "bank", "other")


class DocumentReader(Protocol):
    source: str

    def read(self, step: str, paths: list[str], emp: dict) -> dict: ...


class PlaceholderReader:
    """Ignores the image contents and returns plausible, format-valid, per-employee-unique values for the
    requested step only (valid Aadhaar checksum, PAN pattern, IFSC pattern)."""
    source = "placeholder"

    def read(self, step: str, paths: list[str], emp: dict) -> dict:
        key = f"{emp['email'].lower()}|{emp['phone']}"

        def h(salt: str) -> int:
            return int(hashlib.sha256(f"{salt}:{key}".encode()).hexdigest(), 16)

        def digits(salt: str, n: int) -> str:
            return str(h(salt) % 10 ** n).zfill(n)

        name = emp["full_name"].upper()
        if step == "pan":
            letters = "".join(chr(65 + (h("p") >> (5 * i)) % 26) for i in range(3))
            initial = (name.split()[-1][:1] if name.split() else "X")
            initial = initial if initial.isalpha() else "X"
            return {"pan": {"number": f"{letters}P{initial}{digits('p2', 4)}{chr(65 + h('p3') % 26)}", "name": name,
                            "father_name": "PLACEHOLDER FATHER", "dob": "01/01/1990"}}
        if step == "aadhaar":
            first11 = str(2 + h("a0") % 8) + digits("a1", 10)
            return {"aadhaar": {"number": first11 + verhoeff_digit(first11), "name": name, "dob": "01/01/1990", "gender": "Not specified",
                                "address": "Placeholder Address, Placeholder City - 560001"}, "pincode": "560001"}
        if step == "bank":
            return {"bank": {"account_holder": name, "account_number": str(1 + h("b") % 9) + digits("b2", 11), "ifsc": "PLCH0" + digits("b3", 6),
                             "bank_name": "Placeholder Bank", "branch": "Placeholder Branch"}}
        return {"other": {"description": "Other document", "reference": "OTH-" + digits("o", 6)}}
