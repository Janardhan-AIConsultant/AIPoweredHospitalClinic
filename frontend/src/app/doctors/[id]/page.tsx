import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { BookingFlow } from "@/components/booking-flow";
import { Alert } from "@/components/ui";
import { ApiError, getDoctor } from "@/lib/api";
import { formatFee, workingDays } from "@/lib/format";

export const metadata: Metadata = { title: "Book an appointment" };

async function DoctorBooking({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const result = await getDoctor(id).then(
    (doctor) => ({ doctor }),
    (error: unknown) => ({ error }),
  );
  if ("error" in result) {
    const e = result.error;
    if (e instanceof ApiError && (e.status === 404 || e.status === 422)) {
      notFound();
    }
    return (
      <Alert>
        We could not load this doctor right now. Please try again shortly.
      </Alert>
    );
  }
  const { doctor } = result;

  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_2fr]">
      <aside className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-primary">
          {doctor.specialization.name}
        </p>
        <h1 className="text-3xl font-bold">{doctor.full_name}</h1>
        {doctor.qualifications && (
          <p className="text-muted">{doctor.qualifications}</p>
        )}
        <dl className="space-y-2 text-sm">
          <div>
            <dt className="text-xs text-muted">Experience</dt>
            <dd>{doctor.experience_years} years</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Consultation fee</dt>
            <dd>{formatFee(doctor.consultation_fee)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Working days</dt>
            <dd>
              {workingDays(doctor.schedules.map((s) => s.weekday)) || "—"}
            </dd>
          </div>
        </dl>
        {doctor.bio && <p className="text-sm">{doctor.bio}</p>}
      </aside>
      <BookingFlow doctor={doctor} />
    </div>
  );
}

export default function DoctorPage(props: PageProps<"/doctors/[id]">) {
  return (
    <div className="space-y-6">
      <Link href="/doctors" className="text-sm text-primary hover:underline">
        ← All doctors
      </Link>
      <Suspense
        fallback={<p className="text-muted" role="status">Loading…</p>}
      >
        <DoctorBooking params={props.params} />
      </Suspense>
    </div>
  );
}
