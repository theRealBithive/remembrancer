import Link from "next/link";

export default function NotFound() {
  return (
    <div className="max-w-[var(--measure)] py-20">
      <p className="font-display text-4xl">Nothing here.</p>
      <p className="mt-4 text-lg text-muted">
        That review either hasn&rsquo;t been written yet or never existed.
      </p>
      <Link
        href="/"
        className="mt-8 inline-block font-mono text-[0.7rem] uppercase tracking-[0.16em] underline underline-offset-4"
      >
        Back to the reviews
      </Link>
    </div>
  );
}
