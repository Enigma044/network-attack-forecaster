import type { ReactNode } from 'react';
import SpotlightCard from './reactbits/SpotlightCard/SpotlightCard';

interface PanelProps {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  step?: number | string;
  children: ReactNode;
  className?: string;
  id?: string;
}

export default function Panel({ title, subtitle, actions, step, children, className = '', id }: PanelProps) {
  return (
    <section id={id} className="scroll-mt-6">
      <SpotlightCard className={`card-shadow rounded-2xl bg-surface p-5 ${className}`} spotlightColor="rgba(57, 135, 229, 0.08)">
        {(title || actions) && (
          <div className="relative mb-4 flex flex-wrap items-start justify-between gap-3">
            <div className="max-w-3xl">
              {step !== undefined && (
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.15em] text-lstm">Step {step}</p>
              )}
              {title && <h2 className="text-lg font-semibold text-ink">{title}</h2>}
              {subtitle && <div className="mt-1 text-sm leading-relaxed text-ink-2">{subtitle}</div>}
            </div>
            {actions}
          </div>
        )}
        <div className="relative">{children}</div>
      </SpotlightCard>
    </section>
  );
}

export function StatusNote({ tone, label, children }: { tone: 'warning' | 'critical' | 'info' | 'good'; label: string; children: ReactNode }) {
  const styles = {
    warning: { icon: '⚠', ring: 'border-warning/40 bg-warning/10', text: 'text-warning' },
    critical: { icon: '✕', ring: 'border-critical/50 bg-critical/10', text: 'text-raise' },
    info: { icon: 'ℹ', ring: 'border-line bg-surface-2', text: 'text-ink-2' },
    good: { icon: '✓', ring: 'border-good/40 bg-good/10', text: 'text-good' }
  }[tone];
  return (
    <div className={`flex gap-3 rounded-xl border px-4 py-3 text-sm ${styles.ring}`} role={tone === 'critical' ? 'alert' : 'status'}>
      <span className={`font-semibold ${styles.text}`} aria-hidden="true">
        {styles.icon}
      </span>
      <div className="text-ink-2">
        <span className={`mr-1 font-semibold ${styles.text}`}>{label}.</span>
        {children}
      </div>
    </div>
  );
}

export function Callout({ children }: { children: ReactNode }) {
  return (
    <div className="flex gap-2 rounded-lg border-l-2 border-lstm/60 bg-lstm/5 px-3 py-2 text-xs leading-relaxed text-ink-2">
      <span aria-hidden="true" className="text-lstm">
        ➜
      </span>
      <div>{children}</div>
    </div>
  );
}
