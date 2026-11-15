import { expect, type APIRequestContext, type Page } from "@playwright/test";
import { API, PASSWORD } from "./support";

export const uniquePhone = () => "9" + String(Math.floor(Math.random() * 1e9)).padStart(9, "0");

const iso = (d: Date) => d.toISOString().slice(0, 10);

/** Book the first open slot of Dr. Anil Kumar through the public API. */
export async function bookViaApi(request: APIRequestContext, phone: string, name = "Asha Rao") {
  const doctors = await (await request.get(`${API}/doctors`)).json();
  const doctor = doctors.find((d: { full_name: string }) => d.full_name === "Dr. Anil Kumar");
  for (let i = 1; i <= 14; i++) {
    const day = iso(new Date(Date.now() + i * 86_400_000));
    const { slots } = await (await request.get(`${API}/doctors/${doctor.id}/slots?date=${day}`)).json();
    if (slots.length === 0) continue;
    const res = await request.post(`${API}/appointments`, {
      headers: { "Idempotency-Key": `e2e-${phone}-${day}` },
      data: {
        doctor_id: doctor.id,
        date: day,
        start_time: slots[0].start_time.slice(0, 5),
        patient_name: name,
        phone,
        notification_consent: true,
      },
    });
    expect(res.status()).toBe(201);
    return (await res.json()) as { appointment_reference: string; doctor_name: string };
  }
  throw new Error("no open slot in the next 14 days");
}

export async function staffLogin(page: Page, who: "admin" | "anil", password = PASSWORD) {
  await page.goto("/staff/login");
  await page.getByLabel("Email").fill(`${who}@e2e.test`);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}
