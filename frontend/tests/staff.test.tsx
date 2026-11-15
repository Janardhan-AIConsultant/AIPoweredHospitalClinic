import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StaffDashboard } from "@/components/staff/dashboard";
import { StaffLogin } from "@/components/staff/login-form";
import { ApiError } from "@/lib/api";
import type { StaffUser } from "@/lib/types";
import { StaffSessionProvider, useStaffSession } from "@/lib/staff-session";

const api = vi.hoisted(() => ({
  staffLogin: vi.fn(),
  staffRefresh: vi.fn(),
  staffLogout: vi.fn(),
  getStats: vi.fn(),
  getStaffAppointments: vi.fn(),
  cancelStaffAppointment: vi.fn(),
  setAppointmentStatus: vi.fn(),
  getAdminDoctors: vi.fn(),
  patchDoctor: vi.fn(),
  getLeave: vi.fn(),
  addLeave: vi.fn(),
  deleteLeave: vi.fn(),
  getAuditLogs: vi.fn(),
}));
const nav = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), ...api }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: nav.replace }) }));

const ADMIN: StaffUser = { id: "u1", email: "admin@clinic.test", role: "ADMIN", doctor_id: null, is_active: true };
const DOCTOR: StaffUser = { id: "u2", email: "anil@clinic.test", role: "DOCTOR", doctor_id: "doc-1", is_active: true };
const session = (user = ADMIN, token = "tok1") => ({ access_token: token, token_type: "bearer", expires_in: 900, user });

const APPT = {
  appointment_reference: "ABCDE23456",
  patient_name: "Asha Rao",
  patient_phone_masked: "+91*****3210",
  doctor_id: "doc-1",
  doctor_name: "Dr. Anil Kumar",
  appointment_date: "2099-01-05",
  start_time: "10:00:00",
  end_time: "10:30:00",
  status: "CONFIRMED",
  reason_for_visit: "Checkup",
  consultation_fee: "500",
  notification_consent: true,
};
const page = (items = [APPT]) => ({ items, total: items.length, limit: 100, offset: 0 });

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockReset());
  nav.replace.mockReset();
  api.staffLogout.mockResolvedValue(undefined);
  api.getLeave.mockResolvedValue([]);
});

function dashboard(user = ADMIN) {
  api.staffRefresh.mockResolvedValue(session(user));
  return render(
    <StaffSessionProvider>
      <StaffDashboard />
    </StaffSessionProvider>,
  );
}

describe("StaffLogin", () => {
  it("validates, signs in and redirects", async () => {
    api.staffRefresh.mockRejectedValue(new ApiError("no", 401, "unauthenticated"));
    api.staffLogin.mockResolvedValue(session());
    const user = userEvent.setup();
    render(
      <StaffSessionProvider>
        <StaffLogin />
      </StaffSessionProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter your email and password.")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Email"), "admin@clinic.test");
    await user.type(screen.getByLabelText("Password"), "Str0ng-Passw0rd!");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/staff"));
    expect(api.staffLogin).toHaveBeenCalledWith("admin@clinic.test", "Str0ng-Passw0rd!");
  });

  it("shows the server's generic error and rate limiting", async () => {
    api.staffRefresh.mockRejectedValue(new ApiError("no", 401, "unauthenticated"));
    api.staffLogin.mockRejectedValueOnce(new ApiError("Invalid email or password.", 401, "unauthenticated"));
    api.staffLogin.mockRejectedValueOnce(new ApiError("slow", 429, "rate_limited"));
    const user = userEvent.setup();
    render(
      <StaffSessionProvider>
        <StaffLogin />
      </StaffSessionProvider>,
    );
    await user.type(screen.getByLabelText("Email"), "a@b.co");
    await user.type(screen.getByLabelText("Password"), "x");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Invalid email or password.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText(/Too many attempts/)).toBeInTheDocument();
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("skips the form when a session already exists", async () => {
    api.staffRefresh.mockResolvedValue(session());
    render(
      <StaffSessionProvider>
        <StaffLogin />
      </StaffSessionProvider>,
    );
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/staff"));
  });
});

