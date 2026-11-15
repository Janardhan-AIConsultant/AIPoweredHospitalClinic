"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useStaffSession } from "@/lib/staff-session";
import type { StaffRole } from "@/lib/types";
import { Button, cx } from "../ui";
import {
  AppointmentsPanel,
  AuditPanel,
  DoctorsPanel,
  LeavePanel,
  OverviewPanel,
} from "./panels";

const TABS: Record<StaffRole, { id: string; label: string }[]> = {
  ADMIN: [
    { id: "overview", label: "Overview" },
    { id: "appointments", label: "Appointments" },
    { id: "doctors", label: "Doctors & leave" },
    { id: "audit", label: "Audit log" },
  ],
  DOCTOR: [
    { id: "appointments", label: "My appointments" },
    { id: "leave", label: "My leave" },
  ],
};

export function StaffDashboard() {
  const router = useRouter();
  const { status, user, logout } = useStaffSession();
  const [tab, setTab] = useState<string | null>(null);

  useEffect(() => {
    if (status === "anon") router.replace("/staff/login");
  }, [status, router]);

  if (status !== "authed" || !user) {
    return (
      <p className="text-muted" role="status">
        {status === "loading" ? "Checking your session…" : "Redirecting to sign in…"}
      </p>
    );
  }

  const tabs = TABS[user.role];
  const active = tab ?? tabs[0].id;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold">{user.role === "ADMIN" ? "Admin dashboard" : "Doctor dashboard"}</h1>
          <p className="text-sm text-muted">Signed in as {user.email}</p>
        </div>
        <Button variant="secondary" onClick={() => void logout()}>
          Sign out
        </Button>
      </div>

      <div role="tablist" aria-label="Dashboard sections" className="flex flex-wrap gap-2 border-b border-border pb-2">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            type="button"
            aria-selected={active === t.id}
            onClick={() => setTab(t.id)}
            className={cx(
              "rounded-lg px-3 py-1.5 text-sm font-medium",
              active === t.id ? "bg-primary text-white dark:text-[#06201d]" : "hover:bg-primary-soft",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div role="tabpanel">
        {active === "overview" && <OverviewPanel />}
        {active === "appointments" && <AppointmentsPanel role={user.role} />}
        {active === "doctors" && <DoctorsPanel />}
        {active === "leave" && <LeavePanel role="DOCTOR" doctors={[]} />}
        {active === "audit" && <AuditPanel />}
      </div>
    </div>
  );
}
