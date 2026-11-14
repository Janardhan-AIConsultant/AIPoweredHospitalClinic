import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const PAGES = ["/", "/doctors", "/my-appointments", "/staff/login", "/privacy"];
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

async function settle(page: Page, path: string) {
  await page.goto(path);
  await page.waitForLoadState("networkidle");
}

async function violations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  return results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`);
}

for (const path of PAGES) {
  test(`no accessibility violations on ${path}`, async ({ page }) => {
    await settle(page, path);
    expect(await violations(page)).toEqual([]);
  });

  test(`no CSP violations or console errors on ${path}`, async ({ page }) => {
    const problems: string[] = [];
    page.on("console", (m) => {
      // The staff login page silently tries to restore a session; the browser logs that expected 401.
      const expected401 = m.text().includes("401") && path === "/staff/login";
      if (m.type() === "error" && !expected401) problems.push(m.text());
    });
    page.on("pageerror", (e) => problems.push(e.message));
    await page.addInitScript(() => {
      document.addEventListener("securitypolicyviolation", (e) =>
        console.error(`CSP violation: ${e.violatedDirective} ${e.blockedURI}`),
      );
    });
    await settle(page, path);
    expect(problems).toEqual([]);
  });
}

test("the booking page with the chat widget open is accessible", async ({ page }) => {
  await settle(page, "/doctors");
  await page.getByRole("link", { name: "Book an appointment with Dr. Anil Kumar" }).click();
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "Chat with us" }).click();
  expect(await violations(page)).toEqual([]);
});

test("pages are served with the security headers", async ({ page }) => {
  const res = await page.goto("/staff/login");
  const h = res!.headers();
  expect(h["content-security-policy"]).toContain("frame-ancestors 'none'");
  expect(h["content-security-policy"]).toContain("object-src 'none'");
  expect(h["x-content-type-options"]).toBe("nosniff");
  expect(h["x-frame-options"]).toBe("DENY");
  expect(h["referrer-policy"]).toBe("strict-origin-when-cross-origin");
  expect(h["x-powered-by"]).toBeUndefined();
  expect(h["cache-control"]).toContain("no-store"); // staff pages
});

test("the API only answers credentialed CORS for the frontend origin", async ({ request }) => {
  const evil = await request.fetch("http://localhost:8100/auth/me", { headers: { Origin: "https://evil.example" } });
  expect(evil.headers()["access-control-allow-origin"]).toBeUndefined();
  const ok = await request.fetch("http://localhost:8100/health", { headers: { Origin: "http://localhost:3100" } });
  expect(ok.headers()["access-control-allow-origin"]).toBe("http://localhost:3100");
  expect(ok.headers()["strict-transport-security"]).toBeTruthy();
});
