import AnimatedList from './reactbits/AnimatedList/AnimatedList';
import type { Forecast } from '../api';
import { fmtTime, toMs } from '../format';
import { plainStage } from './StageChain';
import { isEarlyWarning } from './Timeline';

interface Props {
  alerts: Forecast[];
  windowSeconds: number;
  hasLabels: boolean;
  selectedRow: number | null;
  onSelect: (row: number) => void;
}

export default function AlertsPanel({ alerts, windowSeconds, hasLabels, selectedRow, onSelect }: Props) {
  if (alerts.length === 0) {
    return <p className="text-sm text-ink-2">The model never got worried enough to raise a flag on this day.</p>;
  }
  return (
    <AnimatedList
      items={alerts}
      ariaLabel="Moments the model raised a flag"
      maxHeightClass="max-h-[340px]"
      onItemSelect={a => onSelect(a.row)}
      renderItem={(a, _i, hovered) => {
        const active = a.row === selectedRow;
        const at = toMs(a.input_end) + windowSeconds * 1000;
        const early = isEarlyWarning(a);
        const outcome = !hasLabels || a.actual_any == null
          ? null
          : early
            ? { text: `warned early: attack came ${a.actual_first_attack_step} min later`, cls: 'text-good', mark: '✓' }
            : a.actual_any === 1
              ? { text: a.now_is_attack === 1 ? 'right: an attack was already under way' : 'right: an attack followed', cls: 'text-ink-2', mark: '✓' }
              : { text: 'false alarm: nothing happened', cls: 'text-warning', mark: '✕' };
        return (
          <div
            className={`rounded-xl border px-3 py-2.5 transition-colors ${
              active ? 'border-lstm/70 bg-lstm/10' : hovered ? 'border-line-strong bg-wash-strong' : 'border-line bg-surface-2'
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2 text-sm font-medium text-ink">
                <span className="text-raise" aria-hidden="true">▲</span>
                {fmtTime(at)}
              </span>
              <span className="tabular text-sm font-semibold text-ink">{Math.round(a.wm_any * 100)}%</span>
            </div>
            <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-wash-strong">
              <div className="h-full rounded-full bg-lstm" style={{ width: `${Math.round(a.wm_any * 100)}%` }} />
            </div>
            <div className="mt-1.5 flex flex-wrap items-center justify-between gap-x-3 text-xs">
              <span className="text-ink-2">{a.predicted_stage ? `Looks like ${plainStage(a.predicted_stage)}` : 'Kind of attack unclear'}</span>
              {outcome && (
                <span className={outcome.cls}>
                  <span aria-hidden="true">{outcome.mark}</span> {outcome.text}
                </span>
              )}
            </div>
          </div>
        );
      }}
    />
  );
}
