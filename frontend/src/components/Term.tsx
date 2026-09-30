import { useId, useState, type ReactNode } from 'react';
import { GLOSSARY } from '../glossary';

// A dotted-underlined term that shows its plain-language definition on hover or keyboard focus.
export default function Term({ k, children }: { k: keyof typeof GLOSSARY | string; children?: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const text = GLOSSARY[k];
  if (!text) return <>{children ?? k}</>;
  return (
    <span className="relative inline-block">
      <button
        type="button"
        aria-describedby={open ? id : undefined}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className="cursor-help border-b border-dotted border-ink-2/70 text-inherit leading-tight outline-none focus-visible:rounded focus-visible:ring-2 focus-visible:ring-lstm/60"
      >
        {children ?? k}
      </button>
      {open && (
        <span
          id={id}
          role="tooltip"
          className="absolute bottom-full left-1/2 z-50 mb-2 w-72 -translate-x-1/2 rounded-lg border border-line bg-surface-2 px-3 py-2 text-left text-xs font-normal leading-relaxed text-ink-2 shadow-xl"
        >
          {text}
        </span>
      )}
    </span>
  );
}
