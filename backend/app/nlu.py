"""Understands what the user means from plain sentences. Rules + fuzzy matching, no LLM, so it is instant,
free and predictable. Returns an Intent; the chat engine decides what to do with it."""
import re
from dataclasses import dataclass

from rapidfuzz import fuzz, process

# canonical field key (as used by the chat engine) -> the ways people say it
FIELD_SYN = {
    "phone": ["phone number", "mobile number", "contact number", "phone no", "mobile no", "phone", "mobile", "contact"],
    "email": ["email address", "email id", "e-mail", "email", "mail id", "mail"],
    "name": ["full name", "full_name", "employee name", "name"],
    "dob": ["date of birth", "birth date", "birthday", "dob"],
    "gender": ["gender", "sex"],
    "address": ["address"],
    "pincode": ["pin code", "pincode", "zip code", "zip", "pin"],
    "aadhaar": ["aadhaar number", "aadhar number", "adhar number", "aadhaar no", "aadhaar", "aadhar", "adhaar", "adhar", "uid"],
    "pan": ["pan number", "pan card", "pan no", "pan"],
    "account": ["account number", "account_number", "account no", "acc no", "acct no", "a/c no", "a/c", "account"],
    "ifsc": ["ifsc code", "ifsc"],
    "holder": ["account holder name", "account_holder", "account holder", "holder name", "holder"],
    "bank": ["bank name", "bank_name", "bank"],
    "branch": ["branch"],
    "father_name": ["father's name", "father’s name", "fathers name", "father_name", "father name", "father"],
    "aadhaar_name": ["name on aadhaar", "aadhaar name", "aadhaar_name"],
    "pan_name": ["name on pan", "pan name", "pan_name"],
}
PHRASE = {p: k for k, ps in FIELD_SYN.items() for p in ps}
F = "(?<![a-z])(?:" + "|".join(re.escape(p) for p in sorted(PHRASE, key=len, reverse=True)) + ")(?![a-z])"
VERB = r"(?:please\s+)?(?:fix|change|update|set|correct|edit|make|replace|modify)"
SEP = r"(?:\s+(?:to|as|with|is|=|:)\s+|\s*[=:]\s*|\s+)"

EDITS = [
    re.compile(rf"^{VERB}\s+(?:the\s+)?(?P<f>{F})\s+(?:of|for)\s+(?P<e>.+?)\s*(?:\s(?:to|as|with|is)\s|[=:])\s*(?P<v>.+)$", re.I),
    re.compile(rf"^{VERB}\s+(?:the\s+)?(?P<f>{F}){SEP}(?P<v>.+)$", re.I),
    re.compile(rf"^{VERB}\s+(?P<e>.+?)(?:'s|’s|s')\s+(?P<f>{F}){SEP}(?P<v>.+)$", re.I),
    re.compile(rf"^{VERB}\s+(?P<e>#?\d+|emp-\d{{1,4}}|[a-z][a-z .'-]*?)\s+(?P<f>{F}){SEP}(?P<v>.+)$", re.I),
    re.compile(rf"^(?P<e>.+?)(?:'s|’s|s')\s+(?P<f>{F})\s+(?:is|to be|should be|=|:)\s+(?P<v>.+)$", re.I),
    re.compile(rf"^(?P<e>her|his|their)\s+(?P<f>{F})\s+(?:is|=|:|to be|should be)\s+(?P<v>.+)$", re.I),
    re.compile(rf"^(?:the\s+|my\s+)?(?P<f>{F})\s+(?:is|=|:)\s+(?P<v>.+)$", re.I),
]

PAN_T = re.compile(r"\b[A-Za-z]{5}\d{4}[A-Za-z]\b")
AADHAAR_T = re.compile(r"(?<![\d])\d{4}[\s-]?\d{4}[\s-]?\d{4}(?![\d])")
IFSC_T = re.compile(r"\b[A-Za-z]{4}0[A-Za-z0-9]{6}\b")
ACCOUNT_T = re.compile(r"(?:a/?c|acc(?:ount)?(?:\s*(?:no|number))?)\W*(\d{9,18})\b", re.I)
DOB_T = re.compile(r"(?:dob|born|birth\w*)\W*(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{4})", re.I)

