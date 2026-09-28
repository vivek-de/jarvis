import { useEffect, useRef, useState } from "react";
import { jget, jpost, jdelete, jpatch, uploadFile, postAudioForWav } from "./api";

type Tab = "chat" | "docs" | "tasks" | "reminders" | "status";

export default function App() {
  const [tab, setTab] = useState<Tab>("chat");
  const tabs: [Tab, string][] = [
    ["chat", "Chat"], ["docs", "Documents"], ["tasks", "Tasks"],
    ["reminders", "Reminders"], ["status", "Status"],
  ];
  return (
    <div className="app">
      <header>
        <h1>JARVIS</h1>
        <nav>
          {tabs.map(([id, label]) => (
            <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>
              {label}
            </button>
          ))}
        </nav>
      </header>
      <main>
        {tab === "chat" && <ChatTab />}
        {tab === "docs" && <DocsTab />}
        {tab === "tasks" && <TasksTab />}
        {tab === "reminders" && <RemindersTab />}
        {tab === "status" && <StatusTab />}
      </main>
      <footer>Read-only over trading — JARVIS never places orders.</footer>
    </div>
  );
}

// ── Chat ──────────────────────────────────────────────────────────────────────
type ChatMsg = { role: "user" | "assistant"; text: string; meta?: string };

