import type { Metadata } from "next";
import { Suspense } from "react";
import { DoctorBrowser } from "@/components/doctor-browser";
import { Alert } from "@/components/ui";
import { getDoctors, getSpecializations } from "@/lib/api";

export const metadata: Metadata = { title: "Find a doctor" };

async function DoctorList() {
  const data = await Promise.all([getDoctors(), getSpecializations()]).catch(
    () => null,
  );
  if (!data) {
    return (
      <Alert>
        We could not load our doctors right now. Please refresh in a moment.
      </Alert>
    );
  }
  return <DoctorBrowser doctors={data[0]} specializations={data[1]} />;
}

export default function DoctorsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Find a doctor</h1>
        <p className="mt-1 text-muted">
          Choose a doctor to see available appointment times.
        </p>
      </div>
      <Suspense
        fallback={<p className="text-muted" role="status">Loading doctors…</p>}
      >
        <DoctorList />
      </Suspense>
    </div>
  );
}