describe("session", () => {
  it("redirects anonymous visitors to the login page", async () => {
    api.staffRefresh.mockRejectedValue(new ApiError("no", 401, "unauthenticated"));
    render(
      <StaffSessionProvider>
        <StaffDashboard />
      </StaffSessionProvider>,
    );
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/staff/login"));
  });

  it("shares one refresh request under StrictMode (rotating tokens are single use)", async () => {
    api.staffRefresh.mockResolvedValue(session());
    api.getStats.mockResolvedValue({
      today: "2099-01-05", today_total: 0, today_by_status: {}, upcoming_active: 0, active_doctors: 0, notifications: {},
    });
    render(
      <StrictMode>
        <StaffSessionProvider>
          <StaffDashboard />
        </StaffSessionProvider>
      </StrictMode>,
    );
    await screen.findByText("Admin dashboard");
    expect(api.staffRefresh).toHaveBeenCalledTimes(1);
  });

  it("refreshes once and retries when the access token has expired", async () => {
    api.staffRefresh.mockResolvedValueOnce(session(ADMIN, "old")).mockResolvedValueOnce(session(ADMIN, "new"));
    const seen: string[] = [];
    function Probe() {
      const { status, call } = useStaffSession();
      return (
        <button
          disabled={status !== "authed"}
          onClick={() =>
            void call(async (t) => {
              seen.push(t);
              if (t === "old") throw new ApiError("expired", 401, "unauthenticated");
              return "ok";
            })
          }
        >
          go
        </button>
      );
    }
    const user = userEvent.setup();
    render(
      <StaffSessionProvider>
        <Probe />
      </StaffSessionProvider>,
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "go" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "go" }));
    await waitFor(() => expect(seen).toEqual(["old", "new"]));
  });

  it("ends the session when the refresh also fails", async () => {
    api.staffRefresh
      .mockResolvedValueOnce(session())
      .mockRejectedValueOnce(new ApiError("revoked", 401, "unauthenticated"));
    api.getStats.mockRejectedValue(new ApiError("expired", 401, "unauthenticated"));
    render(
      <StaffSessionProvider>
        <StaffDashboard />
      </StaffSessionProvider>,
    );
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/staff/login"));
  });

  it("signs out", async () => {
    api.getStats.mockResolvedValue({
      today: "2099-01-05", today_total: 0, today_by_status: {}, upcoming_active: 0, active_doctors: 0, notifications: {},
    });
    const user = userEvent.setup();
    dashboard();
    await user.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(api.staffLogout).toHaveBeenCalled();
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/staff/login"));
  });
});

