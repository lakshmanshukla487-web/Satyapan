/** Design tokens: deep navy "ink" surfaces, a cyan→indigo brand accent, Inter + JetBrains Mono. */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: { 950: '#070b14', 900: '#0b1220', 800: '#111a2e', 700: '#1c2a44', 600: '#2b3b5c', 500: '#41557f' },
        brand: { 300: '#67e8f9', 400: '#22d3ee', 500: '#06b6d4', 600: '#0891b2', indigo: '#6366f1' },
      },
      fontFamily: {
        sans: ['Inter', '"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 0 0 rgba(255,255,255,0.04) inset, 0 12px 32px -14px rgba(0,0,0,0.65)',
        glow: '0 0 0 1px rgba(34,211,238,0.25), 0 10px 34px -10px rgba(34,211,238,0.35)',
        danger: '0 0 0 1px rgba(248,113,113,0.3), 0 10px 30px -10px rgba(248,113,113,0.35)',
      },
      keyframes: {
        fadeUp: { '0%': { opacity: '0', transform: 'translateY(6px)' }, '100%': { opacity: '1', transform: 'translateY(0)' } },
        ring: { '0%': { transform: 'scale(0.9)', opacity: '0.7' }, '100%': { transform: 'scale(1.6)', opacity: '0' } },
      },
      animation: { fadeUp: 'fadeUp .35s ease-out both', ring: 'ring 1.6s ease-out infinite' },
    },
  },
  plugins: [],
}
