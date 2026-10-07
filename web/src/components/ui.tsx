import type { ReactNode } from "react";
import type { Severity } from "../api";

const SEV_ICON: Record<Severity, string> = { critical: "!!", high: "!", medium: "~", low: "-" };

export function SeverityPill({ severity }: { severity: Severity }) {
  return (
    <span className={`pill sev-${severity}`} title={`Severity: ${severity}`}>
      <span aria-hidden>{SEV_ICON[severity]}</span>
      {severity}
    </span>
  );
}

export function StatusPill({ status }: { status: string }) {
  const cls =
    status === "open" ? "st-open" : status === "resolved" ? "st-resolved" : status === "awaiting review" ? "st-review" : "st-done";
  return <span className={`pill ${cls}`}>{status}</span>;
}

export function Kpi({ label, value, unit, note }: { label: string; value: ReactNode; unit?: string; note?: ReactNode }) {
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className="value">
        {value}
        {unit && <small> {unit}</small>}
      </div>
      {note && <div className="note">{note}</div>}
    </div>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return <div className="muted" style={{ padding: 20 }}>{what}...</div>;
}

export const TYPE_LABEL: Record<string, string> = {
  tower_outage: "Tower outage",
  firmware_bad: "Firmware regression",
  battery_fade: "Battery fade",
  water_ingress: "Water ingress",
  gps_drift: "GPS drift",
  device_offline: "Collar offline",
  tower_power_low: "Tower power low",
  anomaly: "Unexplained anomaly",
  poor_coverage: "Poor coverage",
  weather_low_charge: "Weather, low charge",
  collar_fit: "Collar fit",
  account_access: "Account access",
  billing: "Billing",
  setup_howto: "How-to",
  alert_settings: "Alert settings",
};
