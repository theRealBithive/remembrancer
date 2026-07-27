import { expect, test } from "@playwright/test";

const SLUG = process.env.E2E_SLUG ?? "project-hail-mary-andy-weir";

test("index lists reviews with title, rating and runtime", async ({ page }) => {
  await page.goto("/");

  const first = page.locator("ol > li").first();
  await expect(first).toBeVisible();
  await expect(first.getByRole("heading", { level: 2 })).not.toBeEmpty();
  // Rating is exposed to assistive tech as text, not as star glyphs.
  await expect(first.getByText(/Rated \d\.\d out of 5/)).toBeAttached();
  // The listening line's runtime label.
  await expect(first.getByText(/\d+h( \d+m)?/)).toBeVisible();
});

test("review page renders content and both ratings", async ({ page }) => {
  await page.goto(`/reviews/${SLUG}`);

  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByText("Overall")).toBeVisible();
  await expect(page.getByText("Narration")).toBeVisible();
  await expect(page.locator(".prose")).not.toBeEmpty();
});

test("OpenGraph tags are in the server-returned HTML, not injected by JS", async ({
  request,
}) => {
  // Deliberately a raw fetch with no JS execution -- this is exactly what a Mastodon
  // instance does when it builds a preview card. If these tags only appeared after
  // hydration, every federated post would render as a bare link.
  const res = await request.get(`/reviews/${SLUG}`);
  expect(res.status()).toBe(200);
  const html = await res.text();

  expect(html).toMatch(/<meta property="og:title" content="[^"]+"/);
  expect(html).toMatch(/<meta property="og:description" content="[^"]+"/);
  expect(html).toMatch(/<meta property="og:image" content="https?:\/\/[^"]+"/);
  expect(html).toContain('<meta property="og:type" content="article"');
});

test("review body is sanitized: no script or event handlers reach the page", async ({
  page,
}) => {
  await page.goto(`/reviews/${SLUG}`);

  // Scoped to the element, not a substring of the document -- Next's own RSC payload
  // scripts live further down the page and would make a naive text search useless.
  const body = await page.locator(".prose").innerHTML();

  expect(body).not.toMatch(/<script/i);
  expect(body).not.toMatch(/<iframe/i);
  expect(body).not.toMatch(/\son[a-z]+\s*=/i);
  expect(await page.locator(".prose a[href^='javascript:']").count()).toBe(0);
});

test("legal page is reachable and linked from the footer everywhere", async ({ page }) => {
  for (const path of ["/", `/reviews/${SLUG}`]) {
    await page.goto(path);
    await expect(
      page.getByRole("contentinfo").getByRole("link", { name: /Impressum/i }),
    ).toBeVisible();
  }

  await page.goto("/legal");
  await expect(page.getByRole("heading", { name: "Impressum" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Datenschutzerklärung" })).toBeVisible();
});

test("unknown slug renders the not-found page rather than an error", async ({ page }) => {
  const res = await page.goto("/reviews/no-such-review");

  expect(res?.status()).toBe(404);
  await expect(page.getByText("Nothing here.")).toBeVisible();
});

test("the feed is linked and served as Atom", async ({ request }) => {
  const res = await request.get("/feed.xml");

  expect(res.status()).toBe(200);
  expect(res.headers()["content-type"]).toContain("xml");
  const xml = await res.text();
  expect(xml).toContain("<feed");
  expect(xml).not.toContain("example.com");
});

test("the Impressum is either complete or says it is not", async ({ page }) => {
  // §5 DDG contact details come from IMPRESSUM_* in the environment, so a deployment
  // can be missing them. What must never happen is a page that looks like a valid
  // Anbieterkennzeichnung while carrying nothing -- the failure has to be legible.
  await page.goto("/legal");

  const address = page.locator("address");
  const warning = page.getByText(/Fehlende Angaben/);

  if (await address.count()) {
    await expect(address).toContainText("E-Mail:");
    await expect(warning).toHaveCount(0);
  } else {
    await expect(warning).toBeVisible();
    await expect(warning).toContainText("IMPRESSUM_");
  }
});

test("the view counter appears after hydration and not in the served HTML", async ({
  page,
  request,
}) => {
  // The mirror image of the OpenGraph test: that one proves a preview fetcher sees
  // the card without running JS, this one proves the same fetcher is never counted.
  const raw = await (await request.get(`/reviews/${SLUG}`)).text();
  expect(raw).not.toMatch(/\d+ reads?/);

  await page.goto(`/reviews/${SLUG}`);

  await expect(page.getByText(/^\d+ reads?$/)).toBeVisible();
});

test("a reload does not count a second time", async ({ page }) => {
  await page.goto(`/reviews/${SLUG}`);
  const label = page.getByText(/^\d+ reads?$/);
  await expect(label).toBeVisible();
  const first = Number((await label.innerText()).split(" ")[0]);

  await page.reload();

  await expect(label).toBeVisible();
  expect(Number((await label.innerText()).split(" ")[0])).toBe(first);
});
