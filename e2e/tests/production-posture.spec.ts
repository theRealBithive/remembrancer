/**
 * Checks that only mean anything when the stack runs the way it is deployed:
 * `DJANGO_DEBUG=false`, behind Caddy, over TLS.
 *
 * With DEBUG on, SECURE_SSL_REDIRECT, HSTS, secure cookies and CSRF_TRUSTED_ORIGINS
 * are all inert, so these assertions would pass vacuously. They skip instead.
 */
import { expect, test } from "@playwright/test";

const IS_TLS = (process.env.BASE_URL ?? "").startsWith("https://");

test.describe("production posture", () => {
  test.skip(!IS_TLS, "requires the stack behind TLS with DJANGO_DEBUG=false");

  test("Django answers directly instead of redirect-looping behind the proxy", async ({
    request,
  }) => {
    // SECURE_SSL_REDIRECT + a proxy that terminates TLS is an infinite loop unless
    // SECURE_PROXY_SSL_HEADER matches the header Caddy sets.
    const res = await request.get("/api/reviews", { maxRedirects: 0 });

    expect(res.status()).toBe(200);
  });

  test("HSTS is set, which also proves DEBUG is off", async ({ request }) => {
    const res = await request.get("/api/reviews");

    expect(res.headers()["strict-transport-security"]).toContain("max-age=");
  });

  // Needs the proxy's :80 published as well, which only CI does -- locally the
  // override maps the TLS port alone.
  test("plain HTTP is upgraded, never served", async ({ request }) => {
    test.skip(!process.env.HTTP_BASE_URL, "set HTTP_BASE_URL to exercise the upgrade");

    const res = await request.get(`${process.env.HTTP_BASE_URL}/`, { maxRedirects: 0 });

    expect([301, 308]).toContain(res.status());
  });
});

/**
 * The admin is the entire write path (Decision 7). Behind a proxy, Django 4+ rejects
 * its own login form outright unless CSRF_TRUSTED_ORIGINS carries the scheme -- a
 * failure that appears only in this posture and locks the operator out of everything.
 */
test.describe("admin login through the proxy", () => {
  const username = process.env.ADMIN_USER;
  const password = process.env.ADMIN_PASSWORD;
  const adminPath = process.env.ADMIN_PATH ?? "steward";

  test.skip(!IS_TLS || !username || !password, "needs TLS and admin credentials");

  async function csrfToken(request: import("@playwright/test").APIRequestContext) {
    const body = await (await request.get(`/${adminPath}/login/`)).text();
    return /name="csrfmiddlewaretoken" value="([^"]+)"/.exec(body)?.[1] ?? "";
  }

  test("succeeds with the site's own origin", async ({ request }) => {
    const token = await csrfToken(request);

    const res = await request.post(`/${adminPath}/login/`, {
      maxRedirects: 0,
      headers: {
        Origin: process.env.BASE_URL!,
        Referer: `${process.env.BASE_URL}/${adminPath}/login/`,
      },
      form: { csrfmiddlewaretoken: token, username: username!, password: password! },
    });

    expect(res.status(), "403 here means CSRF_TRUSTED_ORIGINS is missing the scheme")
      .toBe(302);
  });

  test("is refused from a foreign origin", async ({ request }) => {
    const token = await csrfToken(request);

    const res = await request.post(`/${adminPath}/login/`, {
      maxRedirects: 0,
      headers: { Origin: "https://evil.example", Referer: "https://evil.example/" },
      form: { csrfmiddlewaretoken: token, username: username!, password: password! },
    });

    expect(res.status()).toBe(403);
  });
});
