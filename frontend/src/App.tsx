import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  api, ApiError, type AnalysisResult, type Forecast, type ForecastDetail, type Info, type ModelInfo, type Report, type Sample, type WindowRow
} from './api';
import AlertsPanel from './components/AlertsPanel';
import Header from './components/Header';
import HowItWorks, { type StepState } from './components/HowItWorks';
import Kpis from './components/Kpis';
import Panel, { StatusNote } from './components/Panel';
import Rollout from './components/Rollout';
import Scoreboard, { MetricTable } from './components/Scoreboard';
import SourcePicker, { type Source } from './components/SourcePicker';
import StageChain, { plainStage } from './components/StageChain';
import StateStrip from './components/StateStrip';
import Term from './components/Term';
import Timeline, { isEarlyWarning, worryWord } from './components/Timeline';
import ValidationPanel from './components/ValidationPanel';
import WhyPanel from './components/WhyPanel';
import { fmtLongDate, fmtTime, toMs } from './format';
import { plainLabel } from './labels';

/** Attack onsets in the labels and how many the model warned about before they began. */
function onsetStory(forecasts: Forecast[], windows: WindowRow[], windowMs: number, k: number) {
  const onsets: number[] = [];
  windows.forEach((w, i) => {
    if (w.is_attack === 1 && (i === 0 || windows[i - 1].is_attack !== 1)) onsets.push(toMs(w.window_start));
  });
  const leads: number[] = [];
  for (const t of onsets) {
    const warned = forecasts
      .filter(f => f.wm_alert && f.now_is_attack === 0)
      .map(f => toMs(f.input_end) + windowMs)
      .filter(now => now <= t && now >= t - k * windowMs);
    if (warned.length) leads.push((t - Math.min(...warned)) / 60000);
  }
  return { onsets: onsets.length, warned: leads.length, meanLead: leads.length ? leads.reduce((a, b) => a + b, 0) / leads.length : 0 };
}

