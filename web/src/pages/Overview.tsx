import { useEffect, useState } from "react";
import { api, fmtTime, type Overview as O, type Severity } from "../api";
import { LineChart } from "../components/LineChart";
import { Kpi, Loading, SeverityPill, StatusPill } from "../components/ui";
import { go } from "../App";

export function Overview({ at, setAt }: { at?: number; setAt: (h: number | undefined) => void }) {
  const [data, setData] = useState<O | null>(null);
  const [slider, setSlider] = useState<number | undefined>(at);

  useEffect(() => {
    const t = setTimeout(() => setAt(slider), 150);
    return () => clearTimeout(t);
  }, [slider, setAt]);

  useEffect(() => {
    let live = true;
    api.overview(at).then((d) => live && setData(d));
    return () => { live = false; };
  }, [at]);

  if (!data) return <Loading what="Replaying 30 days of fleet telemetry" />;
  const k = data.kpis;
  const cursor = Math.round(data.at / 3);
  const sevs: Severity[] = ["critical", "high", "medium", "low"];

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <h1>Fleet health</h1>
          <div className="sub">
            {k.collars.toLocaleString()} GPS collars on {k.farms} farms, {k.towers} solar base towers. As of {fmtTime(data.as_of)}.
          </div>
        </div>
        <div className="replay">
          <span className="muted">Replay</span>
          <input
            type="range"
            min={24}
            max={data.hours - 1}
            step={3}
            value={slider ?? data.hours - 1}
            onChange={(e) => setSlider(Number(e.target.value))}
            aria-label="Replay the fleet to an earlier hour"
          />
          <span className="when">{fmtTime(data.as_of)}</span>
          <button className="btn ghost" onClick={() => setSlider(undefined)}>Now</button>
        </div>
      </div>

      <div className="grid kpis">
        <Kpi label="Collars reporting" value={k.reporting.toLocaleString()} unit={`/ ${k.collars.toLocaleString()}`} note={`${k.reporting_pct}% in the last 3 hours`} />
        <Kpi label="Open incidents" value={k.open_incidents} note={sevs.filter((s) => data.severity_counts[s]).map((s) => `${data.severity_counts[s]} ${s}`).join(", ") || "none"} />
        <Kpi label="Collars in incidents" value={k.collars_in_incidents} note={`${k.farms_affected} of ${k.farms} farms affected`} />
        <Kpi label="Towers online" value={k.towers_online} unit={`/ ${k.towers}`} note={k.towers_online < k.towers ? `${k.towers - k.towers_online} without heartbeat` : "all heartbeats in"} />
        <Kpi label="Alerts sent" value={k.alerts_sent} note={`from ${k.signals_grouped.toLocaleString()} detector signals`} />
        <Kpi label="Tickets waiting" value={k.tickets_waiting} note="suggestions awaiting a person" />
      </div>

      <div className="grid two">
        <div className="card">
          <h2>Collars reporting each hour (%)</h2>
          <LineChart
            times={data.series.time}
            series={[{ name: "Reporting", values: data.series.reporting_pct, color: "var(--line-1)", unit: "%" }]}
            cursor={cursor}
            height={180}
          />
          <h2 style={{ marginTop: 12 }}>Median collar battery (%)</h2>
          <LineChart
            times={data.series.time}
            series={[{ name: "Median battery", values: data.series.median_battery, color: "var(--line-2)", unit: "%" }]}
            cursor={cursor}
            height={150}
          />
        </div>
        <div className="card">
          <div className="spread">
            <h2>Most severe open incidents</h2>
            <a href="#/incidents">All incidents</a>
          </div>
          <table>
            <tbody>
              {data.top_incidents.map((i) => (
                <tr key={i.id} className="click" onClick={() => go(`incidents/${i.id}`)}>
                  <td style={{ width: 92 }}><SeverityPill severity={i.severity} /></td>
                  <td>
                    <div style={{ fontWeight: 600 }}>{i.title}</div>
                    <div className="muted" style={{ fontSize: 12 }}>
                      {i.id} - opened {fmtTime(i.opened_at)} - {i.collars} collars, {i.farms.length} farm{i.farms.length === 1 ? "" : "s"}
                    </div>
                  </td>
                  <td><StatusPill status={i.status} /></td>
                </tr>
              ))}
              {!data.top_incidents.length && <tr><td className="muted">No open incidents at this hour.</td></tr>}
            </tbody>
          </table>
          <h2 style={{ marginTop: 16 }}>Open incidents over time</h2>
          <LineChart
            times={data.series.time}
            series={[{ name: "Open incidents", values: data.series.open_incidents, color: "var(--sev-high)" }]}
            cursor={cursor}
            height={120}
            digits={0}
            yDomain={[0, Math.max(5, ...data.series.open_incidents) + 2]}
          />
        </div>
      </div>

      <div className="card">
        <div className="spread">
          <h2>Farms</h2>
          <span className="muted" style={{ fontSize: 12 }}>Left edge shows the worst open incident; percentage is collars reporting</span>
        </div>
        <div className="farmgrid">
          {data.farms.map((f) => (
            <div key={f.id} className={`farm ${f.worst_severity ?? "none"}`} title={`${f.region}, ${f.terrain} country`}>
              <b>{f.name}</b>
              <span>{f.id} - {f.collars} collars</span>
              <div className="row" style={{ marginTop: 4, gap: 6 }}>
                <div className="bar" style={{ flex: 1 }}><div style={{ width: `${f.reporting_pct}%` }} /></div>
                <span style={{ fontVariantNumeric: "tabular-nums" }}>{f.reporting_pct.toFixed(0)}%</span>
              </div>
              {f.open_incidents > 0 && <span>{f.open_incidents} open</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
