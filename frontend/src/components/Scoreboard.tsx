import { useState } from 'react';
import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { BinaryMetrics, MetricBlock, Metrics } from '../api';
import { useTheme, type Palette } from '../theme';
import Term from './Term';

const NAMES = { world_model: 'Our world model', logistic_regression: 'Simple baseline', persistence_reference: '“Same as now” guess*' } as const;
type Key = keyof typeof NAMES;
const colorOf = (c: Palette, k: Key) => (k === 'world_model' ? c.wm : k === 'logistic_regression' ? c.lr : c.persist);

/** "About 1 in 4" style phrasing for a fraction. */
export function inWords(p: number): string {
  if (p <= 0) return 'none';
  if (p >= 0.995) return 'all';
  const candidates = [2, 3, 4, 5, 10, 20, 50, 100];
  for (const d of candidates) {
    const n = Math.round(p * d);
    if (n >= 1 && Math.abs(n / d - p) < 0.03) return `about ${n} in ${d}`;
  }
  return `${Math.round(p * 100)}%`;
}

function Row({ name, color, m }: { name: string; color: string; m: BinaryMetrics }) {
  return (
    <tr className="border-b border-line">
      <td className="py-2 pr-3 text-ink">
        <span className="flex items-center gap-2">
          <span className="inline-block h-3 w-3 rounded-sm" style={{ background: color }} />
          {name}
        </span>
      </td>
      {[m.precision, m.recall, m.f1, m.false_positive_rate].map((v, i) => (
        <td key={i} className="px-2 py-2 text-right text-ink">{v.toFixed(3)}</td>
      ))}
      <td className="px-2 py-2 text-right text-ink-2">{m.average_precision?.toFixed(3) ?? '–'}</td>
    </tr>
  );
}

