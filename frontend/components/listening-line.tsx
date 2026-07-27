import { pace as formatPace, runtime, runtimeFraction } from "@/lib/format";

/**
 * The signature element: a rule whose length is proportional to how long the book
 * took to listen to. It is the one thing on the page a print-book review site
 * couldn't have, and it carries real information rather than decorating the row --
 * a 30-hour epic is visibly longer than a 6-hour novella.
 */
export function ListeningLine({
  seconds,
  narration,
  daysToFinish = null,
  hoursPerDay = null,
}: {
  seconds: number | null;
  narration?: string | null;
  daysToFinish?: number | null;
  hoursPerDay?: number | null;
}) {
  const label = runtime(seconds);
  if (!label) return null;

  // How fast it went down. Sits on the same rule as the length, because the two only
  // mean anything together.
  const spent = formatPace(daysToFinish, hoursPerDay);

  return (
    <div className="mt-3 flex items-center gap-3 text-muted">
      <span
        aria-hidden="true"
        className="h-px bg-current"
        style={{ width: `${runtimeFraction(seconds) * 100}%`, maxWidth: "22rem" }}
      />
      <span className="font-mono text-[0.7rem] tracking-[0.08em] whitespace-nowrap">
        {label}
        {spent && <span className="opacity-70"> · {spent}</span>}
      </span>
      {narration && (
        <span className="ml-auto font-mono text-[0.7rem] tracking-[0.08em] whitespace-nowrap">
          voice {narration}
        </span>
      )}
    </div>
  );
}
