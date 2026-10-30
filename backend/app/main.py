from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .chat import Chat
from .config import get_settings
from .schema import TEMPLATE
from .sessions import Sessions
from .store import MasterStore

cfg = get_settings()
store = MasterStore(cfg.data_dir)
sessions = Sessions(cfg.data_dir)
chat = Chat(store, sessions, cfg)


app = FastAPI(title="Employee onboarding", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=cfg.cors_list, allow_methods=["*"], allow_headers=["*"])


def _sid(sid: str) -> str:
    if not sessions.valid(sid):
        raise HTTPException(400, "Invalid session id")
    return sid


@app.get("/api/health")
def health():
    return {"ok": True, "employees": len(store.all())}


@app.get("/api/schema")
def schema():
    """The standard employee master record."""
    return TEMPLATE


@app.get("/api/chat/{sid}")
def history(sid: str):
    return chat.history(_sid(sid))


@app.post("/api/chat")
def post_chat(session_id: str = Form(...), text: str = Form(""), files: list[UploadFile] = File(default=[])):
    sid = _sid(session_id)
    cap = cfg.max_upload_mb * 1024 * 1024
    if len(files) > 10:
        raise HTTPException(400, "At most 10 files per message")
    blobs = []
    for f in files:
        data = f.file.read(cap + 1)
        if len(data) > cap:
            raise HTTPException(413, f"{f.filename} is larger than {cfg.max_upload_mb} MB")
        blobs.append((f.filename or "file", data))
    return chat.handle(sid, text, blobs)


@app.get("/api/master")
def master():
    """The master JSON list."""
    return {"employees": store.all()}


@app.get("/api/master/download")
def download(format: str = "xlsx"):
    if format not in ("xlsx", "xls"):
        raise HTTPException(400, "format must be xlsx or xls")
    path = store.xlsx_path if format == "xlsx" else store.xls_path
    if not path.exists():
        raise HTTPException(404, "No verified employees yet. Verify and confirm a batch first.")
    media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if format == "xlsx" else "application/vnd.ms-excel"
    return FileResponse(path, media_type=media, filename=f"master_employees.{format}")
