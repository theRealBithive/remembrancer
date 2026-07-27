import { createHmac, timingSafeEqual } from "node:crypto";
import { revalidatePath } from "next/cache";
import { NextResponse } from "next/server";

/**
 * On-demand ISR invalidation, called by Django when a review is published or edited.
 *
 * Not reachable from the internet: Caddy routes public /api/* to Django, so only the
 * internal docker network can reach this handler. The HMAC below is defence in depth.
 * The corollary is that Next can never own a public /api route.
 */
export const dynamic = "force-dynamic";

const SECRET = process.env.REVALIDATE_SECRET ?? "";

function signatureMatches(body: string, provided: string | null): boolean {
  if (!provided) return false;
  const expected = createHmac("sha256", SECRET).update(body).digest("hex");
  const a = Buffer.from(expected, "utf8");
  const b = Buffer.from(provided, "utf8");
  // timingSafeEqual throws on a length mismatch, so check that first -- length is
  // fixed for a hex digest and reveals nothing.
  return a.length === b.length && timingSafeEqual(a, b);
}

export async function POST(request: Request) {
  if (!SECRET) {
    return NextResponse.json({ error: "Revalidation is not configured." }, { status: 503 });
  }

  const body = await request.text();
  if (!signatureMatches(body, request.headers.get("x-signature"))) {
    return NextResponse.json({ error: "Bad signature." }, { status: 401 });
  }

  let paths: unknown;
  try {
    paths = JSON.parse(body)?.paths;
  } catch {
    return NextResponse.json({ error: "Malformed body." }, { status: 400 });
  }

  if (!Array.isArray(paths) || paths.some((p) => typeof p !== "string" || !p.startsWith("/"))) {
    return NextResponse.json({ error: "`paths` must be absolute paths." }, { status: 400 });
  }

  for (const path of paths as string[]) {
    revalidatePath(path);
  }

  return NextResponse.json({ revalidated: paths });
}
