"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { ApiError, createAppointment, getSlots } from "@/lib/api";
import {
  BOOKING_HORIZON_DAYS,
  addDays,
  clinicToday,
  formatDate,
  formatDateShort,
  formatFee,
  formatTime,
  isValidIndianMobile,
  weekdayIndex,
} from "@/lib/format";
import type { Appointment, BookingRequest, Doctor, Slot } from "@/lib/types";
import { Alert, Button, Card, Field, TextArea, TextInput, cx } from "./ui";

export interface FormValues {
  patient_name: string;
  phone: string;
  email: string;
  reason: string;
  consent: boolean;
}

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function validateForm(v: FormValues): Record<string, string> {
  const errors: Record<string, string> = {};
  if (v.patient_name.trim().length < 2) {
    errors.patient_name = "Please enter the patient's full name.";
  }
  if (!isValidIndianMobile(v.phone)) {
    errors.phone = "Enter a valid 10-digit Indian mobile number.";
  }
  if (v.email.trim() && !EMAIL_RE.test(v.email.trim())) {
    errors.email = "Enter a valid email address or leave it blank.";
  }
  return errors;
}

export function buildPayload(
  doctorId: string,
  date: string,
  slot: Slot,
  v: FormValues,
): BookingRequest {
  return {
    doctor_id: doctorId,
    date,
    start_time: slot.start_time.slice(0, 5),
    patient_name: v.patient_name.trim(),
    phone: v.phone.trim(),
    email: v.email.trim() || null,
    reason_for_visit: v.reason.trim() || null,
    notification_consent: v.consent,
  };
}

interface SlotState {
  key: string;
  slots?: Slot[];
  error?: string;
}

const noopSubscribe = () => () => {};

const EMPTY: FormValues = {
  patient_name: "",
  phone: "",
  email: "",
  reason: "",
  consent: false,
};

