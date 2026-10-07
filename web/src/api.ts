export type Severity = "critical" | "high" | "medium" | "low";

export interface IncidentSummary {
  id: string;
  type: string;
  type_label: string;
  title: string;
  severity: Severity;
  status: "open" | "resolved";
  opened_at: string;
  opened_hour: number;
  resolved_at: string | null;
  last_at: string;
  collars: number;
  farms: string[];
  towers: string[];
  sources: string[];
  absorbed: number;
  kb: string | null;
}

export interface Overview {
  as_of: string;
  at: number;
  hours: number;
  start: string;
  kpis: {
    collars: number;
    reporting: number;
    reporting_pct: number;
    collars_in_incidents: number;
    towers: number;
    towers_online: number;
    farms: number;
    farms_affected: number;
    open_incidents: number;
    alerts_sent: number;
    signals_grouped: number;
    tickets_waiting: number;
  };
  severity_counts: Record<Severity, number>;
  series: { time: string[]; hour: number[]; reporting_pct: (number | null)[]; median_battery: (number | null)[]; open_incidents: number[] };
  farms: { id: string; name: string; region: string; terrain: string; collars: number; reporting_pct: number; open_incidents: number; worst_severity: Severity | null }[];
  top_incidents: IncidentSummary[];
}

export interface IncidentDetail extends IncidentSummary {
  evidence: { at: string; rule: string; source: string; detail: string }[];
  rules: string[];
  devices: { id: string; farm: string; tower: string; joined_at: string }[];
  notifications: { at: string; kind: string; severity: Severity; slack: { text: string; blocks: { text: { text: string } }[] } }[];
  series: { time?: string[]; reporting_pct?: (number | null)[]; median_battery?: (number | null)[]; median_gps_fix?: (number | null)[] };
  kb_article: { id: string; title: string; body: string } | null;
}

export interface DeviceDetail {
  id: string;
  farm: { id: string; name: string };
  tower: { id: string; name: string };
  firmware_now: string;
  firmware_changes: { at: string; version: string }[];
  incidents: (IncidentSummary & { joined_at: string })[];
  series: Record<string, (number | null)[]> & { time: string[] };
}

export interface DevicePick {
  id: string;
  farm: string;
  tower: string;
  incidents: string[];
}

export interface TicketRow {
  id: string;
  received_at: string;
  sender: string;
  subject: string;
  farm: string | null;
  category: string;
  article_id: string;
  escalate: boolean;
  guard_hits: number;
  mode: string;
  status: string;
}

export interface TicketDetail extends TicketRow {
  body: string;
  suggestion: {
    category: string;
    article_id: string;
    article_title: string;
    candidates: { id: string; title: string; score: number }[];
    escalate: boolean;
    escalation_reason: string;
    draft: string;
    link: { farm_id: string | null; farm_name: string | null; device_ids: string[]; tower_ids: string[]; how: string[] };
    evidence: { facts: string[] };
    related_incidents: string[];
    guard_hits: string[];
    fell_back: string[];
    llm: { cached: boolean; live: boolean; latency_s: number; error: string | null } | null;
    mode: string;
  };
  article: { id: string; title: string; body: string };
  decision: { action: string; draft: string; decided_at: string } | null;
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json() as Promise<T>;
}

export const api = {
  overview: (at?: number) => get<Overview>(`/api/overview${at === undefined ? "" : `?at=${at}`}`),
  incidents: (at: number | undefined, status: string) =>
    get<IncidentSummary[]>(`/api/incidents?status=${status}${at === undefined ? "" : `&at=${at}`}`),
  incident: (id: string) => get<IncidentDetail>(`/api/incidents/${id}`),
  devices: (q = "") => get<DevicePick[]>(`/api/devices?q=${encodeURIComponent(q)}`),
  device: (id: string) => get<DeviceDetail>(`/api/devices/${id}`),
  tickets: () => get<TicketRow[]>("/api/tickets"),
  ticket: (id: string) => get<TicketDetail>(`/api/tickets/${id}`),
  decide: async (id: string, action: string, draft: string) => {
    const r = await fetch(`/api/tickets/${id}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, draft }),
    });
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  },
};

export const fmtTime = (iso: string) =>
  new Date(iso).toLocaleString("en-NZ", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });

export const fmtDay = (iso: string) => new Date(iso).toLocaleDateString("en-NZ", { day: "numeric", month: "short" });
