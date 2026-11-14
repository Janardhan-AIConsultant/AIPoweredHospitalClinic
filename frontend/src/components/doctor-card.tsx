import Link from "next/link";
import { formatFee, workingDays } from "@/lib/format";
import type { Doctor } from "@/lib/types";
import { Card } from "./ui";

export function DoctorCard({ doctor }: { doctor: Doctor }) {
  const days = workingDays(doctor.schedules.map((s) => s.weekday));
  return (
    <Card className="flex h-full flex-col gap-3">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-primary">
          {doctor.specialization.name}
        </p>
        <h3 className="mt-1 text-lg font-semibold">{doctor.full_name}</h3>
        {doctor.qualifications && (
          <p className="text-sm text-muted">{doctor.qualifications}</p>
        )}
      </div>
      <dl className="grid grid-cols-2 gap-2 text-sm">
        <div>
          <dt className="text-xs text-muted">Experience</dt>
          <dd>{doctor.experience_years} years</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Consultation</dt>
          <dd>{formatFee(doctor.consultation_fee)}</dd>
        </div>
        <div className="col-span-2">
          <dt className="text-xs text-muted">Available</dt>
          <dd>{days || "Currently no sessions"}</dd>
        </div>
      </dl>
      <Link
        href={`/doctors/${doctor.id}`}
        className="mt-auto inline-flex justify-center rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-white hover:bg-primary-hover dark:text-[#06201d]"
        aria-label={`Book an appointment with ${doctor.full_name}`}
      >
        Book appointment
      </Link>
    </Card>
  );
}
