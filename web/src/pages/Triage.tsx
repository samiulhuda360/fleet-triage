import { useEffect, useState } from "react";
import { api, fmtTime, type TicketDetail, type TicketRow } from "../api";
import { Loading, StatusPill, TYPE_LABEL } from "../components/ui";
import { go } from "../App";

export function Triage({ id }: { id?: string }) {
  const [rows, setRows] = useState<TicketRow[] | null>(null);
  const [filter, setFilter] = useState("waiting");
  const reload = () => api.tickets().then(setRows);
  useEffect(() => { reload(); }, []);

  const shown = (rows ?? []).filter((r) => filter === "all" || (filter === "waiting" ? r.status === "awaiting review" : r.escalate));
  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <h1>Triage queue</h1>
          <div className="sub">Support tickets linked to farms and collars, with the matching known-issue article and a draft. A person decides.</div>
        </div>
        <div className="tabs">
          {[["waiting", "Awaiting review"], ["escalate", "Suggested escalations"], ["all", "All"]].map(([k, l]) => (
            <button key={k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>{l}</button>
          ))}
        </div>
      </div>
      <div className="grid split">
        <div className="card scroll" style={{ padding: 0 }}>
          {!rows ? <Loading /> : (
            <table>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.id} className={`click ${r.id === id ? "sel" : ""}`} onClick={() => go(`triage/${r.id}`)}>
                    <td>
                      <div className="spread">
                        <b>{r.subject}</b>
                        <span className="muted" style={{ fontSize: 12, whiteSpace: "nowrap" }}>{fmtTime(r.received_at)}</span>
                      </div>
                      <div className="muted" style={{ fontSize: 12 }}>
                        {r.id} - {r.farm ?? "unknown farm"} - {r.article_id} {TYPE_LABEL[r.category] ?? r.category}
                        {r.escalate ? " - escalate" : ""}
                      </div>
                    </td>
                    <td style={{ width: 120 }}><StatusPill status={r.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div>{id ? <TicketPanel key={id} id={id} onDecided={reload} /> : <div className="card muted">Select a ticket.</div>}</div>
      </div>
    </div>
  );
}

function TicketPanel({ id, onDecided }: { id: string; onDecided: () => void }) {
  const [t, setT] = useState<TicketDetail | null>(null);
  const [draft, setDraft] = useState("");
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    api.ticket(id).then((d) => {
      setT(d);
      setDraft(d.decision?.draft ?? d.suggestion.draft);
    });
  }, [id]);

  if (!t) return <div className="card"><Loading /></div>;
  const s = t.suggestion;
  const decide = async (action: string) => {
    await api.decide(id, action, draft);
    setSaved(action);
    onDecided();
  };
  const source = s.llm ? `model (${s.llm.cached ? "replayed from cache" : s.llm.live ? "live call" : "unavailable"})` : `${s.mode} path`;

  return (
    <div className="stack">
      <div className="card">
        <div className="spread">
          <div className="muted">{t.id} - from {t.sender} - {fmtTime(t.received_at)}</div>
          <StatusPill status={saved ?? t.status} />
        </div>
        <h2 style={{ fontSize: 17, color: "var(--text)", margin: "8px 0" }}>{t.subject}</h2>
        <div className="ticket-body">{t.body}</div>
      </div>

      <div className="grid two">
        <div className="card">
          <h2>Linked</h2>
          <div><b>{s.link.farm_name ?? "No farm found"}</b> {s.link.farm_id && <span className="muted">({s.link.farm_id})</span>}</div>
          <div style={{ margin: "6px 0" }}>
            {s.link.device_ids.map((d) => <a key={d} href={`#/devices/${d}`} className="tag mono">{d}</a>)}
            {s.related_incidents.map((i) => <a key={i} href={`#/incidents/${i}`} className="tag">{i}</a>)}
          </div>
          <ul className="facts" style={{ fontSize: 12.5 }}>{s.link.how.map((h) => <li key={h}>{h}</li>)}</ul>
          <h2 style={{ marginTop: 12 }}>Device data at ticket time</h2>
          <ul className="facts" style={{ fontSize: 12.5 }}>{s.evidence.facts.slice(1).map((f) => <li key={f}>{f}</li>)}</ul>
        </div>
        <div className="card">
          <h2>Suggestion</h2>
          <div style={{ fontSize: 15, fontWeight: 600 }}>{s.article_id}: {s.article_title}</div>
          <div className="row" style={{ margin: "8px 0" }}>
            <span className="tag">{TYPE_LABEL[s.category] ?? s.category}</span>
            <span className={`pill ${s.escalate ? "sev-high" : "st-done"}`}>{s.escalate ? "escalate" : "reply only"}</span>
            <span className="muted" style={{ fontSize: 12 }}>by {source}</span>
          </div>
          <div className="muted" style={{ fontSize: 12.5 }}>{s.escalation_reason}</div>
          <h2 style={{ marginTop: 12 }}>Retrieval candidates</h2>
          <table>
            <tbody>
              {s.candidates.map((c) => (
                <tr key={c.id}><td className="mono">{c.id}</td><td>{c.title}</td><td className="num">{c.score.toFixed(2)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="spread">
          <h2>Draft reply</h2>
          <span className="muted" style={{ fontSize: 12 }}>Edit freely; nothing is sent from this screen</span>
        </div>
        {s.guard_hits.length > 0 && (
          <div className="guard" style={{ marginBottom: 8 }}>
            Guards: {s.guard_hits.join("; ")}. {s.fell_back.join("; ")}
          </div>
        )}
        {s.guard_hits.length === 0 && <div className="notice" style={{ marginBottom: 8 }}>Guards passed: no promises, and every collar, number and version in the draft is in the device data.</div>}
        <textarea value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="Draft reply" />
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn primary" onClick={() => decide("approve")}>Approve reply</button>
          <button className="btn warn" onClick={() => decide("escalate")}>Escalate</button>
          <button className="btn" onClick={() => decide("reject")}>Reject</button>
          {saved && <span className="muted">Recorded "{saved}". The reply goes out through the support desk, not from here.</span>}
        </div>
      </div>
    </div>
  );
}
