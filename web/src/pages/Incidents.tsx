import { useEffect, useState } from "react";
import { api, fmtTime, type IncidentDetail, type IncidentSummary } from "../api";
import { Legend, LineChart } from "../components/LineChart";
import { Loading, SeverityPill, StatusPill } from "../components/ui";
import { go } from "../App";

export function Incidents({ id, at }: { id?: string; at?: number }) {
  const [status, setStatus] = useState("open");
  const [rows, setRows] = useState<IncidentSummary[] | null>(null);

  useEffect(() => {
    api.incidents(at, status).then(setRows);
  }, [at, status]);

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <h1>Incidents</h1>
          <div className="sub">Detector signals grouped by tower, firmware version or farm, with severity and impact.</div>
        </div>
        <div className="tabs">
          {["open", "resolved", "all"].map((s) => (
            <button key={s} className={status === s ? "on" : ""} onClick={() => setStatus(s)}>{s}</button>
          ))}
        </div>
      </div>
      <div className="grid split">
        <div className="card scroll" style={{ padding: 0 }}>
          {!rows ? <Loading /> : (
            <table>
              <thead>
                <tr><th>Severity</th><th>Incident</th><th className="num">Collars</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className={`click ${r.id === id ? "sel" : ""}`} onClick={() => go(`incidents/${r.id}`)}>
                    <td><SeverityPill severity={r.severity} /></td>
                    <td>
                      <div style={{ fontWeight: 600 }}>{r.title}</div>
                      <div className="muted" style={{ fontSize: 12 }}>
                        {r.id} - {r.type_label} - {fmtTime(r.opened_at)} - {r.status}
                      </div>
                    </td>
                    <td className="num">{r.collars}</td>
                  </tr>
                ))}
                {!rows.length && <tr><td colSpan={3} className="muted">Nothing here.</td></tr>}
              </tbody>
            </table>
          )}
        </div>
        <div>{id ? <IncidentPanel id={id} /> : <div className="card muted">Select an incident to see its evidence, impact and alerts.</div>}</div>
      </div>
    </div>
  );
}

function IncidentPanel({ id }: { id: string }) {
  const [d, setD] = useState<IncidentDetail | null>(null);
  useEffect(() => {
    setD(null);
    api.incident(id).then(setD);
  }, [id]);
  if (!d) return <div className="card"><Loading /></div>;
  const s = d.series;
  return (
    <div className="stack">
      <div className="card">
        <div className="row"><SeverityPill severity={d.severity} /><StatusPill status={d.status} /><span className="muted">{d.id} - {d.type_label}</span></div>
        <h2 style={{ fontSize: 18, color: "var(--text)", margin: "10px 0 6px" }}>{d.title}</h2>
        <div className="row" style={{ gap: 24, margin: "8px 0 4px" }}>
          <div><div className="muted" style={{ fontSize: 12 }}>Collars</div><b style={{ fontSize: 20 }}>{d.collars}</b></div>
          <div><div className="muted" style={{ fontSize: 12 }}>Farms</div><b style={{ fontSize: 20 }}>{d.farms.length}</b></div>
          <div><div className="muted" style={{ fontSize: 12 }}>Opened</div><b>{fmtTime(d.opened_at)}</b></div>
          <div><div className="muted" style={{ fontSize: 12 }}>{d.resolved_at ? "Resolved" : "Last signal"}</div><b>{fmtTime(d.resolved_at ?? d.last_at)}</b></div>
          <div><div className="muted" style={{ fontSize: 12 }}>Signals merged in</div><b>{d.absorbed.toLocaleString()}</b></div>
        </div>
        <div style={{ marginTop: 6 }}>
          {d.farms.slice(0, 8).map((f) => <span key={f} className="tag">{f}</span>)}
          {d.towers.map((t) => <span key={t} className="tag">{t}</span>)}
          {d.sources.map((t) => <span key={t} className="tag">source: {t}</span>)}
        </div>
      </div>

      {s.time && (
        <div className="card">
          <div className="spread"><h2>Affected collars around the incident</h2>
            <Legend items={[{ name: "reporting %", color: "var(--line-1)" }, { name: "median battery %", color: "var(--line-2)" }, { name: "median GPS fix %", color: "var(--line-ref)", dashed: true }]} />
          </div>
          <LineChart
            times={s.time}
            series={[
              { name: "Reporting", values: s.reporting_pct ?? [], color: "var(--line-1)", unit: "%" },
              { name: "Median battery", values: s.median_battery ?? [], color: "var(--line-2)", unit: "%" },
              { name: "Median GPS fix", values: s.median_gps_fix ?? [], color: "var(--line-ref)", dashed: true, unit: "%" },
            ]}
            yDomain={[0, 102]}
            markers={[{ index: Math.min(72, d.opened_hour), label: "opened" }]}
            height={200}
          />
        </div>
      )}

      <div className="card">
        <h2>Evidence</h2>
        <ul className="facts">
          {d.evidence.map((e, k) => (
            <li key={k}><span className="mono">{e.rule}</span> {fmtTime(e.at)}: {e.detail}</li>
          ))}
        </ul>
      </div>

      <div className="grid two">
        <div className="card">
          <h2>Alerts sent ({d.notifications.length})</h2>
          <div className="stack">
            {d.notifications.map((n, k) => (
              <div key={k}>
                <div className="muted" style={{ fontSize: 12 }}>{fmtTime(n.at)} - {n.kind}</div>
                <div className="slack">{n.slack.text}{"\n"}{n.slack.blocks[1]?.text.text}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="card">
          <h2>Collars ({d.collars})</h2>
          <div className="scroll" style={{ maxHeight: 300 }}>
            <table>
              <tbody>
                {d.devices.slice(0, 120).map((v) => (
                  <tr key={v.id} className="click" onClick={() => go(`devices/${v.id}`)}>
                    <td className="mono">{v.id}</td><td>{v.farm}</td><td className="muted">{fmtTime(v.joined_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {d.kb_article && (
        <div className="card">
          <h2>Known issue {d.kb_article.id}: {d.kb_article.title}</h2>
          <div style={{ whiteSpace: "pre-wrap", color: "var(--text-2)", fontSize: 13 }}>{d.kb_article.body.replace(/## /g, "")}</div>
        </div>
      )}
    </div>
  );
}
