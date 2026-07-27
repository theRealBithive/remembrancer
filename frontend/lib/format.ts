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

/**
 * How long the book took, relative to its length.
 *
 * The pace is the point, not the elapsed time on its own: four days on a 14-hour book
 * is a different act from four days on a three-hour one. No start or finish date is
 * published — the judgement is interesting, the calendar is not.
 */
export function pace(days: number | null, hoursPerDay: number | null): string | null {
  if (days === null || hoursPerDay === null) return null;

  const span =
    days < 1
      ? "in a day"
      : days < 1.5
        ? "in a day"
        : days < 60
          ? `over ${Math.round(days)} days`
          : days < 365
            ? `over ${Math.round(days / 30.44)} months`
            : `over ${(days / 365.25).toFixed(1)} years`;

  const rate = hoursPerDay >= 10 ? Math.round(hoursPerDay) : Number(hoursPerDay.toFixed(1));
  return `${span}, ${rate} h/day`;
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
