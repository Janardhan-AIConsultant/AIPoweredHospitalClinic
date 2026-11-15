"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  addLeave,
  cancelStaffAppointment,
  deleteLeave,
  getAdminDoctors,
  getAuditLogs,
  getLeave,
  getStaffAppointments,
  getStats,
  patchDoctor,
  setAppointmentStatus,
} from "@/lib/api";
import { clinicToday, formatDate, formatDateShort, formatFee, formatTime } from "@/lib/format";
import { useStaffSession } from "@/lib/staff-session";
import type { AdminDoctor, StaffRole } from "@/lib/types";
import { Alert, Button, Card, Field, TextInput, cx } from "../ui";

function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.status === 429 ? "Too many requests. Please wait a moment." : e.message;
  return "Something went wrong. Please try again.";
}

/** Load data once and on `reload()`. Stale data stays visible while a refetch is in flight. */
function useRemote<T>(fetcher: () => Promise<T>) {
  const [state, setState] = useState<{ data?: T; error?: string }>({});
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let alive = true;
    fetcher().then(
      (data) => alive && setState({ data }),
      (e) => alive && setState({ error: errorText(e) }),
    );
    return () => {
      alive = false;
    };
  }, [fetcher, version]);
  return { ...state, reload: () => setVersion((v) => v + 1) };
}

function Loading({ error, loading }: { error?: string; loading: boolean }) {
  if (error) return <Alert>{error}</Alert>;
  return loading ? (
    <p className="text-muted" role="status">
      Loading…
    </p>
  ) : null;
}

// ------------------------------------------------------------------ overview
export function OverviewPanel() {
  const { call } = useStaffSession();
  const fetcher = useCallback(() => call((t) => getStats(t)), [call]);
  const { data, error } = useRemote(fetcher);
  if (!data) return <Loading error={error} loading />;
  const n = data.notifications;
  const tiles: [string, number][] = [
    [`Appointments today (${formatDateShort(data.today)})`, data.today_total],
    ["Upcoming appointments", data.upcoming_active],
    ["Active doctors", data.active_doctors],
    ["Messages waiting", n.PENDING ?? 0],
    ["Messages retrying", n.FAILED ?? 0],
    ["Messages failed for good", n.DEAD ?? 0],
  ];
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {tiles.map(([label, value]) => (
          <Card key={label} className="p-4">
            <dt className="text-xs text-muted">{label}</dt>
            <dd className="mt-1 text-2xl font-bold">{value}</dd>
          </Card>
        ))}
      </dl>
      {Object.keys(data.today_by_status).length > 0 && (
        <p className="text-sm text-muted">
          Today:{" "}
          {Object.entries(data.today_by_status)
            .map(([s, c]) => `${c} ${s.toLowerCase()}`)
            .join(", ")}
        </p>
      )}
    </div>
  );
}

// -------------------------------------------------------------- appointments
const STATUSES = ["", "CONFIRMED", "COMPLETED", "NO_SHOW", "CANCELLED", "RESCHEDULED"];