function ChatTab() {
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  async function send() {
    const message = input.trim();
    if (!message || busy) return;
    setInput("");
    setMsgs((m) => [...m, { role: "user", text: message }]);
    setBusy(true);
    try {
      const r: any = await jpost("/chat", { message, channel: "web" });
      const bits = [
        r.skill ? `skill: ${r.skill}` : null,
        r.tool_used ? `tool: ${r.tool_used}` : null,
        r.latency_ms != null ? `${r.latency_ms}ms` : null,
        r.cost_inr ? `₹${Number(r.cost_inr).toFixed(3)}` : null,
      ].filter(Boolean);
      setMsgs((m) => [...m, { role: "assistant", text: r.response ?? r.reply ?? "(no reply)", meta: bits.join("  ·  ") }]);
    } catch (e: any) {
      setMsgs((m) => [...m, { role: "assistant", text: `⚠️ ${e.message}` }]);
    } finally {
      setBusy(false);
    }
  }

  async function onVoice(file: File) {
    setBusy(true);
    setMsgs((m) => [...m, { role: "user", text: "🎙️ (voice message)" }]);
    try {
      const { blob, transcript, response } = await postAudioForWav("/voice/chat", file);
      setMsgs((m) => [
        ...m.slice(0, -1),
        { role: "user", text: transcript || "🎙️ (voice message)" },
        { role: "assistant", text: response || "(spoken reply)" },
      ]);
      if (audioRef.current) {
        audioRef.current.src = URL.createObjectURL(blob);
        audioRef.current.play().catch(() => {});
      }
    } catch (e: any) {
      setMsgs((m) => [...m, { role: "assistant", text: `⚠️ ${e.message}` }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="chat">
      <div className="log">
        {msgs.length === 0 && <p className="hint">Ask JARVIS anything. Try “what time is it in IST” or “list my documents”.</p>}
        {msgs.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>
            <div className="text">{m.text}</div>
            {m.meta && <div className="meta">{m.meta}</div>}
          </div>
        ))}
      </div>
      <div className="composer">
        <input
          value={input}
          placeholder="Message JARVIS…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          disabled={busy}
        />
        <button onClick={send} disabled={busy}>Send</button>
        <button className="ghost" onClick={() => fileRef.current?.click()} disabled={busy} title="Send a voice message">🎙️</button>
        <input ref={fileRef} type="file" accept="audio/*" hidden
               onChange={(e) => e.target.files?.[0] && onVoice(e.target.files[0])} />
      </div>
      <audio ref={audioRef} hidden />
    </section>
  );
}

// ── Documents ───────────────────────────────────────────────────────────────
function DocsTab() {
  const [docs, setDocs] = useState<any[]>([]);
  const [q, setQ] = useState("");
  const [answer, setAnswer] = useState<any>(null);
  const [drag, setDrag] = useState(false);
  const [err, setErr] = useState("");

  async function refresh() {
    try { setDocs((await jget<any>("/docs/list")).documents || []); }
    catch (e: any) { setErr(e.message); }
  }
  useEffect(() => { refresh(); }, []);

  async function upload(file: File) {
    setErr("");
    try { await uploadFile("/docs/upload", file); await refresh(); }
    catch (e: any) { setErr(e.message); }
  }
  async function search() {
    if (!q.trim()) return;
    try { setAnswer(await jpost("/docs/query", { query: q, top_k: 5 })); }
    catch (e: any) { setErr(e.message); }
  }
  async function del(id: string) {
    try { await jdelete(`/docs/${id}`); await refresh(); } catch (e: any) { setErr(e.message); }
  }

  return (
    <section className="docs">
      <div
        className={`dropzone ${drag ? "over" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files?.[0]; if (f) upload(f); }}
      >
        Drag &amp; drop a PDF / DOCX / XLSX / CSV / TXT / MD here to upload.
      </div>
      {err && <p className="error">{err}</p>}
      <div className="searchbar">
        <input value={q} placeholder="Ask your documents…" onChange={(e) => setQ(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && search()} />
        <button onClick={search}>Search</button>
      </div>
      {answer && (
        <div className="answer">
          <p>{answer.answer}</p>
          {answer.sources?.length ? <div className="meta">sources: {answer.sources.map((s: any) => s.filename).join(", ")}</div> : null}
        </div>
      )}
      <table>
        <thead><tr><th>File</th><th>Type</th><th>Chunks</th><th></th></tr></thead>
        <tbody>
          {docs.map((d) => (
            <tr key={d.id}>
              <td>{d.filename}</td><td>{d.doc_type}</td><td>{d.chunk_count}</td>
              <td><button className="danger" onClick={() => del(d.id)}>Delete</button></td>
            </tr>
          ))}
          {docs.length === 0 && <tr><td colSpan={4} className="hint">No documents yet.</td></tr>}
        </tbody>
      </table>
    </section>
  );
}

// ── Tasks ─────────────────────────────────────────────────────────────────────
function TasksTab() {
  const [tasks, setTasks] = useState<any[]>([]);
  const [form, setForm] = useState({ name: "", trigger_type: "cron", trigger_value: "0 9 * * *", action_type: "remind", message: "" });
  const [err, setErr] = useState("");

  async function refresh() {
    try { setTasks((await jget<any>("/tasks")).tasks || []); } catch (e: any) { setErr(e.message); }
  }
  useEffect(() => { refresh(); }, []);

  async function create() {
    setErr("");
    try {
      await jpost("/tasks", {
        name: form.name || "task", trigger_type: form.trigger_type, trigger_value: form.trigger_value,
        action_type: form.action_type, action_payload: { message: form.message || form.name },
      });
      setForm({ ...form, name: "", message: "" });
      await refresh();
    } catch (e: any) { setErr(e.message); }
  }
  async function toggle(t: any) {
    try { await jpatch(`/tasks/${t.id}`, { enabled: !t.enabled }); await refresh(); } catch (e: any) { setErr(e.message); }
  }
  async function del(id: string) {
    try { await jdelete(`/tasks/${id}`); await refresh(); } catch (e: any) { setErr(e.message); }
  }

  return (
    <section className="tasks">
      <div className="form">
        <input placeholder="name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <select value={form.trigger_type} onChange={(e) => setForm({ ...form, trigger_type: e.target.value })}>
          <option value="cron">cron</option><option value="interval">interval</option><option value="once">once</option>
        </select>
        <input placeholder="trigger value" value={form.trigger_value} onChange={(e) => setForm({ ...form, trigger_value: e.target.value })} />
        <select value={form.action_type} onChange={(e) => setForm({ ...form, action_type: e.target.value })}>
          <option value="remind">remind</option><option value="message">message</option>
        </select>
        <input placeholder="message" value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} />
        <button onClick={create}>Add</button>
      </div>
      {err && <p className="error">{err}</p>}
      <table>
        <thead><tr><th>Name</th><th>Trigger</th><th>Action</th><th>Next run</th><th>Enabled</th><th></th></tr></thead>
        <tbody>
          {tasks.map((t) => (
            <tr key={t.id}>
              <td>{(t.action_payload?.message) || t.name}</td>
              <td>{t.trigger_type}={t.trigger_value}</td>
              <td>{t.action_type}</td>
              <td>{t.next_run ? String(t.next_run).slice(0, 16) : "—"}</td>
              <td><button className={t.enabled ? "on" : "off"} onClick={() => toggle(t)}>{t.enabled ? "on" : "off"}</button></td>
              <td><button className="danger" onClick={() => del(t.id)}>Delete</button></td>
            </tr>
          ))}
          {tasks.length === 0 && <tr><td colSpan={6} className="hint">No scheduled tasks.</td></tr>}
        </tbody>
      </table>
    </section>
  );
}

// ── Reminders ──────────────────────────────────────────────────────────────────
function RemindersTab() {
  const [reminders, setReminders] = useState<any[]>([]);
  useEffect(() => {
    let stop = false;
    const poll = async () => {
      try {
        const r = await jget<any>("/reminders/pending");   // fetching also marks delivered
        if (!stop) setReminders((prev) => [...(r.reminders || []), ...prev].slice(0, 50));
      } catch { /* ignore */ }
    };
    poll();
    const id = setInterval(poll, 30000);
    return () => { stop = true; clearInterval(id); };
  }, []);
  return (
    <section className="reminders">
      <p className="hint">Pending reminders are shown as they fire (polled every 30s; marked delivered on view).</p>
      <ul>
        {reminders.map((r, i) => <li key={r.id || i}>⏰ {r.message} <span className="meta">{String(r.scheduled_for || "").slice(0, 16)}</span></li>)}
        {reminders.length === 0 && <li className="hint">Nothing pending.</li>}
      </ul>
    </section>
  );
}

// ── Status ──────────────────────────────────────────────────────────────────
function StatusTab() {
  const [h, setH] = useState<any>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let stop = false;
    const poll = async () => {
      try { const d = await jget<any>("/health"); if (!stop) { setH(d); setErr(""); } }
      catch (e: any) { if (!stop) setErr(e.message); }
    };
    poll();
    const id = setInterval(poll, 10000);
    return () => { stop = true; clearInterval(id); };
  }, []);

  const dot = (ok: boolean) => <span className={`dot ${ok ? "up" : "down"}`} />;
  const mcp = h?.mcp || {};
  return (
    <section className="status">
      {err && <p className="error">{err}</p>}
      {!h ? <p className="hint">Loading…</p> : (
        <div className="cards">
          <div className="card">{dot(h.status === "ok")} <b>Overall</b><span>{h.status}</span></div>
          <div className="card">{dot(!!h.ollama?.ok)} <b>Ollama</b><span>{h.ollama?.ok ? "up" : "down"}</span></div>
          <div className="card">{dot(!!h.db?.ok)} <b>Database</b><span>{h.db?.ok ? "up" : "down"}</span></div>
          <div className="card">{dot((h.memory?.enabled ?? false))} <b>Memory</b><span>{h.memory?.enabled ? "on" : "off"}</span></div>
          <div className="card">{dot(true)} <b>Skills</b><span>{(h.skills || []).length}</span></div>
          <div className="card">{dot(true)} <b>Spend today</b><span>₹{Number(h.spend_today_inr || 0).toFixed(2)} / {h.spend_cap_inr}</span></div>
        </div>
      )}
      {Object.keys(mcp).length > 0 && (
        <div className="mcp">
          <h3>MCP servers</h3>
          <ul>
            {Object.entries(mcp).map(([name, s]: any) => (
              <li key={name}>{dot(!s.error)} {name} — {s.tool_count ?? 0} tools {s.error ? `(${s.error})` : ""}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
