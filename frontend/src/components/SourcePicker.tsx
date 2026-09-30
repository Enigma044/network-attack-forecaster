import { useRef, useState } from 'react';
import type { ModelInfo, Sample } from '../api';

export type Source = { kind: 'sample'; sample: Sample } | { kind: 'upload'; file: File };

const ATTACKS: Record<string, string> = {
  'Wednesday-14-02-2018': 'FTP & SSH brute force',
  'Thursday-15-02-2018': 'DoS GoldenEye, Slowloris',
  'Friday-16-02-2018': 'DoS SlowHTTPTest, Hulk',
  'Wednesday-21-02-2018': 'DDoS LOIC-UDP, HOIC',
  'Thursday-22-02-2018': 'Web brute force, XSS, SQL injection',
  'Friday-23-02-2018': 'Web brute force, XSS, SQL injection',
  'Wednesday-28-02-2018': 'Infiltration (internal scanning)',
  'Thursday-01-03-2018': 'Infiltration (internal scanning)',
  'Friday-02-03-2018': 'Botnet (Ares) C2'
};

const dayOf = (stem: string) => stem.replace('_TrafficForML_CICFlowMeter', '');

interface Props {
  samples: Sample[];
  models: ModelInfo[];
  source: Source | null;
  onSource: (s: Source) => void;
  model: string;
  onModel: (m: string) => void;
  busy: boolean;
  onRun: () => void;
  maxUploadMb?: number;
}

export default function SourcePicker({ samples, models, source, onSource, model, onModel, busy, onRun, maxUploadMb }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const real = samples.filter(s => s.kind === 'real');
  const synth = samples.filter(s => s.kind === 'synthetic');
  const current = models.find(m => m.name === model);
  const testDays = new Set((current?.split.test ?? []).map(c => c.split(':')[0]));
  const trainFiles = new Set((current?.training_files ?? []).map(f => f.replace(/\.csv$/, '')));
  const selectedId = source?.kind === 'sample' ? source.sample.id : null;

  const tag = (s: Sample) =>
    testDays.has(s.stem) ? { text: 'fair test · model never saw this day', cls: 'bg-good/15 text-good' } : trainFiles.has(s.stem) ? { text: 'model learned from this day', cls: 'bg-wash-strong text-ink-2' } : null;

  const card = (s: Sample, title: string, sub: string) => {
    const t = tag(s);
    const active = selectedId === s.id;
    return (
      <button
        key={s.id}
        onClick={() => onSource({ kind: 'sample', sample: s })}
        aria-pressed={active}
        className={`flex flex-col items-start gap-1 rounded-xl border px-3 py-2.5 text-left transition-colors ${
          active ? 'border-lstm bg-lstm/10' : 'border-line bg-surface-2 hover:border-line-strong'
        }`}
      >
        <span className="text-sm font-medium text-ink">{title}</span>
        <span className="text-xs text-ink-2">{sub}</span>
        <span className="mt-1 flex flex-wrap gap-1.5 text-[11px]">
          <span className="rounded bg-wash px-1.5 py-0.5 text-muted">{s.size_mb} MB</span>
          {t && <span className={`rounded px-1.5 py-0.5 ${t.cls}`}>{t.text}</span>}
        </span>
      </button>
    );
  };

  const realSorted = [...real].sort((a, b) => Number(testDays.has(b.stem)) - Number(testDays.has(a.stem)) || a.size_mb - b.size_mb);

  return (
    <div className="space-y-4">
      {real.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">Real traffic from a test network (CIC-IDS-2018), one file per day</p>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {realSorted.map(s => card(s, dayOf(s.stem), ATTACKS[dayOf(s.stem)] ?? 'CIC-IDS-2018 capture'))}
          </div>
        </div>
      )}
      <div className="grid gap-3 lg:grid-cols-2">
        {synth.length > 0 && (
          <div>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">Practice data (made up, for a quick look)</p>
            <select
              className="w-full rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-ink"
              value={source?.kind === 'sample' && source.sample.kind === 'synthetic' ? source.sample.id : ''}
              onChange={e => {
                const s = synth.find(x => x.id === e.target.value);
                if (s) onSource({ kind: 'sample', sample: s });
              }}
            >
              <option value="" disabled>
                Choose a practice day…
              </option>
              {synth.map(s => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
        )}
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">Or bring your own file</p>
          <div
            onDragOver={e => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={e => {
              e.preventDefault();
              setDragging(false);
              const f = e.dataTransfer.files[0];
              if (f) onSource({ kind: 'upload', file: f });
            }}
            className={`flex items-center gap-3 rounded-lg border border-dashed px-3 py-2 text-sm ${
              dragging ? 'border-lstm bg-lstm/10' : source?.kind === 'upload' ? 'border-lstm bg-lstm/10' : 'border-line-strong bg-surface-2'
            }`}
          >
            <button className="rounded-md bg-wash-strong px-3 py-1 text-ink hover:bg-wash-strong" onClick={() => inputRef.current?.click()}>
              Choose CSV
            </button>
            <span className="truncate text-ink-2">
              {source?.kind === 'upload' ? `${source.file.name} · ${(source.file.size / 1e6).toFixed(1)} MB` : `or drop a CIC-IDS-2018 flow CSV${maxUploadMb ? ` (up to ${maxUploadMb >= 1000 ? `${+(maxUploadMb / 1024).toFixed(1)} GB` : `${Math.round(maxUploadMb)} MB`})` : ''}`}
            </span>
            <input
              ref={inputRef}
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              onChange={e => {
                const f = e.target.files?.[0];
                if (f) onSource({ kind: 'upload', file: f });
              }}
            />
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
        <button
          onClick={onRun}
          disabled={busy || !source || !model}
          className="rounded-lg bg-lstm px-5 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? 'Working on it…' : 'Run the forecast'}
        </button>
        <label className="flex items-center gap-2 text-xs text-muted">
          Model
          <select
            className="rounded-lg border border-line bg-surface-2 px-2 py-1.5 text-xs text-ink"
            value={model}
            onChange={e => onModel(e.target.value)}
          >
            {models.map(m => (
              <option key={m.name} value={m.name}>
                {m.data_kind === 'synthetic' ? 'Practice model (learned from made-up data)' : 'Main model (learned from real traffic)'}
              </option>
            ))}
          </select>
        </label>
        <span className="text-xs text-muted">We pick the right model for the data you choose, so you rarely need to change this.</span>
      </div>
    </div>
  );
}
