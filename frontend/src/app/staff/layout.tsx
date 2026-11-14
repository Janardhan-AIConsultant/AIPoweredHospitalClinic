import type { Metadata } from "next";
import type { ReactNode } from "react";
import { StaffSessionProvider } from "@/lib/staff-session";

export const metadata: Metadata = {
  title: "Staff",
  robots: { index: false, follow: false },
};

export default function StaffLayout({ children }: { children: ReactNode }) {
  return <StaffSessionProvider>{children}</StaffSessionProvider>;
}
