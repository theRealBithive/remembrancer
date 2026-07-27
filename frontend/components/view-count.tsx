"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Counts this page view and shows the running total.
 *
 * Deliberately client-side. The page itself is statically cached, so a Mastodon
 * instance building a preview card gets HTML off the CDN-ish layer and never runs
 * this script -- which is exactly what keeps federation out of the numbers, and the
 * database out of the stampede.
 *
 * Nothing is rendered until the count comes back. Baking a number into the static
 * HTML would show every visitor a value up to an hour old and then visibly swap it.
 */
export function ViewCount({ slug }: { slug: string }) {
  const [count, setCount] = useState<number | null>(null);
  const fired = useRef(false);

  useEffect(() => {
    // React StrictMode runs effects twice in development. The server dedups anyway,
    // but sending it twice would make the local numbers a lie about production.
    if (fired.current) return;
    fired.current = true;

    const controller = new AbortController();

    fetch(`/api/reviews/${encodeURIComponent(slug)}/view`, {
      method: "POST",
      signal: controller.signal,
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (typeof data?.count === "number") setCount(data.count);
      })
      // No retry, no error UI. A lost count is worth strictly nothing; a retry loop
      // against a throttled endpoint is worth less than that.
      .catch(() => {});

    return () => controller.abort();
  }, [slug]);

  return (
    // The height is reserved so the line appearing does not shove the footer down.
    <p className="mt-12 h-4 font-mono text-[0.65rem] uppercase tracking-[0.16em] text-muted">
      {count !== null && `${count.toLocaleString("en")} ${count === 1 ? "read" : "reads"}`}
    </p>
  );
}
