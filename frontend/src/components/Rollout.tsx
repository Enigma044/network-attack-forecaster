import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { ForecastDetail } from '../api';
import { useTheme } from '../theme';

// Step 4 detail: the world model's imagined next K minutes for one moment.
export default function Rollout({ detail, showBaseline }: { detail: ForecastDetail; showBaseline: boolean }) {
  const { palette: c } = useTheme();
  const r = detail.rollout;
  const data = r.world_model.map((p, i) => ({
    step: `+${i + 1} min`,
    p,
    band: [r.q10[i], r.q90[i]] as [number, number],
    lr: r.baseline[i],
    actual: r.actual[i]
  }));
  const known = data.some(d => d.actual != null);
  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
        <span className="flex items-center gap-1.5"><span className="inline-block h-0.5 w-4" style={{ background: c.wm }} />Typical imagined future</span>
        <span className="flex items-center gap-1.5"><span className="inline-block h-3 w-4 rounded-sm bg-lstm/25" />Where most of the 32 futures landed</span>
        {showBaseline && <span className="flex items-center gap-1.5"><span className="inline-block w-4 border-t-2 border-dashed" style={{ borderColor: c.lr }} />Simple baseline</span>}
      </div>
      <div className="h-[200px]" role="img" aria-label="Imagined chance of an attack for each of the next minutes">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 6, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke={c.grid} />
            <XAxis dataKey="step" stroke={c.axis} tick={{ fill: c.tick, fontSize: 11 }} tickLine={false} />
            <YAxis domain={[0, 1]} ticks={[0, 0.5, 1]} tickFormatter={v => `${Math.round(v * 100)}%`} stroke={c.axis}
              tick={{ fill: c.tick, fontSize: 11 }} tickLine={false} axisLine={false} width={44} />
            <Tooltip
              isAnimationActive={false}
              cursor={{ stroke: c.cursor, strokeOpacity: 0.4 }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const d = payload[0].payload as (typeof data)[number];
                return (
                  <div className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs shadow-lg">
                    <p className="text-muted">{d.step} from now</p>
                    <p><span className="tabular font-semibold text-ink">{(d.p * 100).toFixed(0)}%</span> <span className="text-ink-2">chance of attack traffic</span></p>
                    <p className="text-muted">most futures between {(d.band[0] * 100).toFixed(0)}% and {(d.band[1] * 100).toFixed(0)}%</p>
                    {showBaseline && <p><span className="tabular font-semibold text-ink">{(d.lr * 100).toFixed(0)}%</span> <span className="text-ink-2">baseline</span></p>}
                    {d.actual != null && <p className={d.actual === 1 ? 'text-critical' : 'text-ink-2'}>In reality: {d.actual === 1 ? 'attack traffic' : 'normal traffic'}</p>}
                  </div>
                );
              }}
            />
            <Area type="monotone" dataKey="band" stroke="none" fill={c.wm} fillOpacity={0.2} isAnimationActive={false} />
            {showBaseline && <Line type="linear" dataKey="lr" stroke={c.lr} strokeWidth={1.5} strokeDasharray="5 4" dot={false} isAnimationActive={false} />}
            <Line type="linear" dataKey="p" stroke={c.wm} strokeWidth={2} dot={{ r: 3, fill: c.wm, stroke: c.surface, strokeWidth: 1.5 }} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      {known && (
        <div className="mt-2">
          <p className="mb-1 text-[11px] text-muted">What actually happened next (dataset labels)</p>
          <div className="grid gap-1 pl-11 pr-3" style={{ gridTemplateColumns: `repeat(${data.length}, minmax(0, 1fr))` }}>
            {data.map(d => (
              <span
                key={d.step}
                title={`${d.step}: ${d.actual == null ? 'past the end of the file' : d.actual === 1 ? 'attack traffic' : 'normal traffic'}`}
                className={`h-3 rounded-sm ${d.actual == null ? 'border border-dashed border-line-strong' : d.actual === 1 ? 'bg-critical' : 'bg-wash-strong'}`}
              />
            ))}
          </div>
          <div className="mt-1 flex flex-wrap gap-3 pl-11 text-[11px] text-muted">
            <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-sm bg-critical" />attack</span>
            <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-sm bg-wash-strong" />normal</span>
            <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-sm border border-dashed border-line-strong" />past the end of the file</span>
          </div>
        </div>
      )}
    </div>
  );
}
