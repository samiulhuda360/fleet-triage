import { useEffect, useMemo, useRef, useState } from "react";
import { fmtDay, fmtTime } from "../api";

export interface Series {
  name: string;
  values: (number | null)[];
  color: string;
  dashed?: boolean;
  unit?: string;
}

interface Band {
  from: number; // index
  to: number;
  label?: string;
}

interface Props {
  times: string[];
  series: Series[];
  height?: number;
  yDomain?: [number, number];
  bands?: Band[];
  markers?: { index: number; label: string }[];
  cursor?: number; // index of a vertical "now" line
  digits?: number;
}

const PAD = { l: 40, r: 12, t: 10, b: 22 };

/** A small responsive SVG line chart with a hover crosshair and tooltip. Gaps (null) break the line. */
export function LineChart({ times, series, height = 170, yDomain, bands = [], markers = [], cursor, digits = 1 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const n = times.length;
  const [y0, y1] = useMemo(() => {
    if (yDomain) return yDomain;
    let lo = Infinity;
    let hi = -Infinity;
    for (const s of series) for (const v of s.values) if (v !== null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    if (!isFinite(lo)) return [0, 1];
    const pad = (hi - lo) * 0.08 || 1;
    return [lo - pad, hi + pad];
  }, [series, yDomain]);

  const iw = Math.max(10, width - PAD.l - PAD.r);
  const ih = height - PAD.t - PAD.b;
  const x = (i: number) => PAD.l + (n <= 1 ? 0 : (i / (n - 1)) * iw);
  const y = (v: number) => PAD.t + ih - ((v - y0) / (y1 - y0 || 1)) * ih;

  const paths = series.map((s) => {
    let d = "";
    let pen = false;
    s.values.forEach((v, i) => {
      if (v === null) { pen = false; return; }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  });

  const ticks = 4;
  const yTicks = Array.from({ length: ticks + 1 }, (_, k) => y0 + ((y1 - y0) * k) / ticks);
  const dayTicks: number[] = [];
  const step = Math.max(1, Math.round(n / Math.max(2, Math.floor(iw / 90))));
  for (let i = 0; i < n; i += step) dayTicks.push(i);

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - box.left - PAD.l;
    const i = Math.round((px / iw) * (n - 1));
    setHover(i >= 0 && i < n ? i : null);
  };

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <svg width={width} height={height} onMouseMove={onMove} onMouseLeave={() => setHover(null)} role="img">
        {bands.map((b, k) => (
          <rect key={k} x={x(b.from)} y={PAD.t} width={Math.max(2, x(b.to) - x(b.from))} height={ih} fill="var(--band)" />
        ))}
        {yTicks.map((v, k) => (
          <g key={k}>
            <line x1={PAD.l} x2={PAD.l + iw} y1={y(v)} y2={y(v)} stroke="#ebe8df" />
            <text x={PAD.l - 6} y={y(v) + 4} fontSize="10.5" textAnchor="end" fill="#7a857f">
              {Math.abs(y1 - y0) < 5 ? v.toFixed(1) : Math.round(v)}
            </text>
          </g>
        ))}
        {dayTicks.map((i) => (
          <text key={i} x={x(i)} y={height - 6} fontSize="10.5" textAnchor="middle" fill="#7a857f">
            {fmtDay(times[i])}
          </text>
        ))}
        {markers.map((m, k) => (
          <g key={k}>
            <line x1={x(m.index)} x2={x(m.index)} y1={PAD.t} y2={PAD.t + ih} stroke="#8a6d3b" strokeDasharray="3 3" />
            <text x={x(m.index) + 4} y={PAD.t + 10} fontSize="10.5" fill="#8a6d3b">{m.label}</text>
          </g>
        ))}
        {paths.map((d, k) => (
          <path key={k} d={d} fill="none" stroke={series[k].color} strokeWidth={series[k].dashed ? 1.5 : 2}
            strokeDasharray={series[k].dashed ? "4 3" : undefined} strokeLinejoin="round" />
        ))}
        {cursor !== undefined && (
          <line x1={x(cursor)} x2={x(cursor)} y1={PAD.t} y2={PAD.t + ih} stroke="#13302c" strokeWidth={1.5} />
        )}
        {hover !== null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={PAD.t + ih} stroke="#13302c" strokeOpacity={0.35} />
            {series.map((s, k) => s.values[hover] !== null && (
              <circle key={k} cx={x(hover)} cy={y(s.values[hover] as number)} r={4} fill={s.color} stroke="#fff" strokeWidth={2} />
            ))}
          </g>
        )}
      </svg>
      {hover !== null && (
        <div className="tip" style={{ left: x(hover), top: PAD.t + 4 }}>
          <div style={{ opacity: 0.8 }}>{fmtTime(times[hover])}</div>
          {series.map((s) => (
            <div key={s.name}>
              {s.name}: <b>{s.values[hover] === null ? "no report" : `${(s.values[hover] as number).toFixed(digits)}${s.unit ?? ""}`}</b>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function Legend({ items }: { items: { name: string; color: string; dashed?: boolean }[] }) {
  return (
    <div className="legend">
      {items.map((i) => (
        <span key={i.name}>
          <i style={{ background: i.dashed ? `repeating-linear-gradient(90deg, ${i.color} 0 4px, transparent 4px 7px)` : i.color }} />
          {i.name}
        </span>
      ))}
    </div>
  );
}
