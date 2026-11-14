export const CLINIC_TZ = "Asia/Kolkata";
export const BOOKING_HORIZON_DAYS = 30;

export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** "09:30:00" -> "9:30 AM" */
export function formatTime(value: string): string {
  const [h, m] = value.split(":").map(Number);
  const suffix = h >= 12 ? "PM" : "AM";
  const hour = h % 12 === 0 ? 12 : h % 12;
  return `${hour}:${String(m).padStart(2, "0")} ${suffix}`;
}

/** Parse "YYYY-MM-DD" as a calendar date without timezone shifts. */
function parseISODate(value: string): Date {
  const [y, m, d] = value.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

export function toISODate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function dateParts(value: string) {
  const parts = new Intl.DateTimeFormat("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).formatToParts(parseISODate(value));
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return {
    weekday: get("weekday"),
    day: get("day"),
    month: get("month"),
    year: get("year"),
  };
}

/** "2030-01-07" -> "Mon, 7 Jan 2030" (independent of ICU punctuation). */
export function formatDate(value: string): string {
  const p = dateParts(value);
  return `${p.weekday}, ${p.day} ${p.month} ${p.year}`;
}

/** "2030-01-07" -> "Mon, 7 Jan" */
export function formatDateShort(value: string): string {
  const p = dateParts(value);
  return `${p.weekday}, ${p.day} ${p.month}`;
}

/** Today's calendar date in the clinic's timezone, as YYYY-MM-DD. */
export function clinicToday(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: CLINIC_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

export function addDays(value: string, days: number): string {
  const d = parseISODate(value);
  d.setUTCDate(d.getUTCDate() + days);
  return toISODate(d);
}

/** Monday = 0 .. Sunday = 6, matching the backend. */
export function weekdayIndex(value: string): number {
  return (parseISODate(value).getUTCDay() + 6) % 7;
}

export function formatFee(value: string): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(Number(value));
}

/** Compact weekday summary, e.g. [0,2,4] -> "Mon, Wed, Fri". */
export function workingDays(weekdays: number[]): string {
  return [...new Set(weekdays)]
    .sort((a, b) => a - b)
    .map((d) => WEEKDAYS[d])
    .join(", ");
}

/** Accepts 10-digit Indian mobiles with optional +91 / 0 prefix. */
export function isValidIndianMobile(raw: string): boolean {
  const digits = raw.replace(/[\s\-()]/g, "");
  return /^(\+91|91|0)?[6-9]\d{9}$/.test(digits);
}
