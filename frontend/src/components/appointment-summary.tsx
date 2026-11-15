"use client";

import Link from "next/link";
import { useState } from "react";
import { formatDate, formatFee, formatTime } from "@/lib/format";
import type { Appointment } from "@/lib/types";
import { cx } from "./ui";

export const ARRIVE_EARLY_MINUTES = 10;

/** "9:00 AM – 9:30 AM". */
export function timeRange(a: Pick<Appointment, "start_time" | "end_time">): string {
  return `${formatTime(a.start_time)} – ${formatTime(a.end_time)}`;
}

/** The reference, big and copyable. It starts with the appointment date (YYYYMMDD). */
export function ReferenceBadge({ reference, compact = false }: { reference: string; compact?: boolean }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(reference);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard unavailable (insecure context): the reference stays visible to copy by hand */
    }
  }

  return (
    <div className="flex items-center justify-between gap-2 rounded-lg bg-primary-soft px-3 py-2">
      <div className="min-w-0">
        <p className="text-[11px] uppercase tracking-wide text-muted">Reference</p>
        <p
          data-testid="appointment-reference"
          className={cx("break-all font-mono font-bold tracking-wider", compact ? "text-base" : "text-2xl")}
        >
          {reference}
        </p>
      </div>
      <button
        type="button"
        onClick={() => void copy()}
        aria-label={`Copy reference ${reference}`}
        className="shrink-0 rounded-md border border-primary/40 bg-surface px-2.5 py-1 text-xs font-medium text-primary hover:bg-primary-soft"
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3 border-b border-border/60 py-1.5 last:border-0">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right font-medium">{value}</dd>
    </div>
  );
}

/** Everything a patient needs after booking, in one structured block. */
export function AppointmentDetails({ appt }: { appt: Appointment }) {
  return (
    <dl className="text-sm">
      <Row label="Doctor" value={appt.doctor_name} />
      <Row label="Specialty" value={appt.specialization} />
      <Row label="Date" value={formatDate(appt.appointment_date)} />
      <Row label="Time" value={timeRange(appt)} />
      <Row label="Patient" value={appt.patient_name} />
      <Row label="Consultation fee" value={formatFee(appt.consultation_fee)} />
      <Row
        label="WhatsApp updates"
        value={appt.notification_consent ? "Yes, confirmation and reminders" : "No"}
      />
    </dl>
  );
}

/** The chat's confirmation message: replaces the old one-line text. */
export function ConfirmationCard({ appt }: { appt: Appointment }) {
  return (
    <section aria-label="Appointment confirmed" className="min-w-[16rem] space-y-3">
      <p className="flex items-center gap-2 font-semibold text-primary">
        <span aria-hidden="true" className="flex h-5 w-5 items-center justify-center rounded-full bg-primary text-xs text-white dark:text-[#06201d]">
          ✓
        </span>
        Appointment confirmed
      </p>
      <ReferenceBadge reference={appt.appointment_reference} compact />
      <AppointmentDetails appt={appt} />
      <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted">
        <li>Please arrive {ARRIVE_EARLY_MINUTES} minutes early and quote your reference.</li>
        <li>
          To change or cancel, open{" "}
          <Link href="/my-appointments" className="font-medium text-primary underline">
            My appointments
          </Link>{" "}
          and verify your mobile number.
        </li>
      </ul>
    </section>
  );
}
