import { expect, test, type Page } from "@playwright/test";
import { API } from "./support";
import { bookViaApi, uniquePhone } from "./helpers";

/** Click the first date that actually has open times. */
async function pickFirstOpenSlot(page: Page) {
  const dates = page.getByRole("group", { name: "Available dates" }).getByRole("button");
  const times = page.getByRole("group", { name: "Available times" }).getByRole("button");
  await expect(dates.first()).toBeVisible(); // the page streams in and computes dates on the client
  const count = await dates.count();
  for (let i = 0; i < count; i++) {
    await dates.nth(i).click();
    if (await times.first().isVisible({ timeout: 5_000 }).catch(() => false)) break;
  }
  await times.first().click();
}

test("a guest can find a doctor and book an appointment", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Find a doctor" }).first().click();
  await expect(page.getByRole("heading", { name: "Find a doctor" })).toBeVisible();
  await page.getByRole("link", { name: "Book an appointment with Dr. Anil Kumar" }).click();
  await pickFirstOpenSlot(page);

  await page.getByLabel("Patient name").fill("E2E Guest");
  await page.getByLabel("Mobile number").fill(uniquePhone());
  await page.getByLabel("No, thanks").check();
  await page.getByRole("button", { name: "Confirm appointment" }).click();

  await expect(page.getByText("Please save your reference number")).toBeVisible();
  await expect(page.getByTestId("appointment-reference")).toBeVisible();
  await expect(page.getByText("Dr. Anil Kumar").first()).toBeVisible();
});

test("validation errors are shown and nothing is booked", async ({ page }) => {
  await page.goto("/doctors");
  await page.getByRole("link", { name: "Book an appointment with Dr. Anil Kumar" }).click();
  await pickFirstOpenSlot(page);
  await page.getByRole("button", { name: "Confirm appointment" }).click();
  await expect(page.getByText("Please enter the patient's full name.")).toBeVisible();
  await expect(page.getByText(/valid 10-digit Indian mobile/)).toBeVisible();
});

test("a patient verifies with a WhatsApp code, reschedules, then cancels", async ({ page, request }) => {
  const phone = uniquePhone();
  const appt = await bookViaApi(request, phone, "Portal Patient");

  await page.goto("/my-appointments");
  await page.getByLabel("Mobile number").fill(phone);
  await page.getByRole("button", { name: "Send code" }).click();
  await expect(page.getByText(/we sent a 6-digit code/)).toBeVisible();

  // a wrong code is refused
  await page.getByLabel("Verification code").fill("000000");
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByText("Invalid or expired code.")).toBeVisible();

  const { code } = await (await request.get(`${API}/__e2e__/last-otp?phone=${phone}`)).json();
  expect(code).toMatch(/^\d{6}$/);
  await page.getByLabel("Verification code").fill(code);
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByText(`Reference ${appt.appointment_reference}`, { exact: true })).toBeVisible();

  // reschedule to another day that has open times
  await page.getByRole("button", { name: "Reschedule" }).click();
  const times = page.getByRole("group", { name: "Available times" }).getByRole("button");
  for (let i = 8; i <= 20; i++) {
    const day = new Date(Date.now() + i * 86_400_000).toISOString().slice(0, 10);
    await page.getByLabel("New date").fill(day);
    if (await times.first().isVisible({ timeout: 4_000 }).catch(() => false)) break;
  }
  await times.first().click();
  const moved = page.getByText(/New reference (\d{8}-\d{4,})/);
  await expect(moved).toBeVisible();
  const newRef = /New reference (\d{8}-\d{4,})/.exec((await moved.textContent()) ?? "")![1];
  await expect(page.getByText(`Reference ${newRef}`, { exact: true })).toBeVisible();

  // cancel it
  await page.getByRole("button", { name: "Cancel appointment" }).click();
  await page.getByRole("button", { name: "Yes, cancel it" }).click();
  await expect(page.getByText(`Appointment ${newRef} was cancelled.`)).toBeVisible();
});

test("an unknown number gets no hint and no list", async ({ page }) => {
  await page.goto("/my-appointments");
  await page.getByLabel("Mobile number").fill(uniquePhone());
  await page.getByRole("button", { name: "Send code" }).click();
  await expect(page.getByText(/If this number has appointments/)).toBeVisible();
  await page.getByLabel("Verification code").fill("123456");
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByText("Invalid or expired code.")).toBeVisible();
});
