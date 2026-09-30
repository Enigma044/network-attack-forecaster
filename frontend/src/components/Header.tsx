import DecryptedText from './reactbits/DecryptedText/DecryptedText';
import Particles from './reactbits/Particles/Particles';
import { usePrefersReducedMotion } from '../hooks';
import { ThemeToggle, useTheme } from '../theme';

export default function Header() {
  const reduced = usePrefersReducedMotion();
  const { palette, resolved } = useTheme();
  return (
    <header className={`relative overflow-hidden border-b border-line ${resolved === 'light' ? 'bg-page' : 'bg-surface'}`}>
      {!reduced && (
        <div className={`pointer-events-none absolute inset-0 ${resolved === 'light' ? 'opacity-60' : 'opacity-70'}`} aria-hidden="true">
          <Particles
            key={resolved}
            particleColors={[...palette.particles]}
            particleCount={180}
            particleSpread={12}
            speed={0.06}
            particleBaseSize={70}
            alphaParticles
            disableRotation={false}
          />
        </div>
      )}
      <div className="relative mx-auto max-w-7xl px-4 py-8 sm:px-6">
        <div className="flex items-start justify-between gap-4">
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-muted">SIH 2026 · Problem 26153</p>
          <ThemeToggle />
        </div>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">
          {reduced ? (
            'Network Attack Forecaster'
          ) : (
            <DecryptedText
              text="Network Attack Forecaster"
              animateOn="view"
              sequential
              revealDirection="start"
              speed={35}
              className="text-ink"
              encryptedClassName="text-lstm"
            />
          )}
        </h1>
        <p className="mt-3 max-w-2xl text-lg text-ink">See trouble coming, not just after it lands.</p>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-2">
          We watch how a network&apos;s traffic changes minute by minute, imagine the next ten minutes, and tell you in plain words how likely
          an attack is, what kind it might be, and what made us think so.
        </p>
        <a href="#try" className="mt-5 inline-block rounded-lg bg-lstm px-4 py-2 text-sm font-semibold text-white hover:opacity-90">
          Try it on a real day of traffic ↓
        </a>
      </div>
    </header>
  );
}