export default function App() {
  const [info, setInfo] = useState<Info | null>(null);
  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [modelName, setModelName] = useState('');
  const [source, setSource] = useState<Source | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(-1);
  const [building, setBuilding] = useState(false);
  const [fatal, setFatal] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [capture, setCapture] = useState('');
  const [selectedRow, setSelectedRow] = useState<number | null>(null);
  const [detail, setDetail] = useState<ForecastDetail | null>(null);
  const [detailBusy, setDetailBusy] = useState(false);
  const [showBaseline, setShowBaseline] = useState(false);
  const resultsRef = useRef<HTMLDivElement>(null);

  const model = models?.find(m => m.name === modelName) ?? null;

  const load = useCallback(async () => {
    const [ms, ss] = await Promise.all([api.models(), api.samples()]);
    setModels(ms);
    setSamples(ss);
    const realModel = ms.find(m => m.data_kind === 'external');
    const preferred = realModel ?? ms[0];
    setModelName(prev => (ms.some(m => m.name === prev) ? prev : preferred?.name ?? ''));
    setSource(prev => {
      if (prev) return prev;
      const testDays = new Set((preferred?.split.test ?? []).map(c => c.split(':')[0]));
      const pool = ss.filter(s => (preferred?.data_kind === 'external' ? s.kind === 'real' : s.kind === 'synthetic'));
      const pick = pool.filter(s => testDays.has(s.stem)).sort((a, b) => a.size_mb - b.size_mb)[0] ?? pool[0];
      return pick ? { kind: 'sample', sample: pick } : null;
    });
  }, []);

  useEffect(() => {
    Promise.all([api.info(), load()])
      .then(([i]) => setInfo(i))
      .catch(() => setFatal('Cannot reach the local API. Start it with: .venv/bin/uvicorn netforecast.api:app --port 8000'));
  }, [load]);

  // Match the model to the data: real CSVs -> the CIC-IDS-2018 model, synthetic -> the synthetic demo model.
  const chooseSource = (s: Source) => {
    setSource(s);
    if (!models) return;
    const wantSynthetic = s.kind === 'sample' && s.sample.kind === 'synthetic';
    const match = models.find(m => (m.data_kind === 'synthetic') === wantSynthetic);
    if (match) setModelName(match.name);
  };

  const buildDemo = async () => {
    setBuilding(true);
    try {
      await api.buildDemo();
      await load();
    } catch (e) {
      setRunError(e instanceof Error ? e.message : String(e));
    } finally {
      setBuilding(false);
    }
  };

  const run = async () => {
    if (!source) return;
    setBusy(true);
    setRunError(null);
    setResult(null);
    setDetail(null);
    setReport(null);
    setProgress(0);
    const timer = window.setInterval(() => setProgress(p => Math.min(p + 1, 3)), 1400);
    try {
      const r = await api.analyze(modelName, source.kind === 'upload' ? { file: source.file } : { sample: source.sample.id });
      setResult(r);
      setReport(r.report);
      const first = r.forecasts[0]?.capture_id ?? '';
      setCapture(first);
      const inCap = r.forecasts.filter(f => f.capture_id === first);
      const early = inCap.filter(isEarlyWarning);
      const pick = (early.length ? early : inCap).reduce((a, b) => (b.wm_any > a.wm_any ? b : a), (early.length ? early : inCap)[0]);
      setSelectedRow(pick?.row ?? null);
      setProgress(5);
      window.setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100);
    } catch (e) {
      setProgress(-1);
      if (e instanceof ApiError && e.report) setReport(e.report);
      else setRunError(e instanceof Error ? e.message : String(e));
    } finally {
      window.clearInterval(timer);
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!result || selectedRow == null) return;
    let cancelled = false;
    setDetailBusy(true);
    api
      .forecast(result.id, selectedRow)
      .then(d => !cancelled && setDetail(d))
      .catch(e => !cancelled && setRunError(e.message))
      .finally(() => !cancelled && setDetailBusy(false));
    return () => {
      cancelled = true;
    };
  }, [result, selectedRow]);

  const captures = useMemo(() => [...new Set(result?.forecasts.map(f => f.capture_id) ?? [])], [result]);
  const fc = useMemo(() => result?.forecasts.filter(f => f.capture_id === capture) ?? [], [result, capture]);
  const wins = useMemo(() => result?.windows.filter(w => w.capture_id === capture) ?? [], [result, capture]);
  const alerts = useMemo(() => fc.filter(f => f.wm_alert), [fc]);
  const selected = result?.forecasts.find(f => f.row === selectedRow) ?? null;
  const resultModel = models?.find(m => m.name === result?.model) ?? model;
  const windowMs = (resultModel?.window_seconds ?? 60) * 1000;
  const k = resultModel?.k ?? 10;
  const story = useMemo(() => (result?.has_labels ? onsetStory(fc, wins, windowMs, k) : null), [result, fc, wins, windowMs, k]);
  const synthetic = resultModel?.data_kind === 'synthetic' || report?.data_kind === 'synthetic';

  const stepStates: StepState[] = [0, 1, 2, 3, 4].map(i => (progress >= 5 ? 'done' : progress < 0 ? 'idle' : i < progress ? 'done' : i === progress ? 'active' : 'idle'));

  if (fatal) {
    return (
      <Shell>
        <StatusNote tone="critical" label="Can't reach the local server">{fatal}</StatusNote>
      </Shell>
    );
  }
  if (!models || !info) {
    return (
      <Shell>
        <p className="text-sm text-muted">Getting things ready…</p>
      </Shell>
    );
  }

  return (
    <Shell>
      <Panel
        title="How it works, in five steps"
        subtitle={
          <>
            Most security tools look at each connection on its own and ask “is this bad?”. We ask a different question: judging by how the
            whole network has been behaving over the last few minutes, <em>what is likely to happen next?</em> Hover any dotted word for a
            short explanation.
          </>
        }
      >
        <HowItWorks states={stepStates} />
      </Panel>

      <Panel
        id="try"
        title="Pick a day to replay"
        subtitle="Choose a day of recorded traffic and we'll replay it minute by minute, as if you were watching it live. Days marked “fair test” were kept away from the model while it learned, so what you see there is honest."
      >
        {models.length === 0 ? (
          <div className="space-y-3 text-sm text-ink-2">
            <p>There's no trained model yet. Train one on the CIC-IDS-2018 files from the command line, or build the practice model to look around.</p>
            {!info.public && (
              <button onClick={buildDemo} disabled={building} className="rounded-lg bg-lstm px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
                {building ? 'Making practice data and training…' : 'Build the practice model'}
              </button>
            )}
          </div>
        ) : (
          <SourcePicker
            samples={samples}
            models={models}
            source={source}
            onSource={chooseSource}
            model={modelName}
            onModel={setModelName}
            busy={busy}
            onRun={run}
            maxUploadMb={info.max_upload_mb}
          />
        )}
      </Panel>

      {runError && <StatusNote tone="critical" label="Something went wrong">{runError}</StatusNote>}
      {busy && (
        <StatusNote tone="info" label="Working on it">
          {['Reading the traffic log…', 'Summarising every minute…', 'Letting the model watch the day…', 'Imagining 32 futures for every minute…'][Math.max(0, Math.min(progress, 3))]}{' '}
          A full day of real traffic takes up to a minute.
        </StatusNote>
      )}

      <div ref={resultsRef} className="scroll-mt-4 space-y-5">
        {report && (
          <Panel step={1} title="First, we checked the file" subtitle="Before trusting any data, we make sure it's complete and readable, and we tell you about anything odd we had to fix.">
            <ValidationPanel report={report} />
          </Panel>
        )}

        {result && resultModel && selected && (
          <>
            {synthetic && (
              <StatusNote tone="warning" label="Practice data">
                This run uses made-up traffic or a model that learned from it. It's here to show how things work, not as evidence about real networks.
              </StatusNote>
            )}
            {captures.length > 1 && (
              <label className="flex items-center gap-2 text-xs text-muted">
                Which day
                <select
                  value={capture}
                  onChange={e => {
                    setCapture(e.target.value);
                    const first = result.forecasts.find(f => f.capture_id === e.target.value);
                    if (first) setSelectedRow(first.row);
                  }}
                  className="rounded-lg border border-line bg-surface-2 px-3 py-1.5 text-sm text-ink"
                >
                  {captures.map(c => <option key={c}>{c}</option>)}
                </select>
              </label>
            )}

            <StoryCard forecasts={fc} windows={wins} nFlows={result.n_flows} report={report} story={story} k={k} windowMs={windowMs} />

            <Kpis
              items={[
                { label: 'Connections read', value: result.n_flows },
                { label: 'Minutes replayed', value: wins.length },
                { label: 'Times it raised a flag', value: alerts.length },
                ...(story ? [
                  { label: 'Attacks that started', value: story.onsets, hint: 'according to the dataset' },
                  { label: 'Seen coming in advance', value: story.warned, hint: story.warned ? `about ${story.meanLead.toFixed(0)} min early on average` : 'none, this time' }
                ] : [
                  { label: 'Most worried', value: Math.max(...fc.map(f => f.wm_any)), percent: true },
                  { label: 'Worry at the end', value: fc[fc.length - 1].wm_any, percent: true }
                ])
              ]}
            />

            <Panel
              step={2}
              title="How busy the network was"
              subtitle={
                <>
                  Each minute gets boiled down to a short summary, a <Term k="state">state</Term> of 34 numbers. Here&apos;s the simplest one: how many
                  connections happened that minute. Red shading marks the times the dataset says an attack was going on.
                </>
              }
            >
              <StateStrip windows={wins} windowSeconds={resultModel.window_seconds} hasLabels={result.has_labels} />
            </Panel>

            <div className="grid gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
              <Panel
                step="3 · 4"
                title="How worried the model was, minute by minute"
                subtitle={
                  <>
                    Every minute, the <Term k="world model">model</Term> looks back {resultModel.seq_len} minutes and{' '}
                    <Term k="rollout">imagines</Term> the next {k}. The blue line is how likely it thinks an attack is. Ideally it climbs{' '}
                    <em>before</em> a red patch begins. Treat the numbers as a sense of risk, not an exact chance.
                  </>
                }
              >
                <Timeline
                  forecasts={fc}
                  windows={wins}
                  windowSeconds={resultModel.window_seconds}
                  k={k}
                  threshold={resultModel.thresholds.world_model.any}
                  hasLabels={result.has_labels}
                  selectedRow={selectedRow}
                  onSelect={setSelectedRow}
                />
              </Panel>
              <Panel title={`Moments it raised a flag · ${alerts.length}`} subtitle="Each time the blue line crossed the dashed line. Pick one to see what the model was imagining and why.">
                <AlertsPanel alerts={alerts} windowSeconds={resultModel.window_seconds} hasLabels={result.has_labels} selectedRow={selectedRow} onSelect={setSelectedRow} />
              </Panel>
            </div>

            <Panel
              step={4}
              title={`What it expected to happen next, at ${fmtTime(toMs(selected.input_end) + windowMs)}`}
              subtitle={
                <>
                  The model played the next {k} minutes forward 32 times, each a little differently. The line is the typical outcome; the shaded band
                  shows how much the imagined futures disagreed. A wide band means “I&apos;m not sure”.
                </>
              }
              actions={
                <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted">
                  <input type="checkbox" checked={showBaseline} onChange={e => setShowBaseline(e.target.checked)} className="accent-base" />
                  Compare with a simple baseline
                </label>
              }
            >
              <div className="grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
                <div className={detailBusy ? 'opacity-50 transition-opacity' : 'transition-opacity'}>
                  {detail && detail.row === selected.row ? <Rollout detail={detail} showBaseline={showBaseline} /> : <p className="text-sm text-muted">Imagining the next few minutes…</p>}
                </div>
                <div className="space-y-3 text-sm">
                  <div className="rounded-xl bg-surface-2 p-3">
                    <p className="text-xs text-muted">
                      <Term k="infiltration probability">Chance of an attack</Term> in the next {k} minutes
                    </p>
                    <p className="tabular text-3xl font-semibold text-ink">{Math.round(selected.wm_any * 100)}%</p>
                    <p className="text-sm text-ink-2">
                      The model is <span className="font-medium text-ink">{worryWord(selected.wm_any)}</span>
                      {selected.wm_alert ? ' and raised a flag' : ', not enough to raise a flag'}{' '}
                      <span className="text-muted">
                        (<Term k="threshold">flag line</Term> at {Math.round(resultModel.thresholds.world_model.any * 100)}%)
                      </span>
                      .{selected.first_step_over_threshold > 0 && ` It expects trouble from about ${selected.first_step_over_threshold} minute${selected.first_step_over_threshold === 1 ? '' : 's'} from now.`}
                    </p>
                  </div>
                  <div className="rounded-xl bg-surface-2 p-3">
                    <p className="text-xs text-muted">What was really going on (dataset answer key)</p>
                    <p className="text-ink">
                      Right now:{' '}
                      {selected.now_is_attack === 1 ? 'an attack was already under way' : selected.now_is_attack === 0 ? 'normal traffic' : 'unknown (no labels)'}
                    </p>
                    {result.has_labels && (
                      <p className="mt-1 text-ink-2">
                        Next {k} minutes:{' '}
                        {selected.n_future_in_data === 0
                          ? 'past the end of the file'
                          : selected.actual_any === 1
                            ? `an attack ${selected.actual_first_attack_step === 1 ? 'the very next minute' : `${selected.actual_first_attack_step} minutes later`}${selected.actual_stage ? ` (${plainStage(selected.actual_stage)})` : ''}`
                            : 'nothing happened'}
                      </p>
                    )}
                  </div>
                  <p className="text-xs leading-relaxed text-muted">
                    Based on {fmtTime(selected.input_start)}–{fmtTime(selected.input_end)} on {fmtLongDate(selected.input_start)}. A forecast is a
                    nudge to take a look, not proof that something is wrong.
                  </p>
                </div>
              </div>
            </Panel>

            <Panel step={5} title="Why it thought so" subtitle="For the moment you picked above: what kind of attack it looks like, and which traffic patterns pushed the model's opinion.">
              <div className="mb-6">
                <StageChain
                  predicted={selected.predicted_stage}
                  probability={selected.stage_prob}
                  actual={selected.actual_stage}
                  seen={resultModel.stages_seen_in_training}
                  alert={selected.wm_alert}
                  rules={info.stage_mapping}
                />
              </div>
              <div className={detailBusy ? 'opacity-50 transition-opacity' : 'transition-opacity'}>
                {detail && detail.row === selected.row ? <WhyPanel detail={detail} /> : <p className="text-sm text-muted">Working out what mattered…</p>}
              </div>
            </Panel>

            {resultModel.metrics && (
              <Panel
                title="Can you trust it? Our honest scorecard"
                subtitle={
                  <>
                    We tested the model on traffic it never saw while learning and compared it with a <Term k="baseline">simple baseline</Term> and a
                    naive <Term k="persistence">“same as now”</Term> guess. Here&apos;s how it did, including where it falls short.
                  </>
                }
              >
                <Scoreboard metrics={resultModel.metrics} k={resultModel.k} synthetic={resultModel.data_kind === 'synthetic'} testDays={resultModel.split.test.map(c => c.split('_')[0])} />
                {result.metrics?.targets.any && (
                  <details className="group mt-5">
                    <summary className="cursor-pointer list-none text-xs text-lstm">
                      <span className="mr-1 inline-block transition-transform group-open:rotate-90">›</span>How it did on just this day
                      {source?.kind === 'sample' && resultModel.split.test.some(c => c.startsWith(source.sample.stem)) ? ' (a fair-test day)' : ' (it may have learned from this day)'}
                    </summary>
                    <div className="mt-3">
                      <MetricTable block={result.metrics.targets.any} />
                    </div>
                  </details>
                )}
              </Panel>
            )}
          </>
        )}
      </div>

      <MethodNotes info={info} model={resultModel ?? model} />
    </Shell>
  );
}

