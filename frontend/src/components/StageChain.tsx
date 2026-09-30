import type { StageRule } from '../api';
import Term from './Term';

export const CHAIN: { stage: string; plain: string }[] = [
  { stage: 'Reconnaissance', plain: 'scouting the target' },
  { stage: 'Initial Access', plain: 'breaking in' },
  { stage: 'Lateral Movement', plain: 'spreading inside' },
  { stage: 'Command and Control', plain: 'taking remote control' },
  { stage: 'Exfiltration', plain: 'stealing data' }
];

export const plainStage = (s: string | null) => CHAIN.find(c => c.stage === s)?.plain ?? null;

interface Props {
  predicted: string | null;
  probability: number;
  actual: string | null;
  seen: string[];
  alert: boolean;
  rules: StageRule[];
}

export default function StageChain({ predicted, probability, actual, seen, alert, rules }: Props) {
  const rule = rules.find(r => r.stage === predicted);
  return (
    <div>
      <p className="mb-3 text-sm text-ink-2">
        Intrusions usually move through a few stages. Here&apos;s where the model thinks this one sits
        {actual ? ', and where the dataset says it really was' : ''}.
      </p>
      <ol className="flex flex-wrap items-stretch gap-1.5" aria-label="Attack stages">
        {CHAIN.map(({ stage, plain }, i) => {
          const isPred = stage === predicted;
          const isActual = stage === actual;
          const learned = seen.includes(stage);
          return (
            <li key={stage} className="flex items-center gap-1.5">
              <span
                className={`flex min-w-[8.5rem] flex-col rounded-lg border px-2.5 py-1.5 text-xs ${
                  isPred ? 'border-lstm bg-lstm/15 text-ink' : 'border-line bg-surface-2 text-ink-2'
                } ${isActual ? 'ring-2 ring-critical/70' : ''} ${learned ? '' : 'opacity-50'}`}
              >
                <span className="font-medium">{plain.charAt(0).toUpperCase() + plain.slice(1)}</span>
                <span className="text-[10px] text-muted">{stage}</span>
                {(isPred || isActual || !learned) && (
                  <span className={`mt-0.5 text-[10px] ${isPred ? 'text-lstm' : isActual ? 'text-critical' : 'text-muted'}`}>
                    {isPred ? `model's guess · ${(probability * 100).toFixed(0)}%` : isActual ? 'what really happened' : 'no examples to learn from'}
                  </span>
                )}
              </span>
              {i < CHAIN.length - 1 && <span className="text-muted" aria-hidden="true">→</span>}
            </li>
          );
        })}
      </ol>
      <p className="mt-3 text-sm text-ink-2">
        {predicted ? (
          <>
            Best guess: <span className="font-medium text-ink">{plainStage(predicted)}</span> (<Term k="ATT&CK stage">{predicted}</Term>).{' '}
            {rule?.rationale} We&apos;re {rule?.confidence === 'low' ? 'not very' : 'moderately'} sure this label-to-stage mapping is right.
          </>
        ) : alert ? (
          'Something looks wrong, but no single stage stands out enough (50% or more) to name it.'
        ) : (
          "We only guess a stage when the model is worried enough to raise a flag, and it isn't here."
        )}
      </p>
    </div>
  );
}
