import { useEffect, useMemo, useState } from "react";
import { api, fmtTime, type DeviceDetail, type DevicePick } from "../api";
import { Legend, LineChart, type Series } from "../components/LineChart";
import { Loading, SeverityPill, StatusPill, TYPE_LABEL } from "../components/ui";
import { go } from "../App";

export function Device({ id }: { id?: string }) {
  const [q, setQ] = useState("");
  const [picks, setPicks] = useState<DevicePick[]>([]);

  useEffect(() => {
    const t = setTimeout(() => api.devices(q).then(setPicks), 200);
    return () => clearTimeout(t);
  }, [q]);

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <h1>Collar drill-down</h1>
          <div className="sub">Hourly telemetry for 30 days against the median of the same farm, with incident windows shaded.</div>
        </div>
        <input className="search" placeholder="Search collar id, e.g. 10234" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="card" style={{ padding: "10px 14px" }}>
        <div className="row" style={{ gap: 6 }}>
          <span className="muted" style={{ fontSize: 12 }}>{q ? "Matches:" : "Collars in incidents:"}</span>
          {picks.map((p) => (
            <a key={p.id} href={`#/devices/${p.id}`} className="tag" style={p.id === id ? { background: "var(--brand-soft)" } : {}}>
              {p.id} {p.incidents.length ? `- ${TYPE_LABEL[p.incidents[0]] ?? p.incidents[0]}` : ""}
            </a>
          ))}
        </div>
      </div>
      {id ? <DevicePanel id={id} /> : <div className="card muted">Pick a collar above.</div>}
    </div>
  );
}

function DevicePanel({ id }: { id: string }) {
  const [d, setD] = useState<DeviceDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setD(null);
    setErr(null);
    api.device(id).then(setD).catch(() => setErr("Collar not found"));
  }, [id]);

  const bands = useMemo(() => {
    if (!d) return [];
    const idx = (iso: string) => d.series.time.indexOf(iso);
    return d.incidents.map((i) => ({ from: Math.max(0, idx(i.joined_at)), to: i.resolved_at ? idx(i.resolved_at) : d.series.time.length - 1 }));
  }, [d]);
  const markers = useMemo(
    () => (d ? d.firmware_changes.map((c) => ({ index: d.series.time.indexOf(c.at), label: `fw ${c.version}` })) : []),
    [d],
  );

  if (err) return <div className="card">{err}</div>;
  if (!d) return <div className="card"><Loading /></div>;
  const s = d.series;
  const offline = s.tower_online.map((v) => (v === 0 ? 1 : 0));
  const towerBands = [] as { from: number; to: number }[];
  offline.forEach((v, i) => {
    if (v && (i === 0 || !offline[i - 1])) towerBands.push({ from: i, to: i });
    if (v) towerBands[towerBands.length - 1].to = i;
  });
  const allBands = [...bands, ...towerBands];

  const chart = (title: string, series: Series[], opts: { yDomain?: [number, number]; digits?: number } = {}) => (
    <div className="card">
      <div className="chart-title">
        <span>{title}</span>
        {series.length > 1 && <Legend items={series.map((x) => ({ name: x.name, color: x.color, dashed: x.dashed }))} />}
      </div>
      <LineChart times={s.time} series={series} bands={allBands} markers={markers} height={160} {...opts} />
    </div>
  );

  return (
    <div className="stack">
      <div className="card">
        <div className="spread">
          <div>
            <h2 style={{ fontSize: 18, color: "var(--text)", margin: 0 }} className="mono">{d.id}</h2>
            <div className="muted">
              {d.farm.name} ({d.farm.id}) - {d.tower.id} {d.tower.name} - firmware {d.firmware_now}
              {d.firmware_changes.length > 0 && ` (updated ${fmtTime(d.firmware_changes[0].at)})`}
            </div>
          </div>
          <div className="row">
            {d.incidents.length === 0 && <span className="pill st-done">no incidents</span>}
          </div>
        </div>
        {d.incidents.length > 0 && (
          <table style={{ marginTop: 8 }}>
            <tbody>
              {d.incidents.map((i) => (
                <tr key={i.id} className="click" onClick={() => go(`incidents/${i.id}`)}>
                  <td style={{ width: 92 }}><SeverityPill severity={i.severity} /></td>
                  <td><b>{i.title}</b><div className="muted" style={{ fontSize: 12 }}>{i.id} - joined {fmtTime(i.joined_at)}</div></td>
                  <td><StatusPill status={i.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="charts">
        {chart("Battery (%)", [
          { name: "this collar", values: s.battery, color: "var(--line-1)", unit: "%" },
          { name: "farm median", values: s.farm_battery, color: "var(--line-ref)", dashed: true, unit: "%" },
        ], { yDomain: [0, 100] })}
        {chart("Solar charge (mA)", [{ name: "solar", values: s.solar_ma, color: "var(--line-2)", unit: " mA" }], { digits: 0 })}
        {chart("Signal strength (dBm)", [
          { name: "this collar", values: s.signal_dbm, color: "var(--line-1)", unit: " dBm" },
          { name: "farm median", values: s.farm_signal_dbm, color: "var(--line-ref)", dashed: true, unit: " dBm" },
        ])}
        {chart("Temperature (C)", [
          { name: "this collar", values: s.temp_c, color: "var(--line-1)", unit: " C" },
          { name: "farm median", values: s.farm_temp_c, color: "var(--line-ref)", dashed: true, unit: " C" },
        ])}
        {chart("GPS fix rate (%)", [{ name: "fix rate", values: s.gps_fix, color: "var(--line-1)", unit: "%" }], { yDomain: [40, 100] })}
        {chart("Position error, HDOP (lower is better)", [
          { name: "this collar", values: s.hdop, color: "var(--line-1)" },
          { name: "farm median", values: s.farm_hdop, color: "var(--line-ref)", dashed: true },
        ], { digits: 2 })}
      </div>
      <div className="muted" style={{ fontSize: 12 }}>
        Shaded: incident windows and hours when the collar's tower had no heartbeat. Dashed verticals: firmware updates. Gaps: no report that hour.
      </div>
    </div>
  );
}
