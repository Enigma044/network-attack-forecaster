import { useMemo } from 'react';
import { Area, AreaChart, CartesianGrid, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { WindowRow } from '../api';
import { fmtDateTime, fmtTime, toMs } from '../format';
import { plainLabel } from '../labels';
import { useTheme } from '../theme';

export function attackBands(windows: WindowRow[], windowMs: number): [number, number][] {
  const bands: [number, number][] = [];
  for (const w of windows) {
    if (w.is_attack !== 1) continue;
    const s = toMs(w.window_start);
    const last = bands[bands.length - 1];
    if (last && s <= last[1]) last[1] = s + windowMs;
    else bands.push([s, s + windowMs]);
  }
  return bands;
}

// Step 2 visual: connections per minute across the day, with labeled attack periods behind it.
export default function StateStrip({ windows, windowSeconds, hasLabels }: { windows: WindowRow[]; windowSeconds: number; hasLabels: boolean }) {
  const { palette: c } = useTheme();
  const windowMs = windowSeconds * 1000;
  const data = useMemo(() => windows.map(w => ({ t: toMs(w.window_start), flows: w.n_flows, label: w.top_label })), [windows]);
  const bands = useMemo(() => (hasLabels ? attackBands(windows, windowMs) : []), [windows, windowMs, hasLabels]);
  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
        <span className="flex items-center gap-1.5"><span className="inline-block h-3 w-4 rounded-sm bg-ink-2/25" />Connections per minute</span>
        {bands.length > 0 && <span className="flex items-center gap-1.5"><span className="inline-block h-3 w-3 rounded-sm bg-critical/30" />Attack under way (dataset labels)</span>}
      </div>
      <div className="h-[150px]" role="img" aria-label="Connections per minute over the day">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke={c.grid} />
            {bands.map(([a, b]) => (
              <ReferenceArea key={a} x1={a} x2={b} fill={c.critical} fillOpacity={0.18} stroke="none" ifOverflow="hidden" />
            ))}
            <XAxis dataKey="t" type="number" scale="time" domain={['dataMin', 'dataMax']} tickFormatter={fmtTime} stroke={c.axis}
              tick={{ fill: c.tick, fontSize: 11 }} tickLine={false} minTickGap={50} />
            <YAxis stroke={c.axis} tick={{ fill: c.tick, fontSize: 11 }} tickLine={false} axisLine={false} width={52}
              tickFormatter={v => (v >= 1000 ? `${Math.round(v / 1000)}k` : String(v))} />
            <Tooltip
              isAnimationActive={false}
              cursor={{ stroke: c.cursor, strokeOpacity: 0.4 }}
              content={({ active, payload }) =>
                active && payload?.length ? (
                  <div className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs shadow-lg">
                    <p className="text-muted">{fmtDateTime(payload[0].payload.t)}</p>
                    <p>
                      <span className="tabular font-semibold text-ink">{Number(payload[0].value).toLocaleString()}</span>{' '}
                      <span className="text-ink-2">connections</span>
                    </p>
                    {payload[0].payload.label && <p className="text-critical">dataset says: {plainLabel(payload[0].payload.label)}</p>}
                  </div>
                ) : null
              }
            />
            <Area type="linear" dataKey="flows" stroke={c.neutral} strokeWidth={1.5} fill={c.neutral} fillOpacity={0.14} isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
