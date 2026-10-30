import io
import os
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="emp-test-")
os.environ["DATA_DIR"] = _tmp

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000" "1f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082")


def make_xlsx(rows, header=("Name", "Email", "Phone Number")) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    if header:
        ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def make_xls(rows, header=("Name", "Email", "Phone")) -> bytes:
    import xlwt
    wb = xlwt.Workbook()
    ws = wb.add_sheet("S")
    for i, r in enumerate([list(header)] + [list(x) for x in rows]):
        for j, v in enumerate(r):
            ws.write(i, j, v)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()
