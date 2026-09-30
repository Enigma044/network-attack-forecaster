import { useState } from 'react';
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { ForecastDetail } from '../api';
import { fmtTime } from '../format';
import { plainLabelList } from '../labels';
import { useTheme } from '../theme';
import Term from './Term';

function DivergingBars({ rows }: { rows: { key: string; label: string; value: number; hint?: string }[] }) {
  const [hover, setHover] = useState<string | null>(null);
  const max = Math.max(0.05, ...rows.map(r => Math.abs(r.value)));
  return (
    <ul className="space-y-1">
      {rows.map(r => {
        const pct = (Math.abs(r.value) / max) * 50;
        const up = r.value >= 0;
        return (
          <li
            key={r.key}
            className={`grid grid-cols-[minmax(0,12rem)_1fr_3.2rem] items-center gap-2 rounded-md px-1 py-1 text-xs ${hover === r.key ? 'bg-wash' : ''}`}
            onMouseEnter={() => setHover(r.key)}
            onMouseLeave={() => setHover(null)}
            title={r.hint}
          >
            <span className="truncate text-ink-2">{r.label}</span>
            <span className="relative h-3.5">
              <span className="absolute inset-y-0 left-1/2 w-px bg-axis" />
              <span className={`absolute inset-y-0 ${up ? 'left-1/2 rounded-r bg-raise' : 'right-1/2 rounded-l bg-lower'}`} style={{ width: `${pct}%` }} />
            </span>
            <span className="tabular text-right text-ink">{up ? '+' : ''}{r.value.toFixed(2)}</span>
          </li>
        );
      })}
    </ul>
  );
}

const compact = (v: number) => {
  const a = Math.abs(v);
  return a >= 100 ? v.toFixed(0) : a >= 10 ? v.toFixed(1) : v.toFixed(2);
};

const pct = (v?: number) => (v == null ? '–' : `${Math.round(v * 100)}%`);

