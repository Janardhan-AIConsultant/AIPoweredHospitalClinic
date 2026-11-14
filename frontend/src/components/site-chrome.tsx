import Link from "next/link";

export const CLINIC_NAME = "Bindu AI Clinic";

export function SiteHeader() {
  return (
    <header className="border-b border-border bg-surface/80 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
        <Link href="/" className="text-lg font-bold text-primary">
          {CLINIC_NAME}
        </Link>
        <nav aria-label="Main" className="flex items-center gap-5 text-sm">
          <Link href="/doctors" className="font-medium hover:text-primary">
            Find a doctor
          </Link>
          <Link href="/my-appointments" className="font-medium hover:text-primary">
            My appointments
          </Link>
        </nav>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="mt-16 border-t border-border">
      <div className="mx-auto max-w-5xl space-y-2 px-4 py-6 text-xs text-muted">
        <p>
          <strong>Medical emergency?</strong> Call <strong>112</strong> or go to
          the nearest emergency department. Online booking is not for
          emergencies.
        </p>
        <p>
          This website helps you book appointments. It does not provide medical
          advice, diagnosis or treatment.
        </p>
        <p>
          © {CLINIC_NAME} ·{" "}
          <Link href="/privacy" className="underline">
            Privacy
          </Link>{" "}
          ·{" "}
          <Link href="/staff" className="underline">
            Staff sign in
          </Link>
        </p>
      </div>
    </footer>
  );
}
