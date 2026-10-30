import { useCallback, useEffect, useRef, useState } from "react";
import { downloadUrl, history, send, type Card, type Msg, type Progress } from "./api";

const newSid = () => crypto.randomUUID().replace(/-/g, "");
const ACCEPT = ".xlsx,.xls,.csv,.jpg,.jpeg,.png,.webp,.pdf";
const EMPTY: Progress = { phase: "idle", total: 0, index: 0, name: "", done: 0 };

const rich = (t: string) =>
  t.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((p, i) =>
    p.startsWith("**") ? <strong key={i}>{p.slice(2, -2)}</strong> : p.startsWith("`") ? <code key={i}>{p.slice(1, -1)}</code> : p);

function CardView({ c }: { c: Card }) {
  if (c.kind === "fields") return (
    <div className="card kvwrap">{c.title && <div className="cap">{c.title}</div>}
      <dl className="kv">{c.rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd className={v === "not provided" ? "nf" : ""}>{v}</dd></div>)}</dl></div>);
  if (c.kind === "table") return (
    <table className="card"><thead><tr>{c.head.map((h) => <th key={h}>{h}</th>)}</tr></thead>
      <tbody>{c.rows.map((r, i) => <tr key={i}>{r.map((x, j) => <td key={j}>{x}</td>)}</tr>)}</tbody></table>);
  if (c.kind === "skipped") return (
    <div className="card list"><div className="cap">Skipped rows</div>{c.rows.map((r, i) => <div key={i} className="li"><b>{r[1]}</b><span>{r[2]}</span></div>)}</div>);
  if (c.kind === "report") return (
    <div className="card list">{c.rows.map((r) => (
      <div key={r.n} className="li col">
        <div className="row"><b>{r.n}. {r.name || "(unnamed)"} {r.id && <span className="muted">{r.id}</span>}</b><span className={`pill ${r.result.toLowerCase()}`}>{r.result.toLowerCase()}</span></div>
        {r.issues.map((x, i) => <div key={i} className="issue">✗ {x}</div>)}
        {r.warnings.map((x, i) => <div key={i} className="warn">! {x}</div>)}
      </div>))}</div>);
  return <div className="dl"><a href={downloadUrl("xlsx")} className="btn">Download master sheet (.xlsx)</a><a href={downloadUrl("xls")} className="btn ghost">.xls</a></div>;
}

export default function App() {
  const [sid, setSid] = useState(() => localStorage.getItem("sid") ?? newSid());
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [prog, setProg] = useState<Progress>(EMPTY);
  const [chips, setChips] = useState<string[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [drag, setDrag] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const pick = useRef<HTMLInputElement>(null);

  useEffect(() => {
    localStorage.setItem("sid", sid);
    history(sid).then((r) => { setMsgs(r.messages); setProg(r.progress); setChips(r.chips); setErr(""); }).catch((e: Error) => setErr(e.message));
  }, [sid]);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs, busy]);

  const submit = useCallback(async (t: string) => {
    if (busy || (!t.trim() && !files.length)) return;
    const sending = files;
    setBusy(true); setErr(""); setFiles([]); setText("");
    setMsgs((m) => [...m, { role: "user", text: t, files: sending.map((f) => f.name) }]);
    try {
      const r = await send(sid, t, sending);
      setMsgs((m) => [...m, ...r.messages]);
      setProg(r.progress); setChips(r.chips);
    } catch (e) { setErr((e as Error).message); setFiles(sending); }
    finally { setBusy(false); }
  }, [busy, files, sid]);

  const label = prog.phase === "collecting" ? `Employee ${prog.index} of ${prog.total} · ${prog.name}` : prog.phase === "review" ? `${prog.done} of ${prog.total} saved · ready to confirm` : "";

  return (
    <div className="app" onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={(e) => { if (e.target === e.currentTarget) setDrag(false); }}
      onDrop={(e) => { e.preventDefault(); setDrag(false); setFiles((f) => [...f, ...Array.from(e.dataTransfer.files)]); }}>
      <header>
        <h1>Employee onboarding</h1>
        {label && <span className="status">{label}</span>}
        <span className="sp" />
        <a className="link" href={downloadUrl("xlsx")}>Master sheet</a>
        <button className="link" onClick={() => { setMsgs([]); setProg(EMPTY); setChips([]); setSid(newSid()); }}>New chat</button>
      </header>
      <main aria-live="polite">
        {msgs.length === 0 && !err && (
          <div className="empty"><h2>Upload your employee sheet</h2>
            <p>An Excel or CSV file with three columns: <b>name</b>, <b>email</b>, <b>phone</b>. Then send 4 images per person, one at a time: <b>PAN, Aadhaar, cancelled cheque, any other</b>. Any picture works for now; details are placeholders. You can also just talk to me: “show Asha”, “change her phone to…”, “how many are left?”.</p>
            <button className="chip" onClick={() => void submit("help")}>How does this work?</button></div>)}
        {msgs.map((m, i) => (
          <div key={i} className={`m ${m.role}`}>
            {m.files?.map((f, k) => <div key={`${f}-${k}`} className="file">📎 {f}</div>)}
            {m.text && <div className="bubble">{m.text.split("\n").map((l, j) => <p key={j}>{rich(l)}</p>)}</div>}
            {m.card && <CardView c={m.card} />}
          </div>))}
        {busy && <div className="m assistant"><div className="bubble typing"><i /><i /><i /></div></div>}
        {!busy && chips.length > 0 && <div className="chips">{chips.map((c) => <button key={c} className="chip" onClick={() => void submit(c)}>{c}</button>)}</div>}
        {err && <p className="error" role="alert">{err}</p>}
        <div ref={end} />
      </main>
      <footer>
        {files.length > 0 && <div className="files">{files.map((f, i) => <span key={i} className="fchip">{f.name}<button aria-label={`Remove ${f.name}`} onClick={() => setFiles(files.filter((_, j) => j !== i))}>×</button></span>)}</div>}
        <div className="bar">
          <button className="clip" aria-label="Attach files" onClick={() => pick.current?.click()} disabled={busy}>＋</button>
          <input ref={pick} type="file" hidden multiple accept={ACCEPT} onChange={(e) => { setFiles([...files, ...Array.from(e.target.files ?? [])]); e.target.value = ""; }} />
          <input value={text} placeholder="Attach a sheet or any image, or type a message" aria-label="Message" disabled={busy}
            onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void submit(text); }} />
          <button className="go" onClick={() => void submit(text)} disabled={busy || (!text.trim() && !files.length)}>Send</button>
        </div>
      </footer>
      {drag && <div className="drop">Drop files to attach</div>}
    </div>
  );
}