export default function WhyPanel({ detail }: { detail: ForecastDetail }) {
  const { palette: c } = useTheme();
  const { shap, temporal } = detail;
  const maxT = Math.max(0.05, ...temporal.map(t => Math.abs(t.importance)));
  const top = shap.features[0];
  return (
    <div className="space-y-6">
      {detail.summary.length > 0 && (
        <div className="rounded-xl border border-line bg-surface-2 p-4">
          <p className="mb-2 text-sm font-semibold text-ink">In plain words</p>
          <ul className="space-y-1.5 text-sm leading-relaxed text-ink-2">
            {detail.summary.map(s => (
              <li key={s} className="flex gap-2">
                <span aria-hidden="true" className="text-lstm">•</span>
                <span>{s}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="text-sm font-semibold text-ink">What caught its attention</h3>
          <p className="mb-3 mt-1 text-xs leading-relaxed text-muted">
            Red bars made the model more worried, blue bars calmed it down.{' '}
            {top && <>The biggest single clue was <span className="text-ink-2">{top.description}</span>. </>}
            (Measured with <Term k="shapley">Shapley values</Term> in <Term k="log-odds">log-odds</Term>, against a normal minute.)
          </p>
          <div className="mb-2 flex items-center gap-4 text-xs text-ink-2">
            <span className="flex items-center gap-1.5"><span className="inline-block h-3 w-3 rounded-sm bg-raise" />more worried</span>
            <span className="flex items-center gap-1.5"><span className="inline-block h-3 w-3 rounded-sm bg-lower" />less worried</span>
          </div>
          <DivergingBars
            rows={shap.features.map(f => ({
              key: f.feature,
              label: f.description,
              value: f.shap_logodds,
              hint: `${f.feature}: last minute ${f.z_last.toFixed(1)}σ from normal (furthest ${f.z_peak.toFixed(1)}σ)`
            }))}
          />
        </div>
        <div className="space-y-6">
          <div>
            <h3 className="text-sm font-semibold text-ink">In broad strokes</h3>
            <p className="mb-3 mt-1 text-xs text-muted">The same clues, grouped by kind.</p>
            <DivergingBars rows={shap.groups.map(g => ({ key: g.group, label: g.group, value: g.value }))} />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-ink">When it started to look suspicious</h3>
            <p className="mb-3 mt-1 text-xs leading-relaxed text-muted">
              We hid one past minute at a time and watched how much the forecast changed. Tall red bars mark the minutes that mattered most. The thin
              line underneath turns red where the dataset says an attack was already running.
            </p>
            <div className="flex h-20 items-end gap-1" role="img" aria-label="How much each past minute mattered">
              {temporal.map(t => {
                const h = (Math.abs(t.importance) / maxT) * 100;
                return (
                  <div
                    key={t.window_start}
                    className="flex flex-1 flex-col items-center gap-1"
                    title={`${fmtTime(t.window_start)}: ${t.importance >= 0 ? '+' : ''}${t.importance.toFixed(2)} log-odds · ${t.n_flows} connections${t.is_attack === 1 ? ' · attack under way' : ''}`}
                  >
                    <div className="flex h-14 w-full items-end">
                      <div className={`w-full rounded-t ${t.importance >= 0 ? 'bg-raise' : 'bg-lower'}`} style={{ height: `${Math.max(h, 3)}%` }} />
                    </div>
                    <span className={`h-1 w-full rounded ${t.is_attack === 1 ? 'bg-critical' : 'bg-wash-strong'}`} />
                  </div>
                );
              })}
            </div>
            <div className="mt-1 flex justify-between text-[10px] text-muted">
              <span>{temporal[0] && `${fmtTime(temporal[0].window_start)} · 10 min before`}</span>
              <span>{temporal.length > 0 && `${fmtTime(temporal[temporal.length - 1].window_start)} · latest`}</span>
            </div>
          </div>
        </div>
      </div>

      <div>
        <h3 className="text-sm font-semibold text-ink">Up close: the three biggest clues, minute by minute</h3>
        <p className="mb-3 mt-1 text-xs text-muted">The actual values in the 10 minutes the model looked at.</p>
        <div className="grid gap-3 md:grid-cols-3">
          {detail.evidence.map(ev => (
            <div key={ev.feature} className="rounded-xl bg-surface-2 p-3">
              <p className="text-xs font-medium text-ink">{ev.description}</p>
              <div className="mt-2 h-[100px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={ev.points} margin={{ top: 4, right: 6, bottom: 0, left: 0 }}>
                    <XAxis dataKey="window_start" tickFormatter={fmtTime} tick={{ fill: c.tick, fontSize: 10 }} stroke={c.axis} tickLine={false} minTickGap={24} />
                    <YAxis tick={{ fill: c.tick, fontSize: 10 }} axisLine={false} tickLine={false} width={40} tickFormatter={compact} domain={['auto', 'auto']} tickCount={3} />
                    <Tooltip
                      isAnimationActive={false}
                      cursor={{ stroke: c.cursor, strokeOpacity: 0.4 }}
                      content={({ active, payload }) =>
                        active && payload?.length ? (
                          <div className="rounded-md border border-line bg-surface px-2 py-1 text-xs shadow">
                            <span className="tabular font-semibold text-ink">{Number(payload[0].value).toFixed(3)}</span>{' '}
                            <span className="text-muted">at {fmtTime(payload[0].payload.window_start)}</span>
                          </div>
                        ) : null
                      }
                    />
                    <Line type="linear" dataKey="value" stroke={c.neutral} strokeWidth={2} dot={{ r: 2.5, fill: c.neutral, stroke: c.surface, strokeWidth: 1 }} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          ))}
        </div>
      </div>

      {detail.flows.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-ink">Traffic that suddenly picked up</h3>
          <p className="mb-3 mt-1 text-xs text-muted">
            Connections grouped by where they were going, sorted by how much busier they got in the last 3 minutes. A good place to start looking.
          </p>
          <div className="overflow-x-auto">
            <table className="tabular w-full min-w-[640px] text-xs">
              <thead>
                <tr className="border-b border-line text-left text-muted">
                  <th className="py-2 pr-3 font-medium">Going to</th>
                  <th className="px-2 py-2 text-right font-medium">Connections</th>
                  <th className="px-2 py-2 text-right font-medium">Per minute: before → lately</th>
                  <th className="px-2 py-2 text-right font-medium" title="Share of connections that opened with a SYN flag">SYN</th>
                  <th className="px-2 py-2 text-right font-medium" title="Share of connections that were reset">RST</th>
                  <th className="px-2 py-2 text-right font-medium" title="Share of connections that got no reply">No reply</th>
                  <th className="py-2 pl-3 font-medium">Dataset says</th>
                </tr>
              </thead>
              <tbody>
                {detail.flows.map(f => (
                  <tr key={`${f['Dst Port']}-${f.Protocol}`} className="border-b border-line">
                    <td className="py-1.5 pr-3 text-ink">
                      port {f['Dst Port']} <span className="text-muted">({f.Protocol})</span>
                    </td>
                    <td className="px-2 py-1.5 text-right text-ink-2">{f.flows.toLocaleString()}</td>
                    <td className="px-2 py-1.5 text-right">
                      <span className="text-ink-2">{f.rate_before.toFixed(1)}</span>
                      <span className="text-muted"> → </span>
                      <span className={f.growth > 0 ? 'font-medium text-critical' : 'text-ink-2'}>{f.rate_recent.toFixed(1)}</span>
                    </td>
                    <td className="px-2 py-1.5 text-right text-ink-2">{pct(f.syn_share)}</td>
                    <td className="px-2 py-1.5 text-right text-ink-2">{pct(f.rst_share)}</td>
                    <td className="px-2 py-1.5 text-right text-ink-2">{pct(f.no_reply_share)}</td>
                    <td className="py-1.5 pl-3 text-ink-2" title={f.labels}>{f.labels ? plainLabelList(f.labels) : '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
