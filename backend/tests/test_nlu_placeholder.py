import pytest

from app import validate as V
from app.nlu import parse
from app.reader import PlaceholderReader
from app.schema import new_employee


@pytest.mark.parametrize("text,name", [
    ("hi", "greet"), ("Hello there", "greet"), ("thanks!", "thanks"), ("yes", "affirm"), ("nope", "deny"), ("help", "help"), ("how does this work?", "help"),
    ("how many are left?", "status"), ("who is next", "status"), ("what's the progress", "status"), ("status", "status"),
    ("skip this one", "skip"), ("next person", "skip"), ("move on", "skip"),
    ("verify", "verify"), ("verfiy", "verify"), ("please re-check everything", "verify"), ("confirm", "confirm"), ("confrim", "confirm"),
    ("publish it", "confirm"), ("looks good", "confirm"), ("go ahead", "confirm"),
    ("download the excel", "download"), ("give me the xls", "download"), ("reset", "reset"), ("start over", "reset"),
    ("what's wrong?", "issues"), ("why did it fail", "issues"), ("what is missing", "issues"),
    ("what is a placeholder", "placeholder"), ("why is the data fake", "placeholder"),
    ("PAN ABCDE1234F", "details"), ("ifsc SBIN0001234 and account 123456789012", "details"), ("dob 15/08/1990", "details"),
    ("blah blah", "unknown"),
])
def test_intents(text, name):
    assert parse(text).name == name


@pytest.mark.parametrize("text,ref,field,value", [
    ("change Asha's phone to 9845099999", "Asha", "phone", "9845099999"),
    ("fix 2 pan ABCDE1234F", "2", "pan", "ABCDE1234F"),
    ("fix pan ABCDE1234F", "", "pan", "ABCDE1234F"),
    ("update the email of Varun to v@x.com", "Varun", "email", "v@x.com"),
    ("set her mobile 9845012345", "her", "phone", "9845012345"),
    ("asha's pan is ABCDE1234F", "asha", "pan", "ABCDE1234F"),
    ("email is a@b.com", "", "email", "a@b.com"),
    ("her email is a@b.com", "her", "email", "a@b.com"),
    ("change bank name to Acme Bank", "", "bank", "Acme Bank"),
    ("fix EMP-0003 holder Asha Rao", "EMP-0003", "holder", "Asha Rao"),
    ("edit the date of birth for the second one to 01/02/1990", "the second one", "dob", "01/02/1990"),
    ("fix account_number 123456789012", "", "account", "123456789012"),
])
def test_edits(text, ref, field, value):
    i = parse(text)
    assert (i.name, i.ref, i.field, i.value) == ("edit", ref, field, value)


def test_refs():
    assert parse("show asha").ref == "asha" and parse("tell me about employee 2").ref == "2" and parse("show EMP-3").ref == "emp-0003"
    assert parse("what's wrong with the last one?").ref == "last" and parse("show the second one").ref == "2"


def test_placeholders_are_valid_unique_per_step_and_pass_verification():
    r, seen = PlaceholderReader(), set()
    for i in range(50):
        e = new_employee(f"Person {i} Tester", f"p{i}@x.com", f"98450{i:05d}")
        pan, aad, bank, oth = (r.read(s, ["x.png"], e) for s in ("pan", "aadhaar", "bank", "other"))
        assert set(pan) == {"pan"} and set(aad) == {"aadhaar", "pincode"} and set(bank) == {"bank"} and set(oth) == {"other"}   # one section per step
        assert V.valid_pan(pan["pan"]["number"]) and pan["pan"]["number"][3] == "P" and V.valid_aadhaar(aad["aadhaar"]["number"])
        assert V.valid_ifsc(bank["bank"]["ifsc"]) and V.valid_account(bank["bank"]["account_number"]) and oth["other"]["reference"].startswith("OTH-")
        seen.add((aad["aadhaar"]["number"], pan["pan"]["number"], bank["bank"]["account_number"], oth["other"]["reference"]))
        assert r.read("pan", ["y.png"], e) == pan                      # deterministic per employee
    assert len(seen) == 50
