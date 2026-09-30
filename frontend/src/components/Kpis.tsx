import CountUp from './reactbits/CountUp/CountUp';
import SpotlightCard from './reactbits/SpotlightCard/SpotlightCard';

export interface Kpi {
  label: string;
  value: number;
  percent?: boolean;
  hint?: string;
}

function Tile({ label, value, percent, hint }: Kpi) {
  const to = percent ? Math.round(value * 100) : value;
  return (
    <SpotlightCard className="card-shadow rounded-2xl bg-surface p-4" spotlightColor="rgba(57, 135, 229, 0.12)">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-1 text-3xl font-semibold text-ink">
        <span aria-hidden="true">
          <CountUp to={to} from={0} duration={0.8} separator="," />
          {percent && '%'}
        </span>
        <span className="sr-only">{percent ? `${to}%` : value.toLocaleString()}</span>
      </p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </SpotlightCard>
  );
}

export default function Kpis({ items }: { items: Kpi[] }) {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
      {items.map(k => (
        <Tile key={k.label} {...k} />
      ))}
    </div>
  );
}
