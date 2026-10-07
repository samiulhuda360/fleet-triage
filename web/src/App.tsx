import { useEffect, useState } from "react";
import { Overview } from "./pages/Overview";
import { Incidents } from "./pages/Incidents";
import { Device } from "./pages/Device";
import { Triage } from "./pages/Triage";

function useHash(): string[] {
  const read = () => window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const [parts, setParts] = useState(read);
  useEffect(() => {
    const on = () => setParts(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return parts;
}

export const go = (path: string) => {
  window.location.hash = `#/${path}`;
};

const NAV = [
  { key: "", label: "Fleet overview", icon: "M3 13h4v8H3zM10 8h4v13h-4zM17 3h4v18h-4z" },
  { key: "incidents", label: "Incidents", icon: "M12 3 2 21h20L12 3zm0 6v6m0 3v.5" },
  { key: "devices", label: "Collar drill-down", icon: "M4 12a8 8 0 1 0 16 0 8 8 0 0 0-16 0zm8-4v4l3 2" },
  { key: "triage", label: "Triage queue", icon: "M4 5h16v11H8l-4 4zM8 9h8M8 12h5" },
];

export function App() {
  const parts = useHash();
  const page = parts[0] ?? "";
  const [at, setAt] = useState<number | undefined>(undefined);

  let body;
  if (page === "incidents") body = <Incidents id={parts[1]} at={at} />;
  else if (page === "devices") body = <Device id={parts[1]} />;
  else if (page === "triage") body = <Triage id={parts[1]} />;
  else body = <Overview at={at} setAt={setAt} />;

  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">
          <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden>
            <circle cx="16" cy="16" r="14" fill="#2f6f68" />
            <path d="M9 18c3-6 11-6 14 0" stroke="#f3efe6" strokeWidth="3" fill="none" strokeLinecap="round" />
            <circle cx="16" cy="21" r="2" fill="#f3efe6" />
          </svg>
          <div>
            Fleet Triage
            <small>Acme Pasture collars</small>
          </div>
        </div>
        <nav className="nav">
          {NAV.map((n) => (
            <a key={n.key} href={`#/${n.key}`} className={page === n.key ? "active" : ""}>
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
                <path d={n.icon} strokeLinejoin="round" strokeLinecap="round" />
              </svg>
              {n.label}
            </a>
          ))}
        </nav>
        <div className="foot">Simulated fleet, seed 7. Every farm and person is fictional.</div>
      </aside>
      <main className="main">{body}</main>
    </div>
  );
}
