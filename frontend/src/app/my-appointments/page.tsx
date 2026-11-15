import type { Metadata } from "next";
import { PatientPortal } from "@/components/patient-portal";

export const metadata: Metadata = { title: "My appointments" };

export default function MyAppointmentsPage() {
  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div>
        <h1 className="text-3xl font-bold">My appointments</h1>
        <p className="mt-1 text-muted">
          Verify your mobile number to view, reschedule or cancel your bookings.
        </p>
      </div>
      <PatientPortal />
    </div>
  );
}
