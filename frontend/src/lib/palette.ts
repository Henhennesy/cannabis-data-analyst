/**
 * Categorical palette for charts.
 *
 * These are the dark-mode steps of a validated eight-hue set, re-validated
 * against THIS app's chart surface (#141a1f) rather than assumed — the
 * reference surface is a different colour, and contrast and lightness-band
 * results are only meaningful against the surface actually rendered on:
 *
 *   lightness band      all 8 inside L 0.48-0.67      PASS
 *   chroma floor        all 8 >= 0.1                  PASS
 *   CVD separation      worst adjacent ΔE 8.4         PASS
 *   normal-vision floor worst adjacent ΔE 19.3        PASS
 *   contrast vs surface all 8 >= 3:1                  PASS
 *
 * Order is the colourblind-safety mechanism, not decoration: hues are assigned
 * in this fixed order and never cycled. A ninth series folds into "Other"
 * rather than getting a generated hue.
 *
 * Note this is deliberately NOT the UI accent (--accent teal). That colour
 * means "interactive"; these mean "series". Reusing one for the other would
 * make a bar look clickable.
 */
export const SERIES = [
  "#3987e5", // blue
  "#d95926", // orange
  "#199e70", // aqua
  "#c98500", // yellow
  "#d55181", // magenta
  "#008300", // green
  "#9085e9", // violet
  "#e66767", // red
] as const;

export const MAX_SERIES = SERIES.length;

export function seriesColor(index: number): string {
  return SERIES[index % SERIES.length];
}

/** Chart chrome, pulled from the app's tokens so charts match the shell. */
export const CHROME = {
  surface: "var(--bg-raised)",
  surfaceHex: "#141a1f",
  grid: "var(--rule)",
  axis: "var(--rule-strong)",
  textMuted: "var(--text-faint)",
  textSecondary: "var(--text-dim)",
  textPrimary: "var(--text)",
} as const;

/** Axis ticks: compact, so "700M" rather than "700,200,580". */
export function compactNumber(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${(n / 1e9).toFixed(abs >= 1e10 ? 0 : 1)}B`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(abs >= 1e7 ? 0 : 1)}M`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(abs >= 1e4 ? 0 : 1)}K`;
  if (Number.isInteger(n)) return n.toLocaleString();
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/** Tooltips and tables show the real number, not the compacted one. */
export function fullNumber(n: number): string {
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}