export function AppointmentsPanel({ role }: { role: StaffRole }) {
  const { call } = useStaffSession();
  const [from, setFrom] = useState(clinicToday());
  const [status, setStatus] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  const fetcher = useCallback(
    () => call((t) => getStaffAppointments(t, role, { date_from: from, status })),
    [call, role, from, status],
  );
  const { data, error, reload } = useRemote(fetcher);

  async function act(reference: string, label: string, fn: (t: string) => Promise<unknown>) {
    setPending(reference);
    setActionError(null);
    setNotice(null);
    try {
      await call(fn);
      setNotice(`${reference}: ${label}.`);
      reload();
    } catch (e) {
      setActionError(errorText(e));
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <Field id="flt-from" label="From date">
          <TextInput id="flt-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </Field>
        <Field id="flt-status" label="Status">
          <select
            id="flt-status"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="w-full rounded-lg border border-border bg-surface px-3 py-2.5 text-sm"
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s ? s.replace("_", " ").toLowerCase() : "All"}
              </option>
            ))}
          </select>
        </Field>
      </div>
      {notice && <Alert tone="info">{notice}</Alert>}
      {actionError && <Alert>{actionError}</Alert>}
      {!data && <Loading error={error} loading />}
      {data && data.items.length === 0 && <Alert tone="info">No appointments match.</Alert>}
      {data && data.items.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Appointments</caption>
            <thead className="bg-primary-soft text-xs uppercase">
              <tr>
                <th scope="col" className="px-3 py-2">When</th>
                <th scope="col" className="px-3 py-2">Patient</th>
                {role === "ADMIN" && <th scope="col" className="px-3 py-2">Doctor</th>}
                <th scope="col" className="px-3 py-2">Status</th>
                <th scope="col" className="px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((a) => {
                const active = a.status === "CONFIRMED" || a.status === "PENDING";
                const busy = pending === a.appointment_reference;
                return (
                  <tr key={a.appointment_reference} className="border-t border-border align-top">
                    <td className="px-3 py-2 whitespace-nowrap">
                      {formatDateShort(a.appointment_date)}
                      <br />
                      <span className="text-muted">{formatTime(a.start_time)}</span>
                    </td>
                    <td className="px-3 py-2">
                      {a.patient_name}
                      <br />
                      <span className="text-xs text-muted">
                        {a.patient_phone_masked} · {a.appointment_reference}
                      </span>
                      {a.reason_for_visit && <p className="text-xs">{a.reason_for_visit}</p>}
                    </td>
                    {role === "ADMIN" && <td className="px-3 py-2">{a.doctor_name}</td>}
                    <td className="px-3 py-2">{a.status}</td>
                    <td className="px-3 py-2">
                      {active && (
                        <div className="flex flex-wrap gap-1.5">
                          <Button
                            variant="secondary"
                            className="px-2.5 py-1 text-xs"
                            disabled={busy}
                            aria-label={`Mark ${a.appointment_reference} completed`}
                            onClick={() =>
                              void act(a.appointment_reference, "marked completed", (t) =>
                                setAppointmentStatus(t, role, a.appointment_reference, "COMPLETED"),
                              )
                            }
                          >
                            Completed
                          </Button>
                          <Button
                            variant="secondary"
                            className="px-2.5 py-1 text-xs"
                            disabled={busy}
                            aria-label={`Mark ${a.appointment_reference} no-show`}
                            onClick={() =>
                              void act(a.appointment_reference, "marked no-show", (t) =>
                                setAppointmentStatus(t, role, a.appointment_reference, "NO_SHOW"),
                              )
                            }
                          >
                            No-show
                          </Button>
                          <CancelButton
                            reference={a.appointment_reference}
                            disabled={busy}
                            onConfirm={() =>
                              act(a.appointment_reference, "cancelled", (t) =>
                                cancelStaffAppointment(t, role, a.appointment_reference),
                              )
                            }
                          />
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {data && data.total > data.items.length && (
        <p className="text-xs text-muted">
          Showing the first {data.items.length} of {data.total}. Narrow the filters to see others.
        </p>
      )}
    </div>
  );
}

function CancelButton({
  reference,
  disabled,
  onConfirm,
}: {
  reference: string;
  disabled: boolean;
  onConfirm: () => Promise<void>;
}) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return (
      <Button
        variant="secondary"
        className="px-2.5 py-1 text-xs"
        disabled={disabled}
        aria-label={`Cancel ${reference}`}
        onClick={() => setAsking(true)}
      >
        Cancel
      </Button>
    );
  }
  return (
    <span className="flex gap-1.5">
      <Button
        className="px-2.5 py-1 text-xs"
        disabled={disabled}
        aria-label={`Confirm cancel ${reference}`}
        onClick={() => void onConfirm().finally(() => setAsking(false))}
      >
        Confirm cancel
      </Button>
      <Button variant="secondary" className="px-2.5 py-1 text-xs" onClick={() => setAsking(false)}>
        Keep
      </Button>
    </span>
  );
}

