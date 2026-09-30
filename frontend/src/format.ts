const pad = (n: number) => String(n).padStart(2, '0');

// Backend timestamps are naive capture-local times; format them without timezone conversion.
export const toMs = (iso: string) => new Date(iso).getTime();

export const fmtTime = (v: string | number) => {
  const d = new Date(v);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

export const fmtDateTime = (v: string | number) => {
  const d = new Date(v);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${fmtTime(v)}`;
};

export const fmtDuration = (a: string | null, b: string | null) => {
  if (!a || !b) return '–';
  const mins = Math.round((toMs(b) - toMs(a)) / 60000);
  return mins >= 60 ? `${Math.floor(mins / 60)} h ${mins % 60} min` : `${mins} min`;
};

export const fmt3 = (v: number | null | undefined) => (v == null ? '–' : v.toFixed(3));

export const fmtLongDate = (v: string | number) =>
  new Date(v).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