PATTERNS = [
    ("confirm", r"^(?:please\s+)?(?:confirm|publish|approve|finali[sz]e|submit|go ahead|looks good|all good|push to master|save to master|update (?:the )?master)\b"),
    ("verify", r"\b(?:verify|validate|re-?check|run (?:the )?checks?|check (?:everything|all|again|them|now))\b"),
    ("reset", r"\b(?:reset|start over|start again|clear (?:everything|all|batch|this)|discard|cancel (?:the )?batch|new batch)\b"),
    ("download", r"\b(?:download|excel|xlsx|spreadsheet|master (?:sheet|file|excel))\b|\bxls\b"),
    ("skip", r"\b(?:skip|move on|next (?:one|person|employee|guy)|leave (?:him|her|them|this one))\b|^next\W*$"),
    ("placeholder", r"\b(?:placeholder|dummy|fake|why .*(?:same|generated|filled|random)|real (?:data|values))\b"),
    ("issues", r"\b(?:why|fail(?:ed|s|ing)?|wrong|problems?|issues?|errors?|missing|incomplete|not passing|didn'?t pass)\b"),
    ("help", r"^(?:help|\?)\W*$|\b(?:how (?:do|does|to|can)|what can you do|commands?|guide|instructions?)\b"),
    ("status", r"\bwho(?:'s| is| are)? (?:left|remaining|next|pending|done|saved|current)\b|\bwhat'?s next\b|\bwhat next\b"),
    ("show", r"^(?:please\s+)?(?:show|display|view|open|see|get|give me|tell me about|what about|what is|what'?s|details?\s+(?:of|for|on)|info\s+(?:on|about|of)|who is)\b(?P<rest>.*)$"),
    ("status", r"\b(?:status|progress|where are we|how many|summary|overview|list|who(?:'s| is| are)? (?:left|remaining|next|pending|done|saved|current)|what'?s next|what next|remaining|how far|left)\b"),
    ("greet", r"^(?:hi|hello|hey|hola|namaste|good (?:morning|afternoon|evening))\b"),
    ("thanks", r"^(?:thanks|thank you|thx|ty|cheers)\b"),
    ("affirm", r"^(?:yes|yep|yeah|yup|ok|okay|sure|y|done|alright|fine|great|cool)\W*$"),
    ("deny", r"^(?:no|nope|nah|n|not now|cancel)\W*$"),
]
COMPILED = [(n, re.compile(p, re.I)) for n, p in PATTERNS]
WORDS = ["confirm", "verify", "reset", "download", "skip", "status", "help", "publish", "validate", "progress"]
WORD_INTENT = {"publish": "confirm", "validate": "verify", "progress": "status"}


@dataclass
class Intent:
    name: str
    ref: str = ""          # who: "2", "asha", "emp-0003", "her", "last"
    field: str = ""        # canonical field key
    value: str = ""
    text: str = ""


def clean_value(v: str) -> str:
    return v.strip().strip("\"'“”‘’").rstrip(".,;").strip()


def details_in(text: str) -> bool:
    return bool(PAN_T.search(text) or IFSC_T.search(text) or ACCOUNT_T.search(text) or DOB_T.search(text) or AADHAAR_T.search(text))


def parse(text: str) -> Intent:
    t = re.sub(r"\s+", " ", (text or "").strip())
    low = t.lower()
    if not t:
        return Intent("empty", text=t)
    for rx in EDITS:
        m = rx.match(t)
        if m:
            d = m.groupdict()
            v = clean_value(d.get("v") or "")
            f = PHRASE.get((d.get("f") or "").lower())
            if v and f:
                return Intent("edit", ref=(d.get("e") or "").strip(), field=f, value=v, text=t)
    if details_in(t) and not re.match(r"^(?:show|what|who|why|how)\b", low):
        return Intent("details", text=t)
    for name, rx in COMPILED:
        m = rx.search(t)
        if m:
            ref = (m.groupdict().get("rest") or "").strip() if name == "show" else ""
            if name == "show" and re.search(r"\b(status|progress|summary|overview|all|everyone|list|left|remaining)\b", ref, re.I):
                return Intent("status", text=t)
            if name == "show" and re.search(r"\b(issues?|problems?|missing|failed|errors?)\b", ref, re.I):
                return Intent("issues", ref=find_ref(ref), text=t)
            if name == "show":
                return Intent("show", ref=find_ref(ref) or ref, text=t)
            if name in ("issues", "status"):
                return Intent(name, ref=find_ref(t) or name_after_preposition(t), text=t)
            return Intent(name, text=t)
    words = low.split()
    if 1 <= len(words) <= 2:                                  # typos: "verfiy", "confrim"
        hit = process.extractOne(words[0], WORDS, scorer=fuzz.ratio, score_cutoff=80)
        if hit:
            return Intent(WORD_INTENT.get(hit[0], hit[0]), text=t)
    ref = find_ref(t)
    return Intent("unknown", ref=ref, text=t)


ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
       "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "6th": 6, "7th": 7, "8th": 8, "9th": 9, "10th": 10}


def name_after_preposition(text: str) -> str:
    """'any problems with manohar?' -> 'manohar'. Ignored when it is clearly about everyone."""
    m = re.search(r"\b(?:with|for|about|of|on|regarding)\s+(?!the\b)(.+?)\s*[?!.]*$", text, re.I)
    ref = re.sub(r"\b(?:employee|person)\b", "", m.group(1), flags=re.I).strip() if m else ""
    return "" if re.fullmatch(r"(?:everyone|everybody|all|all of them|them all|the batch|this batch|now|today)", ref, re.I) else ref


def find_ref(text: str) -> str:
    """Pull out who the sentence is about: EMP-0003, #2, employee 2, 'the second one', 'last', 'her'."""
    t = text.lower()
    m = re.search(r"emp-?\s?(\d{1,4})", t)
    if m:
        return f"emp-{int(m.group(1)):04d}"
    m = re.search(r"(?:#|\b(?:employee|emp|person|number|no\.?|row)\s*)(\d{1,3})\b", t)
    if m:
        return m.group(1)
    for w, n in ORD.items():
        if re.search(rf"\b{w}\b", t):
            return str(n)
    if re.search(r"\blast\b", t):
        return "last"
    if re.search(r"\b(?:him|her|them|he|she|they|this one|current)\b", t):
        return "current"
    return ""