// ------------------------------------------------------------------- doctors
export function DoctorsPanel() {
  const { call } = useStaffSession();
  const fetcher = useCallback(() => call((t) => getAdminDoctors(t)), [call]);
  const { data, error, reload } = useRemote(fetcher);
  const [message, setMessage] = useState<string | null>(null);
  const [fail, setFail] = useState<string | null>(null);

  async function save(d: AdminDoctor, patch: { consultation_fee?: string; is_active?: boolean }) {
    setFail(null);
    setMessage(null);
    try {
      await call((t) => patchDoctor(t, d.id, patch));
      setMessage(`${d.full_name} updated.`);
      reload();
    } catch (e) {
      setFail(errorText(e));
    }
  }

  if (!data) return <Loading error={error} loading />;
  return (
    <div className="space-y-6">
      {message && <Alert tone="info">{message}</Alert>}
      {fail && <Alert>{fail}</Alert>}
      <ul className="space-y-3">
        {data.map((d) => (
          <li key={d.id}>
            <DoctorRow doctor={d} onSave={(p) => save(d, p)} />
          </li>
        ))}
      </ul>
      <h2 className="text-xl font-semibold">Leave</h2>
      <LeavePanel role="ADMIN" doctors={data} />
    </div>
  );
}

function DoctorRow({
  doctor,
  onSave,
}: {
  doctor: AdminDoctor;
  onSave: (p: { consultation_fee?: string; is_active?: boolean }) => Promise<void>;
}) {
  const [fee, setFee] = useState(String(Number(doctor.consultation_fee)));
  const dirty = fee !== String(Number(doctor.consultation_fee));
  const valid = fee !== "" && Number(fee) >= 0 && Number.isFinite(Number(fee));
  return (
    <Card className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <p className="font-semibold">
          {doctor.full_name} {!doctor.is_active && <span className="text-xs text-danger">(inactive)</span>}
        </p>
        <p className="text-sm text-muted">
          {doctor.specialization} · {formatFee(doctor.consultation_fee)} · {doctor.upcoming_appointments} upcoming
        </p>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <Field id={`fee-${doctor.id}`} label="Fee (₹)">
          <TextInput
            id={`fee-${doctor.id}`}
            type="number"
            min={0}
            value={fee}
            onChange={(e) => setFee(e.target.value)}
            className="w-28 rounded-lg border border-border bg-surface px-3 py-2 text-sm"
          />
        </Field>
        <Button
          variant="secondary"
          disabled={!dirty || !valid}
          aria-label={`Save fee for ${doctor.full_name}`}
          onClick={() => void onSave({ consultation_fee: fee })}
        >
          Save fee
        </Button>
        <Button
          variant="secondary"
          aria-label={`${doctor.is_active ? "Deactivate" : "Activate"} ${doctor.full_name}`}
          onClick={() => void onSave({ is_active: !doctor.is_active })}
        >
          {doctor.is_active ? "Deactivate" : "Activate"}
        </Button>
      </div>
    </Card>
  );
}