describe("admin dashboard", () => {
  it("shows the overview with stats and message queue health", async () => {
    api.getStats.mockResolvedValue({
      today: "2099-01-05",
      today_total: 3,
      today_by_status: { CONFIRMED: 2, CANCELLED: 1 },
      upcoming_active: 7,
      active_doctors: 5,
      notifications: { PENDING: 4, FAILED: 1, DEAD: 2 },
    });
    dashboard();
    expect(await screen.findByText("Upcoming appointments")).toBeInTheDocument();
    expect(screen.getByText("Messages failed for good").nextSibling).toHaveTextContent("2");
    expect(screen.getByText(/2 confirmed, 1 cancelled/)).toBeInTheDocument();
  });

  it("lists appointments with masked phones and applies actions", async () => {
    api.getStats.mockResolvedValue({
      today: "2099-01-05", today_total: 0, today_by_status: {}, upcoming_active: 0, active_doctors: 0, notifications: {},
    });
    api.getStaffAppointments.mockResolvedValue(page());
    api.setAppointmentStatus.mockResolvedValue({ ...APPT, status: "COMPLETED" });
    api.cancelStaffAppointment.mockResolvedValue({});
    const user = userEvent.setup();
    dashboard();
    await user.click(await screen.findByRole("tab", { name: "Appointments" }));
    const table = await screen.findByRole("table", { name: "Appointments" });
    expect(within(table).getByText(/\+91\*{5}3210/)).toBeInTheDocument();
    expect(table).not.toHaveTextContent("9876543210");
    expect(api.getStaffAppointments.mock.calls[0].slice(1, 2)).toEqual(["ADMIN"]);

    await user.click(screen.getByRole("button", { name: "Mark ABCDE23456 completed" }));
    expect(api.setAppointmentStatus).toHaveBeenCalledWith("tok1", "ADMIN", "ABCDE23456", "COMPLETED");
    expect(await screen.findByText(/marked completed/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cancel ABCDE23456" }));
    expect(api.cancelStaffAppointment).not.toHaveBeenCalled(); // needs explicit confirmation
    await user.click(screen.getByRole("button", { name: "Confirm cancel ABCDE23456" }));
    await waitFor(() => expect(api.cancelStaffAppointment).toHaveBeenCalledWith("tok1", "ADMIN", "ABCDE23456"));
  });

  it("surfaces action errors without losing the list", async () => {
    api.getStats.mockResolvedValue({
      today: "2099-01-05", today_total: 0, today_by_status: {}, upcoming_active: 0, active_doctors: 0, notifications: {},
    });
    api.getStaffAppointments.mockResolvedValue(page());
    api.setAppointmentStatus.mockRejectedValue(new ApiError("This appointment has not started yet.", 422, "validation_error"));
    const user = userEvent.setup();
    dashboard();
    await user.click(await screen.findByRole("tab", { name: "Appointments" }));
    await user.click(await screen.findByRole("button", { name: "Mark ABCDE23456 no-show" }));
    expect(await screen.findByText("This appointment has not started yet.")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Appointments" })).toBeInTheDocument();
  });

  it("filters by status", async () => {
    api.getStats.mockResolvedValue({
      today: "2099-01-05", today_total: 0, today_by_status: {}, upcoming_active: 0, active_doctors: 0, notifications: {},
    });
    api.getStaffAppointments.mockResolvedValue(page([]));
    const user = userEvent.setup();
    dashboard();
    await user.click(await screen.findByRole("tab", { name: "Appointments" }));
    expect(await screen.findByText("No appointments match.")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Status"), "CANCELLED");
    await waitFor(() =>
      expect(api.getStaffAppointments).toHaveBeenLastCalledWith("tok1", "ADMIN", expect.objectContaining({ status: "CANCELLED" })),
    );
  });

  it("edits a doctor's fee and activation", async () => {
    api.getStats.mockResolvedValue({
      today: "2099-01-05", today_total: 0, today_by_status: {}, upcoming_active: 0, active_doctors: 0, notifications: {},
    });
    api.getAdminDoctors.mockResolvedValue([
      { id: "doc-1", full_name: "Dr. Anil Kumar", specialization: "General Physician", consultation_fee: "500.00", is_active: true, upcoming_appointments: 2 },
    ]);
    api.patchDoctor.mockResolvedValue({});
    const user = userEvent.setup();
    dashboard();
    await user.click(await screen.findByRole("tab", { name: "Doctors & leave" }));
    const save = await screen.findByRole("button", { name: "Save fee for Dr. Anil Kumar" });
    expect(save).toBeDisabled();
    const fee = screen.getByLabelText("Fee (₹)");
    await user.clear(fee);
    await user.type(fee, "650");
    await user.click(save);
    expect(api.patchDoctor).toHaveBeenCalledWith("tok1", "doc-1", { consultation_fee: "650" });
    await user.click(screen.getByRole("button", { name: "Deactivate Dr. Anil Kumar" }));
    expect(api.patchDoctor).toHaveBeenLastCalledWith("tok1", "doc-1", { is_active: false });
  });

  it("adds leave and warns about already-booked appointments", async () => {
    api.getStats.mockResolvedValue({
      today: "2099-01-05", today_total: 0, today_by_status: {}, upcoming_active: 0, active_doctors: 0, notifications: {},
    });
    api.getAdminDoctors.mockResolvedValue([
      { id: "doc-1", full_name: "Dr. Anil Kumar", specialization: "GP", consultation_fee: "500", is_active: true, upcoming_appointments: 1 },
    ]);
    api.addLeave.mockResolvedValue({ id: "l1", doctor_id: "doc-1", start_date: "2099-01-05", end_date: "2099-01-06", reason: null, affected_appointments: 2 });
    const user = userEvent.setup();
    dashboard();
    await user.click(await screen.findByRole("tab", { name: "Doctors & leave" }));
    await screen.findByLabelText("Doctor");
    await user.click(screen.getByRole("button", { name: "Add leave" }));
    expect(await screen.findByText(/Choose a doctor/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Doctor"), "doc-1");
    await user.type(screen.getByLabelText("From"), "2099-01-05");
    await user.type(screen.getByLabelText("To"), "2099-01-06");
    await user.click(screen.getByRole("button", { name: "Add leave" }));
    expect(await screen.findByText(/2 existing appointment\(s\)/)).toBeInTheDocument();
    expect(api.addLeave).toHaveBeenCalledWith("tok1", "ADMIN", "doc-1", {
      start_date: "2099-01-05", end_date: "2099-01-06", reason: null,
    });
  });

  it("shows the audit log", async () => {
    api.getStats.mockResolvedValue({
      today: "2099-01-05", today_total: 0, today_by_status: {}, upcoming_active: 0, active_doctors: 0, notifications: {},
    });
    api.getAuditLogs.mockResolvedValue([
      { id: "a1", created_at: "2030-01-01T00:00:00Z", actor_role: "ADMIN", action: "appointment.cancel", entity_type: "appointment", entity_id: "x" },
    ]);
    const user = userEvent.setup();
    dashboard();
    await user.click(await screen.findByRole("tab", { name: "Audit log" }));
    expect(await screen.findByText("appointment.cancel")).toBeInTheDocument();
  });
});

describe("doctor dashboard", () => {
  it("shows only the doctor's own tabs and calls the doctor endpoints", async () => {
    api.getStaffAppointments.mockResolvedValue(page());
    dashboard(DOCTOR);
    expect(await screen.findByText("Doctor dashboard")).toBeInTheDocument();
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["My appointments", "My leave"]);
    expect(screen.queryByRole("tab", { name: "Audit log" })).not.toBeInTheDocument();
    await screen.findByRole("table", { name: "Appointments" });
    expect(api.getStaffAppointments.mock.calls[0][1]).toBe("DOCTOR");
    expect(screen.queryByRole("columnheader", { name: "Doctor" })).not.toBeInTheDocument();
  });

  it("adds own leave without choosing a doctor", async () => {
    api.getStaffAppointments.mockResolvedValue(page([]));
    api.addLeave.mockResolvedValue({ id: "l1", doctor_id: "doc-1", start_date: "2099-02-01", end_date: "2099-02-01", reason: "x", affected_appointments: 0 });
    const user = userEvent.setup();
    dashboard(DOCTOR);
    await user.click(await screen.findByRole("tab", { name: "My leave" }));
    expect(screen.queryByLabelText("Doctor")).not.toBeInTheDocument();
    await user.type(await screen.findByLabelText("From"), "2099-02-01");
    await user.type(screen.getByLabelText("To"), "2099-02-01");
    await user.click(screen.getByRole("button", { name: "Add leave" }));
    expect(await screen.findByText("Leave added.")).toBeInTheDocument();
    expect(api.addLeave).toHaveBeenCalledWith("tok1", "DOCTOR", "doc-1", expect.objectContaining({ start_date: "2099-02-01" }));
  });
});
