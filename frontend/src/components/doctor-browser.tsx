"use client";

import { useMemo, useState } from "react";
import type { Doctor, Specialization } from "@/lib/types";
import { DoctorCard } from "./doctor-card";
import { TextInput, cx } from "./ui";

export function filterDoctors(
  doctors: Doctor[],
  specializationId: string | null,
  query: string,
): Doctor[] {
  const q = query.trim().toLowerCase();
  return doctors.filter(
    (d) =>
      (!specializationId || d.specialization.id === specializationId) &&
      (!q ||
        d.full_name.toLowerCase().includes(q) ||
        d.specialization.name.toLowerCase().includes(q)),
  );
}

export function DoctorBrowser({
  doctors,
  specializations,
}: {
  doctors: Doctor[];
  specializations: Specialization[];
}) {
  const [spec, setSpec] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const visible = useMemo(
    () => filterDoctors(doctors, spec, query),
    [doctors, spec, query],
  );

  return (
    <div className="space-y-5">
      <div className="space-y-3">
        <label htmlFor="doctor-search" className="sr-only">
          Search doctors or specialties
        </label>
        <TextInput
          id="doctor-search"
          type="search"
          placeholder="Search by doctor or specialty"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div
          role="group"
          aria-label="Filter by specialty"
          className="flex flex-wrap gap-2"
        >
          {[{ id: null, name: "All" }, ...specializations].map((s) => (
            <button
              key={s.id ?? "all"}
              type="button"
              aria-pressed={spec === s.id}
              onClick={() => setSpec(s.id)}
              className={cx(
                "rounded-full border px-3 py-1.5 text-sm",
                spec === s.id
                  ? "border-primary bg-primary-soft font-semibold text-primary"
                  : "border-border bg-surface hover:bg-primary-soft",
              )}
            >
              {s.name}
            </button>
          ))}
        </div>
      </div>
      <p className="text-sm text-muted" aria-live="polite">
        {visible.length} {visible.length === 1 ? "doctor" : "doctors"} found
      </p>
      {visible.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border p-8 text-center text-muted">
          No doctors match your search. Try another specialty.
        </p>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {visible.map((d) => (
            <li key={d.id}>
              <DoctorCard doctor={d} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
