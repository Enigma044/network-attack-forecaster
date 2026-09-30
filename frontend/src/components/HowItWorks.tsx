import type { ReactNode } from 'react';
import Term from './Term';

export type StepState = 'idle' | 'active' | 'done';

export const STEPS: { id: string; title: string; icon: string; body: ReactNode; tech: ReactNode }[] = [
  {
    id: 'ingest',
    title: 'We read the traffic log',
    icon: '⇣',
    body: 'Every connection on the network leaves a line in a log. We load the file and check it makes sense before trusting it.',
    tech: <>CIC-IDS-2018 <Term k="flow">flow</Term> CSV · validation</>
  },
  {
    id: 'state',
    title: 'We take a snapshot every minute',
    icon: '▦',
    body: 'Thousands of connections become one short summary per minute: how busy, which ports, how chatty, how many hosts.',
    tech: <>1-minute <Term k="window">windows</Term> → 34-number <Term k="state">state</Term></>
  },
  {
    id: 'model',
    title: 'The model learns what comes next',
    icon: '◎',
    body: 'Having watched many days, it has learned how one minute usually turns into the next, both on quiet days and during attacks.',
    tech: <>LSTM <Term k="world model">world model</Term> · P(S_t+1 | S_t)</>
  },
  {
    id: 'simulate',
    title: 'It imagines the next 10 minutes',
    icon: '⟿',
    body: 'From the last 10 minutes it plays the future forward, 32 slightly different ways, and counts how often an attack shows up.',
    tech: <><Term k="rollout">Rollout</Term> · <Term k="K">K</Term> = 10 · <Term k="infiltration probability">probability</Term></>
  },
  {
    id: 'explain',
    title: 'It tells you why, and what kind',
    icon: '✦',
    body: 'It points to the traffic patterns that worried it most and guesses which stage of an intrusion this looks like.',
    tech: <><Term k="shapley">Shapley values</Term> · <Term k="ATT&CK stage">ATT&CK stage</Term></>
  }
];

export default function HowItWorks({ states }: { states: StepState[] }) {
  return (
    <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" aria-label="How the forecast is produced">
      {STEPS.map((s, i) => {
        const st = states[i] ?? 'idle';
        return (
          <li
            key={s.id}
            className={`relative flex flex-col rounded-2xl border p-4 transition-colors duration-300 ${
              st === 'active' ? 'border-lstm/70 bg-lstm/10' : st === 'done' ? 'border-good/40 bg-surface' : 'border-line bg-surface'
            }`}
          >
            <div className="flex items-start gap-2">
              <span
                className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm font-semibold ${
                  st === 'done' ? 'bg-good/20 text-good' : st === 'active' ? 'bg-lstm text-white' : 'bg-wash-strong text-ink-2'
                }`}
                aria-hidden="true"
              >
                {st === 'done' ? '✓' : i + 1}
              </span>
              <span className="text-sm font-semibold leading-snug text-ink">
                <span className="sr-only">Step {i + 1}: </span>
                {s.title}
              </span>
            </div>
            <p className="mt-2 flex-1 text-xs leading-relaxed text-ink-2">{s.body}</p>
            <p className="mt-3 border-t border-line pt-2 text-[11px] text-muted">{s.tech}</p>
            {st === 'active' && (
              <span className="absolute inset-x-4 bottom-1.5 h-0.5 overflow-hidden rounded-full bg-wash-strong" aria-hidden="true">
                <span className="block h-full w-1/3 animate-[slide_1.2s_ease-in-out_infinite] rounded-full bg-lstm" />
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}
