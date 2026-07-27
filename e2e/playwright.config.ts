import { defineConfig, devices } from "@playwright/test";

/**
 * Runs against an already-running stack (docker compose, or Django + `pnpm start`
 * locally). BASE_URL points at whichever origin serves the Next.js app.
 */
export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // "github" annotates the failing line in the diff; "html" is what CI uploads as an
  // artifact when something fails.
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.BASE_URL ?? "http://127.0.0.1:3000",
    trace: "on-first-retry",
    // Verifying locally means running the stack with DJANGO_DEBUG=false over TLS --
    // the only way HSTS, secure cookies and CSRF_TRUSTED_ORIGINS are actually live --
    // and Caddy signs `localhost` with its internal CA.
    ignoreHTTPSErrors: true,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
