import Link from "next/link";
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  TextareaHTMLAttributes,
} from "react";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

const buttonBase =
  "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50";
const buttonVariants = {
  primary: "bg-primary text-white hover:bg-primary-hover dark:text-[#06201d]",
  secondary: "border border-border bg-surface hover:bg-primary-soft",
};

export function Button({
  variant = "primary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof buttonVariants;
}) {
  return (
    <button
      className={cx(buttonBase, buttonVariants[variant], className)}
      {...props}
    />
  );
}

export function ButtonLink({
  href,
  variant = "primary",
  className,
  children,
}: {
  href: string;
  variant?: keyof typeof buttonVariants;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link
      href={href}
      className={cx(buttonBase, buttonVariants[variant], className)}
    >
      {children}
    </Link>
  );
}

export function Card({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cx(
        "rounded-2xl border border-border bg-surface p-5 shadow-sm",
        className,
      )}
    >
      {children}
    </div>
  );
}

const inputClass =
  "w-full rounded-lg border border-border bg-surface px-3 py-2.5 text-sm placeholder:text-muted aria-[invalid=true]:border-danger";

export function Field({
  label,
  error,
  hint,
  id,
  children,
}: {
  label: string;
  error?: string;
  hint?: string;
  id: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {hint && !error && <p className="text-xs text-muted">{hint}</p>}
      {error && (
        <p id={`${id}-error`} role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

/** Explicit yes/no question: WhatsApp messages are opt-in, so the patient must answer before booking. */
export function WhatsAppChoice({
  name,
  value,
  onChange,
  error,
  compact = false,
}: {
  name: string;
  value: boolean | null;
  onChange: (next: boolean) => void;
  error?: string;
  compact?: boolean;
}) {
  const option = (label: string, v: boolean) => (
    <label className="flex cursor-pointer items-center gap-2">
      <input
        type="radio"
        name={name}
        checked={value === v}
        onChange={() => onChange(v)}
        aria-describedby={error ? `${name}-error` : undefined}
      />
      <span>{label}</span>
    </label>
  );
  return (
    <fieldset className={cx("space-y-1.5", compact ? "text-xs" : "text-sm")}>
      <legend className="font-medium">
        Would you like your appointment details and reminders on WhatsApp?
      </legend>
      <div className="flex flex-wrap gap-x-6 gap-y-1">
        {option("Yes, message me", true)}
        {option("No, thanks", false)}
      </div>
      <p className="text-muted">WhatsApp is optional: choose No if you prefer. Your number is still used to find your booking.</p>
      {error && (
        <p id={`${name}-error`} role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
    </fieldset>
  );
}

export function TextInput({
  error,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { error?: string }) {
  return (
    <input
      className={inputClass}
      aria-invalid={error ? true : undefined}
      aria-describedby={error ? `${props.id}-error` : undefined}
      {...props}
    />
  );
}

export function TextArea({
  error,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { error?: string }) {
  return (
    <textarea
      className={inputClass}
      aria-invalid={error ? true : undefined}
      aria-describedby={error ? `${props.id}-error` : undefined}
      {...props}
    />
  );
}

export function Alert({
  tone = "danger",
  children,
}: {
  tone?: "danger" | "info";
  children: ReactNode;
}) {
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={cx(
        "rounded-lg border px-3 py-2.5 text-sm",
        tone === "danger"
          ? "border-danger/40 bg-danger-soft text-danger"
          : "border-border bg-primary-soft",
      )}
    >
      {children}
    </div>
  );
}
