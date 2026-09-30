import type { Report } from '../api';
import { fmtDuration } from '../format';
import { StatusNote } from './Panel';

export default function ValidationPanel({ report }: { report: Report }) {
  const labels = Object.entries(report.label_counts).sort((a, b) => b[1] - a[1]);
  return (
    <details open={!report.ok || report.warnings.length > 0} className="card-shadow group rounded-2xl border border-line bg-surface p-5">
      <summary className="cursor-pointer list-none text-sm font-semibold text-ink">
        <span className="mr-2 inline-block text-muted transition-transform group-open:rotate-90">›</span>
        {report.ok ? 'The file looks good' : 'We couldn’t use this file'} · <span className="font-normal text-ink-2">{report.source}</span>
        <span className={`ml-3 text-xs font-medium ${report.ok ? 'text-good' : 'text-raise'}`}>
          {report.ok ? '✓ ready' : '✕ rejected'}
        </span>
      </summary>
      <div className="mt-4 space-y-3">
        {report.errors.map(e => (
          <StatusNote key={e} tone="critical" label="Problem">
            {e}
          </StatusNote>
        ))}
        {report.warnings.map(w => (
          <StatusNote key={w} tone="warning" label="Heads up">
            {w}
          </StatusNote>
        ))}
        {report.n_rows_read > 0 && (
          <dl className="tabular grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            {[
              ['Lines read', report.n_rows_read.toLocaleString()],
              ['Usable connections', report.n_rows_valid.toLocaleString()],
              ['Has answer key (labels)', report.has_labels ? 'yes' : 'no'],
              ['Covers', fmtDuration(report.time_start, report.time_end)]
            ].map(([k, v]) => (
              <div key={k} className="rounded-lg bg-surface-2 px-3 py-2">
                <dt className="text-xs text-muted">{k}</dt>
                <dd className="font-medium text-ink">{v}</dd>
              </div>
            ))}
          </dl>
        )}
        {labels.length > 0 && (
          <div className="flex flex-wrap gap-2 text-xs">
            {labels.map(([label, n]) => (
              <span key={label} className="rounded-full border border-line px-2.5 py-1 text-ink-2">
                {label} <span className="tabular text-muted">{n.toLocaleString()}</span>
              </span>
            ))}
          </div>
        )}
      </div>
    </details>
  );
}