export function BookingFlow({ doctor }: { doctor: Doctor }) {
  const workingWeekdays = useMemo(
    () => new Set(doctor.schedules.map((s) => s.weekday)),
    [doctor.schedules],
  );
  // Client-only value: avoids a server/client date mismatch during prerender.
  const today = useSyncExternalStore(
    noopSubscribe,
    () => clinicToday(),
    () => null,
  );
  const [chosenDate, setChosenDate] = useState<string | null>(null);
  const [slotState, setSlotState] = useState<SlotState | null>(null);
  const [selected, setSelected] = useState<{ date: string; slot: Slot } | null>(
    null,
  );
  const [reloadTick, setReloadTick] = useState(0);
  const [values, setValues] = useState<FormValues>(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [booked, setBooked] = useState<Appointment | null>(null);
  const keyRef = useRef<{ payload: string; key: string } | null>(null);

  const days = useMemo(() => {
    if (!today) return [];
    const out: string[] = [];
    for (let i = 0; i <= BOOKING_HORIZON_DAYS && out.length < 10; i++) {
      const d = addDays(today, i);
      if (workingWeekdays.has(weekdayIndex(d))) out.push(d);
    }
    return out;
  }, [today, workingWeekdays]);

  const date = chosenDate ?? days[0] ?? "";
  const fetchKey = `${date}#${reloadTick}`;
  const slot = selected && selected.date === date ? selected.slot : null;
  const slots = slotState?.key === fetchKey ? (slotState.slots ?? null) : null;
  const slotsError = slotState?.key === fetchKey ? (slotState.error ?? null) : null;

  useEffect(() => {
    if (!date) return;
    let cancelled = false;
    getSlots(doctor.id, date)
      .then((res) => {
        if (!cancelled) setSlotState({ key: fetchKey, slots: res.slots });
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setSlotState({
            key: fetchKey,
            error:
              e instanceof ApiError ? e.message : "Could not load time slots.",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [doctor.id, date, fetchKey]);

  const reloadSlots = () => setReloadTick((t) => t + 1);

  const update = <K extends keyof FormValues>(k: K, v: FormValues[K]) => {
    setValues((prev) => ({ ...prev, [k]: v }));
    setErrors((prev) => ({ ...prev, [k === "reason" ? "reason_for_visit" : k]: "" }));
  };

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!slot || submitting) return;
    const found = validateForm(values);
    setErrors(found);
    setFormError(null);
    if (Object.keys(found).length > 0) return;

    const payload = buildPayload(doctor.id, date, slot, values);
    const fingerprint = JSON.stringify(payload);
    // Same payload => same key, so a retry after a network failure cannot double-book.
    if (keyRef.current?.payload !== fingerprint) {
      keyRef.current = { payload: fingerprint, key: crypto.randomUUID() };
    }
    setSubmitting(true);
    try {
      setBooked(await createAppointment(payload, keyRef.current.key));
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "slot_unavailable") {
          setFormError(
            "Sorry, that time was just taken. Please choose another slot.",
          );
          setSelected(null);
          reloadSlots();
        } else if (err.status === 422) {
          setErrors({
            patient_name: err.fieldErrors.patient_name ?? "",
            phone: err.fieldErrors.phone ?? "",
            email: err.fieldErrors.email ?? "",
          });
          setFormError(err.message);
        } else {
          setFormError(err.message);
        }
      } else {
        setFormError("Something went wrong. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (booked) {
    return (
      <Confirmation
        appointment={booked}
        onAnother={() => {
          setBooked(null);
          setValues(EMPTY);
          setSelected(null);
          keyRef.current = null;
          reloadSlots();
        }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <section aria-labelledby="pick-date">
        <h2 id="pick-date" className="text-lg font-semibold">
          1. Choose a date
        </h2>
        {days.length === 0 && today ? (
          <p className="mt-2 text-sm text-muted">
            This doctor has no upcoming sessions.
          </p>
        ) : (
          <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Available dates">
            {days.map((d) => (
              <button
                key={d}
                type="button"
                aria-pressed={d === date}
                onClick={() => setChosenDate(d)}
                className={cx(
                  "rounded-lg border px-3 py-2 text-sm",
                  d === date
                    ? "border-primary bg-primary-soft font-semibold text-primary"
                    : "border-border bg-surface hover:bg-primary-soft",
                )}
              >
                {formatDateShort(d)}
              </button>
            ))}
          </div>
        )}
      </section>

      {!slot && formError && <Alert>{formError}</Alert>}

      {date && (
        <section aria-labelledby="pick-slot">
          <h2 id="pick-slot" className="text-lg font-semibold">
            2. Choose a time
          </h2>
          <div className="mt-3" aria-live="polite">
            {slotsError ? (
              <Alert>
                {slotsError}{" "}
                <button className="underline" onClick={reloadSlots}>
                  Retry
                </button>
              </Alert>
            ) : slots === null ? (
              <p className="text-sm text-muted">Loading available times…</p>
            ) : slots.length === 0 ? (
              <p className="text-sm text-muted">
                No times available on this day. Please pick another date.
              </p>
            ) : (
              <div className="flex flex-wrap gap-2" role="group" aria-label="Available times">
                {slots.map((s) => (
                  <button
                    key={s.start_time}
                    type="button"
                    aria-pressed={slot?.start_time === s.start_time}
                    onClick={() => setSelected({ date, slot: s })}
                    className={cx(
                      "rounded-lg border px-3 py-2 text-sm",
                      slot?.start_time === s.start_time
                        ? "border-primary bg-primary text-white dark:text-[#06201d]"
                        : "border-border bg-surface hover:bg-primary-soft",
                    )}
                  >
                    {formatTime(s.start_time)}
                  </button>
                ))}
              </div>
            )}
          </div>
        </section>
      )}

      {slot && (
        <form onSubmit={onSubmit} noValidate aria-labelledby="your-details">
          <Card className="space-y-4">
            <div>
              <h2 id="your-details" className="text-lg font-semibold">
                3. Your details
              </h2>
              <p className="text-sm text-muted">
                {formatDate(date)} at {formatTime(slot.start_time)} ·{" "}
                {formatFee(doctor.consultation_fee)}
              </p>
            </div>
            {formError && <Alert>{formError}</Alert>}
            <Field id="patient_name" label="Patient name" error={errors.patient_name}>
              <TextInput
                id="patient_name"
                autoComplete="name"
                maxLength={120}
                value={values.patient_name}
                error={errors.patient_name}
                onChange={(e) => update("patient_name", e.target.value)}
              />
            </Field>
            <Field
              id="phone"
              label="Mobile number"
              hint="Used only for your appointment. 10-digit Indian mobile."
              error={errors.phone}
            >
              <TextInput
                id="phone"
                type="tel"
                inputMode="tel"
                autoComplete="tel"
                maxLength={20}
                value={values.phone}
                error={errors.phone}
                onChange={(e) => update("phone", e.target.value)}
              />
            </Field>
            <Field id="email" label="Email (optional)" error={errors.email}>
              <TextInput
                id="email"
                type="email"
                autoComplete="email"
                maxLength={254}
                value={values.email}
                error={errors.email}
                onChange={(e) => update("email", e.target.value)}
              />
            </Field>
            <Field
              id="reason"
              label="Reason for visit (optional)"
              hint="Keep it brief. Do not include sensitive medical details."
            >
              <TextArea
                id="reason"
                rows={3}
                maxLength={300}
                value={values.reason}
                onChange={(e) => update("reason", e.target.value)}
              />
            </Field>
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-1"
                checked={values.consent}
                onChange={(e) => update("consent", e.target.checked)}
              />
              <span>
                Send my appointment confirmation and reminders on WhatsApp.
              </span>
            </label>
            <Button type="submit" disabled={submitting} className="w-full">
              {submitting ? "Booking…" : "Confirm appointment"}
            </Button>
          </Card>
        </form>
      )}
    </div>
  );
}

function Confirmation({
  appointment,
  onAnother,
}: {
  appointment: Appointment;
  onAnother: () => void;
}) {
  return (
    <Card className="space-y-4" >
      <div role="status">
        <h2 className="text-xl font-semibold text-primary">
          Appointment confirmed
        </h2>
        <p className="text-sm text-muted">
          Please save your reference number. You will need it to manage your
          appointment.
        </p>
      </div>
      <p className="rounded-lg bg-primary-soft px-4 py-3 text-center text-2xl font-bold tracking-widest">
        {appointment.appointment_reference}
      </p>
      <dl className="grid grid-cols-2 gap-3 text-sm">
        <Item label="Doctor" value={appointment.doctor_name} />
        <Item label="Specialty" value={appointment.specialization} />
        <Item label="Date" value={formatDate(appointment.appointment_date)} />
        <Item label="Time" value={formatTime(appointment.start_time)} />
        <Item label="Patient" value={appointment.patient_name} />
        <Item label="Fee" value={formatFee(appointment.consultation_fee)} />
      </dl>
      <p className="text-sm text-muted">
        Please arrive 10 minutes early.
      </p>
      <div className="flex gap-3">
        <Button variant="secondary" onClick={() => window.print()}>
          Print
        </Button>
        <Button variant="secondary" onClick={onAnother}>
          Book another
        </Button>
      </div>
    </Card>
  );
}

function Item({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}
