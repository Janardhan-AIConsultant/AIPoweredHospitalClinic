import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PatientPortal } from "@/components/patient-portal";
import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({
  requestOtp: vi.fn(),
  verifyOtp: vi.fn(),
  getMyAppointments: vi.fn(),
  cancelMyAppointment: vi.fn(),
  rescheduleMyAppointment: vi.fn(),
  getSlots: vi.fn(),
}));

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), ...api }));

const appt = (over = {}) => ({
  appointment_reference: "ABCDE23456",
  doctor_id: "doc-1",
  doctor_name: "Dr. Anil Kumar",
  specialization: "General Physician",
  appointment_date: "2099-01-05",
  start_time: "10:00:00",
  end_time: "10:30:00",
  consultation_fee: "500",
  status: "CONFIRMED",
  patient_name: "Asha Rao",
  reason_for_visit: null,
  ...over,
});

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockReset());
  api.requestOtp.mockResolvedValue({ message: "ok" });
  api.verifyOtp.mockResolvedValue({ access_token: "tok", expires_in: 900 });
});

async function signIn(items = [appt()]) {
  api.getMyAppointments.mockResolvedValue(items);
  const user = userEvent.setup();
  render(<PatientPortal />);
  await user.type(screen.getByLabelText("Mobile number"), "9876543210");
  await user.click(screen.getByRole("button", { name: "Send code" }));
  await user.type(await screen.findByLabelText("Verification code"), "123456");
  await user.click(screen.getByRole("button", { name: "Verify" }));
  await screen.findByRole("list");
  return user;
}

describe("PatientPortal", () => {
  it("validates the phone number before asking for a code", async () => {
    const user = userEvent.setup();
    render(<PatientPortal />);
    await user.type(screen.getByLabelText("Mobile number"), "123");
    await user.click(screen.getByRole("button", { name: "Send code" }));
    expect(await screen.findByText(/10-digit mobile number/)).toBeInTheDocument();
    expect(api.requestOtp).not.toHaveBeenCalled();
  });

  it("requests a code, verifies it and lists appointments", async () => {
    await signIn();
    expect(api.requestOtp).toHaveBeenCalledWith("9876543210");
    expect(api.verifyOtp).toHaveBeenCalledWith("9876543210", "123456");
    expect(api.getMyAppointments).toHaveBeenCalledWith("tok");
    expect(screen.getByText(/ABCDE23456/)).toBeInTheDocument();
  });

  it("only accepts a 6-digit code and shows a wrong-code error", async () => {
    api.verifyOtp.mockRejectedValue(new ApiError("Invalid or expired code.", 401, "unauthenticated"));
    const user = userEvent.setup();
    render(<PatientPortal />);
    await user.type(screen.getByLabelText("Mobile number"), "9876543210");
    await user.click(screen.getByRole("button", { name: "Send code" }));
    const code = await screen.findByLabelText("Verification code");
    await user.type(code, "12ab");
    expect(code).toHaveValue("12");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText("Enter the 6-digit code.")).toBeInTheDocument();
    await user.type(code, "3456");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText("Invalid or expired code.")).toBeInTheDocument();
  });

  it("explains rate limiting", async () => {
    api.requestOtp.mockRejectedValue(new ApiError("Too many", 429, "rate_limited"));
    const user = userEvent.setup();
    render(<PatientPortal />);
    await user.type(screen.getByLabelText("Mobile number"), "9876543210");
    await user.click(screen.getByRole("button", { name: "Send code" }));
    expect(await screen.findByText(/Too many attempts/)).toBeInTheDocument();
  });

  it("cancels an appointment after confirmation and refreshes the list", async () => {
    api.cancelMyAppointment.mockResolvedValue(appt({ status: "CANCELLED" }));
    const user = await signIn();
    api.getMyAppointments.mockResolvedValue([appt({ status: "CANCELLED" })]);
    await user.click(screen.getByRole("button", { name: "Cancel appointment" }));
    expect(api.cancelMyAppointment).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Yes, cancel it" }));
    expect(await screen.findByText(/was cancelled/)).toBeInTheDocument();
    expect(api.cancelMyAppointment).toHaveBeenCalledWith("tok", "ABCDE23456");
    await waitFor(() => expect(screen.queryByRole("button", { name: "Cancel appointment" })).not.toBeInTheDocument());
  });

  it("can back out of a cancellation", async () => {
    const user = await signIn();
    await user.click(screen.getByRole("button", { name: "Cancel appointment" }));
    await user.click(screen.getByRole("button", { name: "Keep it" }));
    expect(api.cancelMyAppointment).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Cancel appointment" })).toBeInTheDocument();
  });

  it("reschedules to a chosen slot", async () => {
    api.getSlots.mockResolvedValue({
      doctor_id: "doc-1",
      date: "2099-01-06",
      slots: [
        { start_time: "09:00:00", end_time: "09:30:00" },
        { start_time: "11:00:00", end_time: "11:30:00" },
      ],
    });
    api.rescheduleMyAppointment.mockResolvedValue(
      appt({ appointment_reference: "NEWREF2345", appointment_date: "2099-01-06", start_time: "11:00:00" }),
    );
    const user = await signIn();
    await user.click(screen.getByRole("button", { name: "Reschedule" }));
    fireEvent.change(screen.getByLabelText("New date"), { target: { value: "2099-01-06" } });
    const group = await screen.findByRole("group", { name: "Available times" });
    await user.click(within(group).getByRole("button", { name: "11:00 AM" }));
    expect(api.rescheduleMyAppointment).toHaveBeenCalledWith("tok", "ABCDE23456", "2099-01-06", "11:00");
    expect(await screen.findByText(/New reference NEWREF2345/)).toBeInTheDocument();
  });

  it("shows when the chosen slot was just taken and reloads the times", async () => {
    api.getSlots.mockResolvedValue({
      doctor_id: "doc-1",
      date: "2099-01-06",
      slots: [{ start_time: "11:00:00", end_time: "11:30:00" }],
    });
    api.rescheduleMyAppointment.mockRejectedValue(new ApiError("taken", 409, "slot_unavailable"));
    const user = await signIn();
    await user.click(screen.getByRole("button", { name: "Reschedule" }));
    fireEvent.change(screen.getByLabelText("New date"), { target: { value: "2099-01-06" } });
    await user.click(await screen.findByRole("button", { name: "11:00 AM" }));
    expect(await screen.findByText(/just taken/)).toBeInTheDocument();
    await waitFor(() => expect(api.getSlots).toHaveBeenCalledTimes(2));
  });

  it("offers no actions for past or cancelled appointments", async () => {
    await signIn([appt({ status: "CANCELLED" }), appt({ appointment_reference: "OLDOLD2345", appointment_date: "2001-01-01" })]);
    expect(screen.queryByRole("button", { name: "Reschedule" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel appointment" })).not.toBeInTheDocument();
  });

  it("handles an empty list", async () => {
    await signIn([]);
    expect(screen.getByText(/No recent or upcoming appointments/)).toBeInTheDocument();
  });
});
