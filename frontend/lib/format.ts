/** Ratings are stored as half-steps: 1–10 renders as 0.5–5.0. */
export function stars(halfSteps: number): string {
  const value = halfSteps / 2;
  return Number.isInteger(value) ? `${value}.0` : value.toFixed(1);
}

export function runtime(seconds: number | null): string | null {
  if (!seconds) return null;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  if (!hours) return `${minutes}m`;
  return minutes ? `${hours}h ${minutes}m` : `${hours}h`;
}

/**
 * Fraction of the listening line to draw, on a square-root scale.
 *
 * Linear would make a 40-hour outlier squash every normal book into a stub; sqrt
 * keeps a 6h novella and a 30h epic visibly different without one dominating.
 * Capped at 40h, floored so the shortest book still reads as a line.
 */
export function runtimeFraction(seconds: number | null): number {
  if (!seconds) return 0;
  const CAP_HOURS = 40;
  const hours = Math.min(seconds / 3600, CAP_HOURS);
  return Math.max(0.08, Math.sqrt(hours / CAP_HOURS));
}

export function listeningDate(iso: string | null): string | null {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString("en-GB", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}