// --------------------------------------------------------------------- leave
export function LeavePanel({ role, doctors }: { role: StaffRole; doctors: AdminDoctor[] }) {
  const { call, user } = useStaffSession();
  const fetcher = useCallback(() => call((t) => getLeave(t, role)), [call, role]);
  const { data, error, reload } = useRemote(fetcher);
  const [doctorId, setDoctorId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [reason, setReason] = useState("");
  const [fail, setFail] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const names = new Map(doctors.map((d) => [d.id, d.full_name]));

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setFail(null);
    setMessage(null);
    const target = role === "ADMIN" ? doctorId : (user?.doctor_id ?? "");
    if (!target || !start || !end) {
      setFail("Choose a doctor, a start date and an end date.");
      return;
    }
    try {
      const leave = await call((t) =>
        addLeave(t, role, target, { start_date: start, end_date: end, reason: reason.trim() || null }),
      );
      setMessage(
        leave.affected_appointments > 0
          ? `Leave added. ${leave.affected_appointments} existing appointment(s) fall in this period and still need to be cancelled or moved.`
          : "Leave added.",
      );
      setStart("");
      setEnd("");
      setReason("");
      reload();
    } catch (err) {
      setFail(errorText(err));
    }
  }

  async function remove(id: string) {
    setFail(null);
    try {
      await call((t) => deleteLeave(t, role, id));
      reload();
    } catch (err) {
      setFail(errorText(err));
    }
  }

  return (
    <div className="space-y-4">
      {message && <Alert tone="info">{message}</Alert>}
      {fail && <Alert>{fail}</Alert>}
      <form onSubmit={add} noValidate aria-label="Add leave" className="flex flex-wrap items-end gap-3">
        {role === "ADMIN" && (
          <Field id="leave-doctor" label="Doctor">
            <select
              id="leave-doctor"
              value={doctorId}
              onChange={(e) => setDoctorId(e.target.value)}
              className="w-full rounded-lg border border-border bg-surface px-3 py-2.5 text-sm"
            >
              <option value="">Select…</option>
              {doctors.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.full_name}
                </option>
              ))}
            </select>
          </Field>
        )}
        <Field id="leave-start" label="From">
          <TextInput id="leave-start" type="date" min={clinicToday()} value={start} onChange={(e) => setStart(e.target.value)} />
        </Field>
        <Field id="leave-end" label="To">
          <TextInput id="leave-end" type="date" min={start || clinicToday()} value={end} onChange={(e) => setEnd(e.target.value)} />
        </Field>
        <Field id="leave-reason" label="Reason (optional)">
          <TextInput id="leave-reason" maxLength={255} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        <Button type="submit">Add leave</Button>
      </form>
      {!data && <Loading error={error} loading />}
      {data && data.length === 0 && <p className="text-sm text-muted">No upcoming leave.</p>}
      {data && data.length > 0 && (
        <ul className="space-y-2">
          {data.map((l) => (
            <li key={l.id} className={cx("flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2 text-sm")}>
              <span>
                {role === "ADMIN" && <strong>{names.get(l.doctor_id) ?? "Doctor"} · </strong>}
                {formatDate(l.start_date)} → {formatDate(l.end_date)}
                {l.reason ? ` · ${l.reason}` : ""}
              </span>
              <Button variant="secondary" className="px-2.5 py-1 text-xs" onClick={() => void remove(l.id)}>
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// --------------------------------------------------------------------- audit
export function AuditPanel() {
  const { call } = useStaffSession();
  const fetcher = useCallback(() => call((t) => getAuditLogs(t)), [call]);
  const { data, error } = useRemote(fetcher);
  if (!data) return <Loading error={error} loading />;
  if (data.length === 0) return <Alert tone="info">No audit entries yet.</Alert>;
  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Audit log</caption>
        <thead className="bg-primary-soft text-xs uppercase">
          <tr>
            <th scope="col" className="px-3 py-2">Time</th>
            <th scope="col" className="px-3 py-2">Who</th>
            <th scope="col" className="px-3 py-2">Action</th>
            <th scope="col" className="px-3 py-2">Target</th>
          </tr>
        </thead>
        <tbody>
          {data.map((e) => (
            <tr key={e.id} className="border-t border-border">
              <td className="px-3 py-2 whitespace-nowrap">{new Date(e.created_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })}</td>
              <td className="px-3 py-2">{e.actor_role ?? "system"}</td>
              <td className="px-3 py-2">{e.action}</td>
              <td className="px-3 py-2 text-xs text-muted">{e.entity_type}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
