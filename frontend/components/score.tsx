import { stars } from "@/lib/format";

/**
 * Ratings as a typographic mark, not star glyphs (Decision 18). Set in the didone
 * display face, whose numerals are the point -- the "/5" stays small so the score
 * reads as a figure rather than a fraction.
 */
export function Score({
  halfSteps,
  size = "md",
}: {
  halfSteps: number;
  size?: "md" | "lg";
}) {
  const value = stars(halfSteps);
  const scale = size === "lg" ? "text-5xl sm:text-6xl" : "text-3xl sm:text-4xl";

  return (
    <p className="flex items-baseline gap-1 leading-none">
      <span className="sr-only">Rated {value} out of 5.</span>
      <span aria-hidden="true" className={`font-display ${scale}`}>
        {value}
      </span>
      <span aria-hidden="true" className="font-mono text-[0.7rem] text-muted">
        /5
      </span>
    </p>
  );
}
