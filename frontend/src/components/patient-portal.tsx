"use client";

import { useState } from "react";
import {
  ApiError,
  cancelMyAppointment,
  getMyAppointments,
  getSlots,
  requestOtp,
  rescheduleMyAppointment,
  verifyOtp,
} from "@/lib/api";
import {
  BOOKING_HORIZON_DAYS,
  addDays,
  clinicToday,
  formatDate,
  formatTime,
  isValidIndianMobile,
} from "@/lib/format";
import type { Appointment, Slot } from "@/lib/types";
import { Alert, Button, Card, Field, TextInput } from "./ui";

type Step = "phone" | "code" | "list";

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 429) return "Too many attempts. Please wait a minute and try again.";
    return e.message;
  }
  return "Something went wrong. Please try again.";
}

export function PatientPortal() {
  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [token, setToken] = useState("");
  const [items, setItems] = useState<Appointment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const sendCode = (e: React.FormEvent) => {
    e.preventDefault();
    if (!isValidIndianMobile(phone)) {
      setError("Enter the 10-digit mobile number you booked with.");
      return;
    }
    void run(async () => {
      await requestOtp(phone.trim());
      setNotice("If this number has appointments, we sent a 6-digit code on WhatsApp.");
      setStep("code");
    });
  };

  const verify = (e: React.FormEvent) => {
    e.preventDefault();
    if (!/^\d{6}$/.test(code.trim())) {
      setError("Enter the 6-digit code.");
      return;
    }
    void run(async () => {
      const t = await verifyOtp(phone.trim(), code.trim());
      setToken(t.access_token);
      setItems(await getMyAppointments(t.access_token));
      setNotice(null);
      setStep("list");
    });
  };

  const reload = async () => setItems(await getMyAppointments(token));

  return (
    <div className="space-y-4">
      {notice && <Alert tone="info">{notice}</Alert>}
      {error && <Alert>{error}</Alert>}

      {step === "phone" && (
        <Card>
          <form onSubmit={sendCode} noValidate className="space-y-4" aria-label="Find my appointments">
            <Field
              id="portal-phone"
              label="Mobile number"
              hint="The number you used when booking. We will send a code on WhatsApp."
            >
              <TextInput
                id="portal-phone"
                type="tel"
                autoComplete="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
              />
            </Field>
            <Button type="submit" disabled={busy}>
              {busy ? "Sending…" : "Send code"}
            </Button>
          </form>
        </Card>
      )}

      {step === "code" && (
        <Card>
          <form onSubmit={verify} noValidate className="space-y-4" aria-label="Verify code">
            <Field id="portal-code" label="Verification code" hint="Valid for 10 minutes.">
              <TextInput
                id="portal-code"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
              />
            </Field>
            <div className="flex gap-2">
              <Button type="submit" disabled={busy}>
                {busy ? "Checking…" : "Verify"}
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setStep("phone");
                  setCode("");
                  setError(null);
                  setNotice(null);
                }}
              >
                Use a different number
              </Button>
            </div>
          </form>
        </Card>
      )}

      {step === "list" && (
        <>
          {items.length === 0 && <Alert tone="info">No recent or upcoming appointments found.</Alert>}
          <ul className="space-y-3">
            {items.map((a) => (
              <li key={a.appointment_reference}>
                <AppointmentRow
                  appt={a}
                  token={token}
                  onChanged={async (message) => {
                    setNotice(message);
                    setError(null);
                    try {
                      await reload();
                    } catch (e) {
                      setError(errorText(e));
                    }
                  }}
                />
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function isUpcoming(a: Appointment): boolean {
  return (a.status === "CONFIRMED" || a.status === "PENDING") && a.appointment_date >= clinicToday();
}

function AppointmentRow({
  appt,
  token,
  onChanged,
}: {
  appt: Appointment;
  token: string;
  onChanged: (message: string) => Promise<void>;
}) {
  const [mode, setMode] = useState<"view" | "cancel" | "reschedule">("view");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function cancel() {
    setBusy(true);
    setError(null);
    try {
      await cancelMyAppointment(token, appt.appointment_reference);
      await onChanged(`Appointment ${appt.appointment_reference} was cancelled.`);
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-semibold">{appt.doctor_name}</p>
          <p className="text-sm text-muted">
            {appt.specialization} · {formatDate(appt.appointment_date)} at {formatTime(appt.start_time)}
          </p>
          <p className="text-xs text-muted">Reference {appt.appointment_reference}</p>
        </div>
        <span className="rounded-full bg-primary-soft px-2.5 py-1 text-xs font-medium">{appt.status}</span>
      </div>
      {error && <Alert>{error}</Alert>}

      {isUpcoming(appt) && mode === "view" && (
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => setMode("reschedule")}>
            Reschedule
          </Button>
          <Button variant="secondary" onClick={() => setMode("cancel")}>
            Cancel appointment
          </Button>
        </div>
      )}

      {mode === "cancel" && (
        <div className="space-y-2">
          <p className="text-sm">Cancel this appointment? This frees the slot for other patients.</p>
          <div className="flex gap-2">
            <Button onClick={cancel} disabled={busy}>
              {busy ? "Cancelling…" : "Yes, cancel it"}
            </Button>
            <Button variant="secondary" onClick={() => setMode("view")} disabled={busy}>
              Keep it
            </Button>
          </div>
        </div>
      )}

      {mode === "reschedule" && (
        <RescheduleForm
          appt={appt}
          token={token}
          onDone={(message) => onChanged(message)}
          onClose={() => setMode("view")}
        />
      )}
    </Card>
  );
}

function RescheduleForm({
  appt,
  token,
  onDone,
  onClose,
}: {
  appt: Appointment;
  token: string;
  onDone: (message: string) => Promise<void>;
  onClose: () => void;
}) {
  const today = clinicToday();
  const [date, setDate] = useState("");
  const [slots, setSlots] = useState<Slot[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function pickDate(value: string, keepError = false) {
    setDate(value);
    setSlots(null);
    if (!keepError) setError(null);
    if (!value) return;
    try {
      setSlots((await getSlots(appt.doctor_id, value)).slots);
    } catch (e) {
      setError(errorText(e));
    }
  }

  async function choose(slot: Slot) {
    setBusy(true);
    setError(null);
    try {
      const moved = await rescheduleMyAppointment(token, appt.appointment_reference, date, slot.start_time.slice(0, 5));
      await onDone(
        `Moved to ${formatDate(moved.appointment_date)} at ${formatTime(moved.start_time)}. New reference ${moved.appointment_reference}.`,
      );
    } catch (e) {
      setError(
        e instanceof ApiError && e.code === "slot_unavailable"
          ? "That time was just taken. Please pick another."
          : errorText(e),
      );
      setBusy(false);
      if (date) void pickDate(date, true);
    }
  }

  return (
    <div className="space-y-3 rounded-xl border border-border p-3">
      <Field id={`resched-${appt.appointment_reference}`} label="New date">
        <TextInput
          id={`resched-${appt.appointment_reference}`}
          type="date"
          min={today}
          max={addDays(today, BOOKING_HORIZON_DAYS)}
          value={date}
          onChange={(e) => void pickDate(e.target.value)}
        />
      </Field>
      {error && <Alert>{error}</Alert>}
      {slots && slots.length === 0 && <p className="text-sm text-muted">No open times on this date.</p>}
      {slots && slots.length > 0 && (
        <div className="flex flex-wrap gap-2" role="group" aria-label="Available times">
          {slots.map((s) => (
            <Button
              key={s.start_time}
              variant="secondary"
              disabled={busy}
              onClick={() => void choose(s)}
              className="px-3 py-1.5"
            >
              {formatTime(s.start_time)}
            </Button>
          ))}
        </div>
      )}
      <Button variant="secondary" onClick={onClose} disabled={busy}>
        Close
      </Button>
    </div>
  );
}