function StoryCard({ forecasts, windows, nFlows, report, story, k, windowMs }: {
  forecasts: Forecast[]; windows: WindowRow[]; nFlows: number; report: Report | null;
  story: { onsets: number; warned: number; meanLead: number } | null; k: number; windowMs: number;
}) {
  if (!windows.length || !forecasts.length) return null;
  const first = windows[0].window_start;
  const last = windows[windows.length - 1].window_start;
  const attackLabels = [...new Set(Object.keys(report?.label_counts ?? {}).filter(l => l.toLowerCase() !== 'benign' && l !== 'Label').map(plainLabel))];
  const periods: string[] = [];
  let open: number | null = null;
  windows.forEach((w, i) => {
    const on = w.is_attack === 1;
    if (on && open === null) open = toMs(w.window_start);
    const next = windows[i + 1];
    if (open !== null && (!next || next.is_attack !== 1)) {
      periods.push(`${fmtTime(open)}–${fmtTime(toMs(w.window_start) + windowMs)}`);
      open = null;
    }
  });
  const flags = forecasts.filter(f => f.wm_alert);
  const falseAlarms = flags.filter(f => f.actual_any === 0).length;
  const calmShare = forecasts.filter(f => f.wm_any < 0.25).length / forecasts.length;
  const lines: string[] = [
    `We replayed ${fmtLongDate(first)} from ${fmtTime(first)} to ${fmtTime(toMs(last) + windowMs)}: ${nFlows.toLocaleString()} connections, summarised into ${windows.length.toLocaleString()} one-minute snapshots.`
  ];
  if (story) {
    lines.push(
      story.onsets === 0
        ? 'According to the dataset, no attack started on this day.'
        : `According to the dataset, ${attackLabels.length ? attackLabels.join(' and ') : 'attack traffic'} happened in ${periods.length} stretch${periods.length === 1 ? '' : 'es'}${periods.length <= 4 ? ` (${periods.join(', ')})` : ''}.`
    );
  }
  lines.push(
    `The model was calm for ${Math.round(calmShare * 100)}% of the day and raised a flag ${flags.length} time${flags.length === 1 ? '' : 's'}${story ? `, ${falseAlarms} of them false alarm${falseAlarms === 1 ? '' : 's'}` : ''}.`
  );
  let takeaway = '';
  if (story && story.onsets > 0) {
    takeaway = story.warned > 0
      ? `It saw ${story.warned} of ${story.onsets} attack${story.onsets === 1 ? '' : 's'} coming, about ${story.meanLead.toFixed(0)} minutes before they started.`
      : `It didn't see the attacks coming. It reacted once they showed up in the traffic. On this dataset attacks start suddenly, without the scouting that would give an early hint, so there was little to go on in the ${k} minutes before.`;
  }
  return (
    <section className="card-shadow rounded-2xl border border-line border-l-4 border-l-lstm bg-surface p-5">
      <p className="text-[11px] font-semibold uppercase tracking-[0.15em] text-lstm">The story of this day</p>
      <div className="mt-2 space-y-1.5 text-[15px] leading-relaxed text-ink">
        {lines.map(l => (
          <p key={l}>{l}</p>
        ))}
        {takeaway && <p className="font-medium">{takeaway}</p>}
      </div>
      <p className="mt-3 text-xs text-muted">Scroll down to see each step, or click any moment on the chart to ask the model “why?”.</p>
    </section>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen">
      <Header />
      <main className="mx-auto flex max-w-7xl flex-col gap-5 px-4 py-6 sm:px-6">{children}</main>
      <footer className="mx-auto max-w-7xl px-4 pb-10 text-xs text-muted sm:px-6">
        SIH 2026 · Problem 26153 · runs fully offline on this machine · CIC-IDS-2018 © Canadian Institute for Cybersecurity
      </footer>
    </div>
  );
}