export function MetricTable({ block }: { block: MetricBlock }) {
  const { palette: c } = useTheme();
  return (
    <div className="overflow-x-auto">
      <table className="tabular w-full min-w-[520px] text-sm">
        <thead>
          <tr className="border-b border-line text-left text-xs text-muted">
            <th className="py-2 pr-3 font-medium">Model</th>
            <th className="px-2 py-2 text-right font-medium"><Term k="precision">Precision</Term></th>
            <th className="px-2 py-2 text-right font-medium"><Term k="recall">Recall</Term></th>
            <th className="px-2 py-2 text-right font-medium"><Term k="f1">F1</Term></th>
            <th className="px-2 py-2 text-right font-medium"><Term k="fpr">FPR</Term></th>
            <th className="px-2 py-2 text-right font-medium">AP</th>
          </tr>
        </thead>
        <tbody>
          {(Object.keys(NAMES) as Key[]).map(k => {
            const m = block[k];
            return m ? <Row key={k} name={NAMES[k]} color={colorOf(c, k)} m={m} /> : null;
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function Scoreboard({ metrics, k, synthetic, testDays }: { metrics: Metrics; k: number; synthetic: boolean; testDays: string[] }) {
  const { palette: c } = useTheme();
  const [which, setWhich] = useState<'days' | 'hours'>('days');
  const hours = metrics.test_hours;
  const src = which === 'hours' && hours ? hours : metrics;
  const any = src.targets.any;
  const horizons = Object.entries(src.targets)
    .filter(([key, v]) => key.startsWith('step_') && v)
    .map(([key, v]) => ({
      label: `${key.split('_')[1]} min ahead`,
      world_model: v!.world_model.average_precision ?? 0,
      logistic_regression: v!.logistic_regression.average_precision ?? 0,
      persistence_reference: v!.persistence_reference?.average_precision ?? 0
    }));
  const onset = src.onset?.any;
  const tabs = [
    { id: 'days' as const, title: 'Days it had never seen', sub: `Test A · ${testDays.join(', ')}` },
    ...(hours ? [{ id: 'hours' as const, title: 'Hours it had never seen', sub: `Test B · ${hours.n.toLocaleString()} moments from held-out hours of the training days` }] : [])
  ];
  return (
    <div className="space-y-5">
      {tabs.length > 1 && (
        <div className="grid gap-2 sm:grid-cols-2" role="tablist" aria-label="Which test to show">
          {tabs.map(t => (
            <button
              key={t.id}
              role="tab"
              aria-selected={which === t.id}
              onClick={() => setWhich(t.id)}
              className={`rounded-xl border px-3 py-2 text-left transition-colors ${which === t.id ? 'border-lstm bg-lstm/10' : 'border-line bg-surface-2 hover:border-line-strong'}`}
            >
              <span className="block text-sm font-medium text-ink">{t.title}</span>
              <span className="block text-xs text-muted">{t.sub}</span>
            </button>
          ))}
        </div>
      )}
      {tabs.length > 1 && (
        <p className="text-sm leading-relaxed text-ink-2">
          {which === 'days'
            ? 'The toughest test: whole days of traffic the model never saw while learning. Every day looks a bit different (busier, other machines, other attack tools), so this shows how well it copes with the unfamiliar.'
            : 'The same kinds of days it learned from, but hours it never saw. This shows how well it learned how known attacks unfold over time.'}
        </p>
      )}
      {any && (
        <div className="grid gap-3 sm:grid-cols-3">
          {(Object.keys(NAMES) as Key[]).map(key => {
            const m = any[key];
            if (!m) return null;
            const quiet = m.fp + m.tn;
            return (
              <div key={key} className="rounded-xl border border-line bg-surface-2 p-3">
                <p className="flex items-center gap-2 text-xs text-muted">
                  <span className="inline-block h-3 w-3 rounded-sm" style={{ background: colorOf(c, key) }} />
                  {NAMES[key]}
                </p>
                <p className="mt-1 text-sm leading-relaxed text-ink">
                  Spotted <span className="font-semibold">{inWords(m.recall)}</span> moments where an attack was coming in the next {k} minutes.
                </p>
                <p className="mt-1 text-sm leading-relaxed text-ink-2">
                  Cried wolf <span className="font-semibold text-ink">{m.fp}</span> time{m.fp === 1 ? '' : 's'} out of {quiet.toLocaleString()} quiet moments.
                </p>
                <p className="tabular mt-2 text-[11px] text-muted">
                  recall {m.recall.toFixed(2)} · precision {m.precision.toFixed(2)} · F1 {m.f1.toFixed(2)}
                </p>
              </div>
            );
          })}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="text-sm font-semibold text-ink">How well it ranks risky moments, by how far ahead</h3>
          <p className="mb-2 mt-1 text-xs text-muted">
            Average precision: 1.0 means every real attack moment was ranked above every quiet one. Useful because it doesn&apos;t depend on where we
            draw the flag line.
          </p>
          <div className="h-[220px]" role="img" aria-label="Average precision by how far ahead the forecast looks">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={horizons} margin={{ top: 16, right: 8, bottom: 0, left: -8 }} barCategoryGap="25%" barGap={2}>
                <CartesianGrid vertical={false} stroke={c.grid} />
                <XAxis dataKey="label" stroke={c.axis} tick={{ fill: c.tick, fontSize: 11 }} tickLine={false} />
                <YAxis domain={[0, 1]} ticks={[0, 0.5, 1]} stroke={c.axis} tick={{ fill: c.tick, fontSize: 11 }} tickLine={false} axisLine={false} />
                <Tooltip
                  isAnimationActive={false}
                  cursor={{ fill: c.cursor, fillOpacity: 0.06 }}
                  content={({ active, payload, label }) =>
                    active && payload?.length ? (
                      <div className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs shadow-lg">
                        <p className="mb-1 text-muted">{label}</p>
                        {payload.map(p => (
                          <p key={String(p.dataKey)} className="flex items-center gap-2">
                            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: colorOf(c, p.dataKey as Key) }} />
                            <span className="tabular font-semibold text-ink">{Number(p.value).toFixed(2)}</span>
                            <span className="text-ink-2">{NAMES[p.dataKey as Key]}</span>
                          </p>
                        ))}
                      </div>
                    ) : null
                  }
                />
                {(Object.keys(NAMES) as Key[]).map(key => (
                  <Bar key={key} dataKey={key} fill={colorOf(c, key)} radius={[4, 4, 0, 0]} isAnimationActive={false}>
                    <LabelList dataKey={key} position="top" formatter={(v: unknown) => Number(v).toFixed(2)} style={{ fill: c.neutral, fontSize: 10 }} />
                  </Bar>
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="space-y-3">
          {onset && (
            <div>
              <h3 className="text-sm font-semibold text-ink">
                Can it <Term k="early warning">warn early</Term>, while everything still looks normal?
              </h3>
              <p className="mb-2 mt-1 text-xs leading-relaxed text-muted">
                This is the case that matters most, and the hardest. Of {onset.world_model.n.toLocaleString()} calm moments, only{' '}
                {onset.world_model.positives} were followed by an attack within {k} minutes.{' '}
                {onset.world_model.tp === 0
                  ? "Honestly, it didn't catch any of them in advance: in this dataset attacks start abruptly, with no scouting beforehand."
                  : `It caught ${onset.world_model.tp} of them ahead of time.`}
              </p>
              <MetricTable block={onset} />
            </div>
          )}
          <p className="text-xs leading-relaxed text-muted">
            * The <Term k="persistence">“same as now” guess</Term> just assumes the next minutes will look like this one. It cheats by reading the
            true labels, so it isn&apos;t a real detector. It shows how easy it is to be right once an attack is already running.
          </p>
          <p className="text-xs leading-relaxed text-muted">
            {synthetic
              ? 'These numbers come from generated practice data. They show the pipeline works; they are not a benchmark.'
              : which === 'days'
                ? `Measured on whole days the model never trained on: ${testDays.join(', ')}.`
                : 'Measured on held-out hours of the training days.'}
          </p>
        </div>
      </div>

      {any && (
        <details className="group">
          <summary className="cursor-pointer list-none text-xs text-lstm">
            <span className="mr-1 inline-block transition-transform group-open:rotate-90">›</span>The full numbers (for the technically curious)
          </summary>
          <div className="mt-3">
            <MetricTable block={any} />
          </div>
        </details>
      )}
    </div>
  );
}
