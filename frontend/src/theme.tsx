import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';

export type ThemeMode = 'system' | 'light' | 'dark';
export type Resolved = 'light' | 'dark';

// Chart colours per mode (validated with the dataviz palette checks against each surface).
const PALETTES = {
  dark: {
    wm: '#3987e5', lr: '#d95926', persist: '#898781', critical: '#d03b3b', good: '#0ca30c', raise: '#e66767', lower: '#3987e5',
    grid: '#2c2c2a', axis: '#383835', tick: '#898781', neutral: '#c3c2b7', surface: '#1a1a19', cursor: '#c3c2b7', selection: '#ffffff',
    particles: ['#3987e5', '#5598e7', '#c3c2b7']
  },
  light: {
    wm: '#2a78d6', lr: '#eb6834', persist: '#898781', critical: '#c62f2f', good: '#008300', raise: '#e34948', lower: '#2a78d6',
    grid: '#ebe3d4', axis: '#d3c8b4', tick: '#71685c', neutral: '#554d44', surface: '#ffffff', cursor: '#554d44', selection: '#1c1814',
    particles: ['#2a78d6', '#1c5cab', '#86b6ef']
  }
} as const;

export type Palette = (typeof PALETTES)[Resolved];

interface ThemeCtx {
  mode: ThemeMode;
  resolved: Resolved;
  setMode: (m: ThemeMode) => void;
  palette: Palette;
}

const Ctx = createContext<ThemeCtx | null>(null);
const KEY = 'netforecast-theme';

function readStored(): ThemeMode {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'light' || v === 'dark' || v === 'system' ? v : 'system';
  } catch {
    return 'system';
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(readStored);
  const [systemDark, setSystemDark] = useState(() => window.matchMedia('(prefers-color-scheme: dark)').matches);

  useEffect(() => {
    const mql = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => setSystemDark(mql.matches);
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
  }, []);

  const resolved: Resolved = mode === 'system' ? (systemDark ? 'dark' : 'light') : mode;

  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
  }, [resolved]);

  const setMode = (m: ThemeMode) => {
    setModeState(m);
    try {
      localStorage.setItem(KEY, m);
    } catch {
      /* storage unavailable: the choice lasts for this visit only */
    }
  };

  return <Ctx.Provider value={{ mode, resolved, setMode, palette: PALETTES[resolved] }}>{children}</Ctx.Provider>;
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useTheme must be used inside ThemeProvider');
  return ctx;
}

/** One Light/Dark switch. Until it is clicked, the page follows the computer's own setting. */
export function ThemeToggle() {
  const { resolved, setMode } = useTheme();
  const isDark = resolved === 'dark';
  return (
    <div className="flex rounded-full border border-line bg-surface/80 p-0.5 backdrop-blur" role="radiogroup" aria-label="Colour theme">
      {(['light', 'dark'] as const).map(id => {
        const active = (id === 'dark') === isDark;
        return (
          <button
            key={id}
            role="radio"
            aria-checked={active}
            onClick={() => setMode(id)}
            title={`${id === 'dark' ? 'Dark' : 'Light'} theme`}
            className={`flex items-center gap-1 rounded-full px-2.5 py-1 text-xs transition-colors ${
              active ? 'bg-wash-strong text-ink' : 'text-muted hover:text-ink'
            }`}
          >
            <span aria-hidden="true">{id === 'dark' ? '☾' : '☀'}</span>
            <span className="hidden sm:inline">{id === 'dark' ? 'Dark' : 'Light'}</span>
          </button>
        );
      })}
    </div>
  );
}
