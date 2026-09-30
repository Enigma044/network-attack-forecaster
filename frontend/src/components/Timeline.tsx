import { useMemo, useState } from 'react';
import {
  CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis
} from 'recharts';
import type { Forecast, WindowRow } from '../api';
import { fmtTime, toMs } from '../format';
import { useTheme, type Palette } from '../theme';
import { attackBands } from './StateStrip';

interface Props {
  forecasts: Forecast[];
  windows: WindowRow[];
  windowSeconds: number;
  k: number;
  threshold: number;
  hasLabels: boolean;
  selectedRow: number | null;
  onSelect: (row: number) => void;
}

interface Point {
  t: number;
  row: number;
  wm: number;
  lr: number;
  early: number | null;
}

export const isEarlyWarning = (f: Forecast) => f.wm_alert && f.now_is_attack === 0 && f.actual_any === 1;

export function worryWord(p: number): string {
  if (p >= 0.8) return 'very worried';
  if (p >= 0.5) return 'worried';
  if (p >= 0.25) return 'a little uneasy';
  return 'calm';
}

function ChartTooltip({ active, payload, showBase, k, c }: { active?: boolean; payload?: { payload: Point }[]; showBase: boolean; k: number; c: Palette }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="max-w-64 rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs shadow-lg">
      <p className="mb-1 text-ink">
        At <span className="font-semibold">{fmtTime(p.t)}</span> the model was <span className="font-semibold">{worryWord(p.wm)}</span>.
      </p>
      <p className="flex items-center gap-2">
        <span className="inline-block h-0.5 w-3" style={{ background: c.wm }} />
        <span className="tabular font-semibold text-ink">{(p.wm * 100).toFixed(0)}%</span>
        <span className="text-ink-2">chance of an attack in the next {k} min</span>
      </p>
      {showBase && (
        <p className="flex items-center gap-2">
          <span className="inline-block h-0.5 w-3" style={{ background: c.lr }} />
          <span className="tabular font-semibold text-ink">{(p.lr * 100).toFixed(0)}%</span>
          <span className="text-ink-2">simple baseline</span>
        </p>
      )}
      {p.early != null && <p className="mt-1 text-good">✓ Warned early: traffic still looked normal, and an attack did follow.</p>}
      <p className="mt-1 text-muted">Click to look closer at this moment</p>
    </div>
  );
}

export default function Timeline({ forecasts, windows, windowSeconds, k, threshold, hasLabels, selectedRow, onSelect }: Props) {
  const { palette: c } = useTheme();
  const [showBase, setShowBase] = useState(false);
  const windowMs = windowSeconds * 1000;
  const data: Point[] = useMemo(
    () => forecasts.map(f => ({ t: toMs(f.input_end) + windowMs, row: f.row, wm: f.wm_any, lr: f.lr_any, early: isEarlyWarning(f) ? f.wm_any : null })),
    [forecasts, windowMs]
  );
  const bands = useMemo(() => (hasLabels ? attackBands(windows, windowMs) : []), [windows, windowMs, hasLabels]);
  const selected = forecasts.find(f => f.row === selectedRow);
  const hasEarly = data.some(d => d.early != null);
  const domain: [number, number] = [data[0]?.t ?? 0, data[data.length - 1]?.t ?? 0];

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-ink-2">
        <span className="flex items-center gap-1.5"><span className="inline-block h-0.5 w-4" style={{ background: c.wm }} />How worried the model was</span>
        {showBase && <span className="flex items-center gap-1.5"><span className="inline-block h-0.5 w-4" style={{ background: c.lr }} />Simple baseline</span>}
        <span className="flex items-center gap-1.5"><span className="inline-block w-4 border-t-2 border-dashed" style={{ borderColor: c.wm }} />Raise-a-flag line</span>
        {bands.length > 0 && <span className="flex items-center gap-1.5"><span className="inline-block h-3 w-3 rounded-sm bg-critical/30" />Attack under way (dataset labels)</span>}
        {hasEarly && <span className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: c.good }} />Warned early</span>}
        <label className="ml-auto flex cursor-pointer items-center gap-1.5 text-muted">
          <input type="checkbox" checked={showBase} onChange={e => setShowBase(e.target.checked)} className="accent-base" />
          Compare with a simple baseline
        </label>
      </div>
      <div className="h-[320px]" role="img" aria-label={`Chance of an attack in the next ${k} minutes, minute by minute`}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={data}
            margin={{ top: 8, right: 12, bottom: 4, left: 0 }}
            onClick={(state: { activeTooltipIndex?: number | string | null }) => {
              const i = Number(state?.activeTooltipIndex);
              if (Number.isFinite(i) && data[i]) onSelect(data[i].row);
            }}
            style={{ cursor: 'pointer' }}
          >
            <CartesianGrid vertical={false} stroke={c.grid} />
            {bands.map(([a, b]) => (
              <ReferenceArea key={a} x1={a} x2={b} y1={0} y2={1} fill={c.critical} fillOpacity={0.18} stroke="none" ifOverflow="hidden" />
            ))}
            <XAxis dataKey="t" type="number" scale="time" domain={domain} tickFormatter={fmtTime} stroke={c.axis}
              tick={{ fill: c.tick, fontSize: 11 }} tickLine={false} minTickGap={50} />
            <YAxis domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.75, 1]} tickFormatter={v => `${Math.round(v * 100)}%`} stroke={c.axis}
              tick={{ fill: c.tick, fontSize: 11 }} tickLine={false} axisLine={false} width={44} />
            <ReferenceLine y={threshold} stroke={c.wm} strokeDasharray="5 4" strokeOpacity={0.8} />
            {selected && <ReferenceLine x={toMs(selected.input_end) + windowMs} stroke={c.selection} strokeWidth={1.5} strokeOpacity={0.7} />}
            <Tooltip content={<ChartTooltip showBase={showBase} k={k} c={c} />} cursor={{ stroke: c.cursor, strokeOpacity: 0.4 }} isAnimationActive={false} />
            {showBase && <Line type="linear" dataKey="lr" stroke={c.lr} strokeWidth={1.5} dot={false} isAnimationActive={false} />}
            <Line type="linear" dataKey="wm" stroke={c.wm} strokeWidth={2} dot={false} activeDot={{ r: 4, stroke: c.surface, strokeWidth: 2 }} isAnimationActive={false} />
            {hasEarly && <Scatter dataKey="early" fill={c.good} shape="circle" isAnimationActive={false} />}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
