import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  BookingFlow,
  buildPayload,
  validateForm,
} from "@/components/booking-flow";
import { DoctorBrowser, filterDoctors } from "@/components/doctor-browser";
import { ApiError } from "@/lib/api";
import type { Doctor, Specialization } from "@/lib/types";

const api = vi.hoisted(() => ({
  getSlots: vi.fn(),
  createAppointment: vi.fn(),
}));

vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  getSlots: api.getSlots,
  createAppointment: api.createAppointment,
}));

const spec: Specialization = { id: "s1", name: "Cardiologist", description: null };
const spec2: Specialization = { id: "s2", name: "Pediatrician", description: null };

function doctor(overrides: Partial<Doctor> = {}): Doctor {
  return {
    id: "d1",
    full_name: "Dr. Rahul Reddy",
    qualifications: null,
    experience_years: 15,
    consultation_fee: "1000.00",
    bio: null,
    photo_url: null,
    specialization: spec,
    // Open every weekday so the first date chip is always available.
    schedules: [0, 1, 2, 3, 4, 5, 6].map((weekday) => ({
      weekday,
      session_type: "MORNING" as const,
      start_time: "09:00:00",
      end_time: "12:00:00",
      break_start: null,
      break_end: null,
    })),
    ...overrides,
  };
}

const SLOTS = {
  doctor_id: "d1",
  date: "x",
  slots: [
    { start_time: "09:00:00", end_time: "09:30:00" },
    { start_time: "09:30:00", end_time: "10:00:00" },
  ],
};

const APPOINTMENT = {
  appointment_reference: "20300107-0001",
  doctor_id: "d1",
  doctor_name: "Dr. Rahul Reddy",
  specialization: "Cardiologist",
  appointment_date: "2030-01-07",
  start_time: "09:00:00",
  end_time: "09:30:00",
  consultation_fee: "1000.00",
  status: "CONFIRMED",
  patient_name: "Asha Rao",
  reason_for_visit: null,
};

beforeEach(() => {
  api.getSlots.mockReset().mockResolvedValue(SLOTS);
  api.createAppointment.mockReset();
  vi.stubGlobal("crypto", { randomUUID: () => "uuid-1" });
});
afterEach(() => vi.unstubAllGlobals());

async function pickSlotAndFill(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "9:00 AM" }));
  await user.type(screen.getByLabelText("Patient name"), "Asha Rao");
  await user.type(screen.getByLabelText("Mobile number"), "9876543210");
  await user.click(screen.getByLabelText("No, thanks"));
}

describe("validation helpers", () => {
  it("flags invalid fields and passes valid ones", () => {
    const bad = validateForm({
      patient_name: " ",
      phone: "123",
      email: "nope",
      reason: "",
      consent: null,
    });
    expect(Object.keys(bad).sort()).toEqual(["consent", "email", "patient_name", "phone"]);
    expect(
      validateForm({
        patient_name: "Asha",
        phone: "9876543210",
        email: "",
        reason: "",
        consent: true,
      }),
    ).toEqual({});
  });

  it("treats an explicit No as a valid answer and never opts in by default", () => {
    const base = { patient_name: "Asha", phone: "9876543210", email: "", reason: "" };
    expect(validateForm({ ...base, consent: false })).toEqual({});
    const slot = { start_time: "09:00:00", end_time: "09:30:00" };
    expect(buildPayload("d1", "2030-01-07", slot, { ...base, consent: false }).notification_consent).toBe(false);
    expect(buildPayload("d1", "2030-01-07", slot, { ...base, consent: null }).notification_consent).toBe(false);
  });

  it("builds a trimmed payload with HH:MM time", () => {
    const p = buildPayload(
      "d1",
      "2030-01-07",
      { start_time: "09:00:00", end_time: "09:30:00" },
      { patient_name: " Asha ", phone: " 98765 43210 ", email: "", reason: " ", consent: true },
    );
    expect(p).toMatchObject({
      start_time: "09:00",
      patient_name: "Asha",
      email: null,
      reason_for_visit: null,
      notification_consent: true,
    });
  });
});

