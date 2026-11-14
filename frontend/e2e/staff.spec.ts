import { expect, test } from "@playwright/test";
import { BROWSER_API, COOKIE_PATH } from "./support";
import { bookViaApi, staffLogin, uniquePhone } from "./helpers";

test("anonymous visitors are sent to the staff login", async ({ page }) => {
  await page.goto("/staff");
  await expect(page).toHaveURL(/\/staff\/login$/);
});

test("wrong credentials show a generic error", async ({ page }) => {
  await staffLogin(page, "admin", "Wrong-Passw0rd-1");
  await expect(page.getByText("Invalid email or password.")).toBeVisible();
  await expect(page).toHaveURL(/\/staff\/login$/);
});

test("admin signs in, sees masked patient data, cancels, survives a reload and signs out", async ({
  page,
  request,
}) => {
  const phone = uniquePhone();
  const appt = await bookViaApi(request, phone, "Staff View Patient");

  await staffLogin(page, "admin");
  await expect(page.getByRole("heading", { name: "Admin dashboard" })).toBeVisible();
  await expect(page.getByText("Upcoming appointments")).toBeVisible();

  await page.getByRole("tab", { name: "Appointments" }).click();
  const row = page.getByRole("row").filter({ hasText: appt.appointment_reference });
  await expect(row).toBeVisible();
  await expect(row).toContainText("Staff View Patient");
  await expect(row).not.toContainText(phone); // the phone number is masked for staff

  // the HttpOnly refresh cookie restores the session after a full reload
  await page.reload();
  await expect(page.getByRole("heading", { name: "Admin dashboard" })).toBeVisible();

  await page.getByRole("tab", { name: "Appointments" }).click();
  await page.getByRole("button", { name: `Cancel ${appt.appointment_reference}` }).click();
  await page.getByRole("button", { name: `Confirm cancel ${appt.appointment_reference}` }).click();
  await expect(page.getByText(`${appt.appointment_reference}: cancelled.`)).toBeVisible();

  await page.getByRole("tab", { name: "Audit log" }).click();
  await expect(page.getByRole("cell", { name: "appointment.cancel" }).first()).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/staff\/login$/);
  await page.goto("/staff");
  await expect(page).toHaveURL(/\/staff\/login$/); // the refresh cookie was revoked
});

test("the refresh cookie is HttpOnly and no token is kept in browser storage", async ({ page, context }) => {
  await staffLogin(page, "admin");
  await expect(page.getByRole("heading", { name: "Admin dashboard" })).toBeVisible();
  const cookie = (await context.cookies()).find((c) => c.name === "refresh_token");
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.path).toBe(COOKIE_PATH);
  const stored = await page.evaluate(
    () => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }),
  );
  expect(stored).not.toMatch(/eyJ/); // no JWT in web storage
  expect(await page.evaluate(() => document.cookie)).not.toContain("refresh_token");
});

test("a doctor sees only their own dashboard and appointments", async ({ page, request }) => {
  const appt = await bookViaApi(request, uniquePhone(), "Doctor View Patient");
  await staffLogin(page, "anil");
  await expect(page.getByRole("heading", { name: "Doctor dashboard" })).toBeVisible();
  await expect(page.getByRole("tab")).toHaveText(["My appointments", "My leave"]);
  await expect(page.getByRole("row").filter({ hasText: appt.appointment_reference })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Doctor" })).toHaveCount(0);
});

test("a doctor token is refused by the admin API", async ({ page }) => {
  await staffLogin(page, "anil");
  await expect(page.getByRole("heading", { name: "Doctor dashboard" })).toBeVisible();
  const status = await page.evaluate(async (base) => {
    const refreshed = await fetch(`${base}/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: { "X-CSRF-Token": "1" },
    }).then((r) => r.json());
    const r = await fetch(`${base}/admin/stats`, {
      headers: { Authorization: `Bearer ${refreshed.access_token}` },
    });
    return r.status;
  }, BROWSER_API);
  expect(status).toBe(403);
});