function MethodNotes({ info, model }: { info: Info; model: ModelInfo | null }) {
  return (
    <details className="card-shadow group rounded-2xl border border-line bg-surface p-5">
      <summary className="cursor-pointer list-none text-sm font-semibold text-ink">
        <span className="mr-2 inline-block text-muted transition-transform group-open:rotate-90">›</span>
        Method details, stage mapping and limitations
      </summary>
      <div className="mt-4 grid gap-6 text-sm text-ink-2 lg:grid-cols-2">
        <ul className="list-disc space-y-1.5 pl-5">
          <li>
            <strong className="text-ink">State</strong>: {info.n_features} per-minute aggregates: volume, protocol mix, durations, packet and byte
            sizes, inter-arrival time, TCP flag rates, destination-port groups, distinct ports and hosts. Raw IP addresses are never used as
            features.
          </li>
          <li>
            <strong className="text-ink">World model</strong>: an LSTM with four heads. It predicts a Gaussian over the next state P(S_t+1 | S_≤t),
            the attack probability and the stage of the next window. It is trained with teacher forcing plus an open-loop {model?.k ?? 10}-step
            rollout loss, so it learns to forecast from its own predictions.
          </li>
          <li>
            <strong className="text-ink">Forecast</strong>: 32 sampled rollouts per minute. The probability of an attack within K is the peak step
            probability on each trajectory, averaged over trajectories.
          </li>
          <li>
            <strong className="text-ink">Explanation</strong>: permutation-sampled Shapley values of the rollout&apos;s mean attack log-odds (the
            method behind SHAP&apos;s PermutationExplainer), plus a per-minute occlusion test.
          </li>
          <li>
            <strong className="text-ink">Evaluation</strong>: whole capture days held out for testing. Thresholds come from validation blocks, never
            from the test days.
          </li>
          <li>
            <strong className="text-ink">Limits</strong>: probabilities are uncalibrated. Packet-level (PCAP) features are not used yet. CIC-IDS-2018
            attacks start abruptly, which limits early warning, and a model only knows the attack families it was trained on.
          </li>
        </ul>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] text-xs">
            <thead>
              <tr className="border-b border-line text-left text-muted">
                <th className="py-2 pr-3 font-medium">Dataset label contains</th>
                <th className="py-2 pr-3 font-medium">Stage</th>
                <th className="py-2 font-medium">Confidence</th>
              </tr>
            </thead>
            <tbody>
              {info.stage_mapping.map(r => (
                <tr key={r['label contains']} className="border-b border-line align-top" title={r.rationale}>
                  <td className="py-1.5 pr-3"><code>{r['label contains']}</code></td>
                  <td className="py-1.5 pr-3 text-ink">{r.stage}</td>
                  <td className="py-1.5">{r.confidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-muted">Exfiltration is never assigned: no CIC-IDS-2018 label supports it.</p>
        </div>
      </div>
    </details>
  );
}