describe("BookingFlow", () => {
  it("shows slots, validates, then books and shows the reference", async () => {
    api.createAppointment.mockResolvedValue(APPOINTMENT);
    const user = userEvent.setup();
    render(<BookingFlow doctor={doctor()} />);

    await user.click(await screen.findByRole("button", { name: "9:00 AM" }));
    await user.click(screen.getByRole("button", { name: "Confirm appointment" }));
    expect(await screen.findByText(/full name/i)).toBeInTheDocument();
    expect(api.createAppointment).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText("Patient name"), "Asha Rao");
    await user.type(screen.getByLabelText("Mobile number"), "9876543210");
    await user.click(screen.getByLabelText("No, thanks"));
    await user.click(screen.getByRole("button", { name: "Confirm appointment" }));

    expect(await screen.findByText("20300107-0001")).toBeInTheDocument();
    expect(screen.getByText("Appointment confirmed")).toBeInTheDocument();
    const [payload, key] = api.createAppointment.mock.calls[0];
    expect(payload).toMatchObject({ doctor_id: "d1", start_time: "09:00", phone: "9876543210" });
    expect(key).toBe("uuid-1");
  });

  it("reuses the idempotency key when retrying the same request", async () => {
    let n = 0;
    vi.stubGlobal("crypto", { randomUUID: () => `uuid-${++n}` });
    api.createAppointment
      .mockRejectedValueOnce(new ApiError("down", 0, "network_error"))
      .mockResolvedValueOnce(APPOINTMENT);
    const user = userEvent.setup();
    render(<BookingFlow doctor={doctor()} />);
    await pickSlotAndFill(user);

    await user.click(screen.getByRole("button", { name: "Confirm appointment" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("down");
    await user.click(screen.getByRole("button", { name: "Confirm appointment" }));
    await screen.findByText("20300107-0001");
    expect(api.createAppointment.mock.calls[0][1]).toBe(api.createAppointment.mock.calls[1][1]);
  });

  it("uses a new idempotency key when the details change", async () => {
    let n = 0;
    vi.stubGlobal("crypto", { randomUUID: () => `uuid-${++n}` });
    api.createAppointment
      .mockRejectedValueOnce(new ApiError("down", 0, "network_error"))
      .mockResolvedValueOnce(APPOINTMENT);
    const user = userEvent.setup();
    render(<BookingFlow doctor={doctor()} />);
    await pickSlotAndFill(user);
    await user.click(screen.getByRole("button", { name: "Confirm appointment" }));
    await screen.findByRole("alert");
    await user.type(screen.getByLabelText("Patient name"), " K");
    await user.click(screen.getByRole("button", { name: "Confirm appointment" }));
    await screen.findByText("20300107-0001");
    expect(api.createAppointment.mock.calls[0][1]).not.toBe(api.createAppointment.mock.calls[1][1]);
  });

  it("reloads slots and clears the selection when the slot was just taken", async () => {
    api.createAppointment.mockRejectedValue(
      new ApiError("The selected time slot is no longer available.", 409, "slot_unavailable"),
    );
    const user = userEvent.setup();
    render(<BookingFlow doctor={doctor()} />);
    await pickSlotAndFill(user);
    const before = api.getSlots.mock.calls.length;
    await user.click(screen.getByRole("button", { name: "Confirm appointment" }));

    expect(await screen.findByText(/just taken/i)).toBeInTheDocument();
    await waitFor(() => expect(api.getSlots.mock.calls.length).toBeGreaterThan(before));
  });

  it("maps server field errors back onto the form", async () => {
    api.createAppointment.mockRejectedValue(
      new ApiError("Invalid request.", 422, "validation_error", { phone: "Invalid Indian mobile number" }),
    );
    const user = userEvent.setup();
    render(<BookingFlow doctor={doctor()} />);
    await pickSlotAndFill(user);
    await user.click(screen.getByRole("button", { name: "Confirm appointment" }));
    expect(await screen.findByText("Invalid Indian mobile number")).toBeInTheDocument();
  });

  it("explains when a day has no times and when loading fails", async () => {
    api.getSlots.mockResolvedValueOnce({ ...SLOTS, slots: [] });
    const { unmount } = render(<BookingFlow doctor={doctor()} />);
    expect(await screen.findByText(/No times available/i)).toBeInTheDocument();
    unmount();

    api.getSlots.mockRejectedValueOnce(new ApiError("Service down", 503, "service_unavailable"));
    render(<BookingFlow doctor={doctor()} />);
    expect(await screen.findByText(/Service down/)).toBeInTheDocument();
  });

  it("handles a doctor with no sessions", async () => {
    render(<BookingFlow doctor={doctor({ schedules: [] })} />);
    expect(await screen.findByText(/no upcoming sessions/i)).toBeInTheDocument();
    expect(api.getSlots).not.toHaveBeenCalled();
  });
});

describe("DoctorBrowser", () => {
  const docs = [
    doctor(),
    doctor({ id: "d2", full_name: "Dr. Priya Sharma", specialization: spec2 }),
  ];

  it("filters by specialty and search text", async () => {
    expect(filterDoctors(docs, "s2", "")).toHaveLength(1);
    expect(filterDoctors(docs, null, "rahul")).toHaveLength(1);
    expect(filterDoctors(docs, "s1", "priya")).toHaveLength(0);

    const user = userEvent.setup();
    render(<DoctorBrowser doctors={docs} specializations={[spec, spec2]} />);
    expect(screen.getByText("2 doctors found")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Pediatrician" }));
    expect(screen.getByText("1 doctor found")).toBeInTheDocument();
    expect(screen.getByText("Dr. Priya Sharma")).toBeInTheDocument();
    await user.type(screen.getByLabelText(/search doctors/i), "zzz");
    expect(screen.getByText(/No doctors match/)).toBeInTheDocument();
  });
});
