"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, confirmChatBooking, sendChat } from "@/lib/api";
import { formatDate, formatFee, formatTime, isValidIndianMobile } from "@/lib/format";
import type { ChatMessage, Proposal } from "@/lib/types";
import { Alert, Button, Field, TextInput, cx } from "./ui";

export const MAX_CHARS = 500;
const MAX_SENT = 12;

const SUGGESTIONS = [
  "Which specialties do you have?",
  "I need a pediatrician",
  "Show slots for Dr. Anil tomorrow",
];

interface Entry extends ChatMessage {
  id: number;
  emergency?: boolean;
}

export function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const nextId = useRef(1);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [entries, proposal, busy, open]);

  const add = (m: ChatMessage, extra: Partial<Entry> = {}) =>
    setEntries((prev) => [...prev, { ...m, id: nextId.current++, ...extra }]);

  async function send(text: string) {
    const content = text.trim();
    if (!content || busy) return;
    const history: ChatMessage[] = [
      ...entries.map(({ role, content: c }) => ({ role, content: c })),
      { role: "user" as const, content },
    ].slice(-MAX_SENT);
    add({ role: "user", content });
    setInput("");
    setError(null);
    setProposal(null);
    setBusy(true);
    try {
      const res = await sendChat(history);
      add(
        { role: "assistant", content: res.reply },
        { emergency: res.guard === "emergency" },
      );
      setProposal(res.proposal);
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 429
          ? "You're sending messages too quickly. Please wait a moment."
          : e instanceof ApiError
            ? e.message
            : "Something went wrong. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-4 right-4 z-40 rounded-full bg-primary px-5 py-3 text-sm font-semibold text-white shadow-lg hover:bg-primary-hover dark:text-[#06201d]"
      >
        Chat with us
      </button>
    );
  }

  return (
    <section
      role="dialog"
      aria-label="Appointment assistant"
      className="fixed inset-x-2 bottom-2 z-40 flex max-h-[80vh] flex-col rounded-2xl border border-border bg-surface shadow-2xl sm:inset-x-auto sm:right-4 sm:bottom-4 sm:w-96"
    >
      <header className="flex items-center justify-between border-b border-border px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold">Appointment assistant</h2>
          <p className="text-xs text-muted">
            Automated. No medical advice. Emergency? Call 112.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label="Close chat"
          className="rounded p-1 text-lg leading-none hover:bg-primary-soft"
        >
          ×
        </button>
      </header>

      <div
        ref={logRef}
        role="log"
        aria-live="polite"
        className="flex-1 space-y-3 overflow-y-auto px-4 py-3 text-sm"
      >
        {entries.length === 0 && (
          <div className="space-y-2">
            <p className="text-muted">
              Hi! I can help you find a doctor, check times and prepare a
              booking. Please don&apos;t share personal details here.
            </p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => void send(s)}
                  className="rounded-full border border-border px-3 py-1.5 text-xs hover:bg-primary-soft"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {entries.map((m) => (
          <div
            key={m.id}
            className={cx("flex", m.role === "user" ? "justify-end" : "justify-start")}
          >
            <p
              className={cx(
                "max-w-[85%] whitespace-pre-line rounded-2xl px-3 py-2",
                m.role === "user"
                  ? "bg-primary text-white dark:text-[#06201d]"
                  : m.emergency
                    ? "border border-danger bg-danger-soft text-danger"
                    : "bg-primary-soft",
              )}
            >
              {m.content}
            </p>
          </div>
        ))}
        {busy && <p className="text-xs text-muted">Assistant is typing…</p>}
        {proposal && (
          <ProposalCard
            key={proposal.token}
            proposal={proposal}
            onDone={(message) => {
              setProposal(null);
              add({ role: "assistant", content: message });
            }}
          />
        )}
        {error && <Alert>{error}</Alert>}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
        className="flex gap-2 border-t border-border p-3"
      >
        <label htmlFor="chat-input" className="sr-only">
          Your message
        </label>
        <input
          id="chat-input"
          value={input}
          maxLength={MAX_CHARS}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type your message"
          autoComplete="off"
          className="min-w-0 flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm"
        />
        <Button type="submit" disabled={busy || !input.trim()}>
          Send
        </Button>
      </form>
    </section>
  );
}

function ProposalCard({
  proposal,
  onDone,
}: {
  proposal: Proposal;
  onDone: (message: string) => void;
}) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [consent, setConsent] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const s = proposal.summary;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    const found: Record<string, string> = {};
    if (name.trim().length < 2) found.name = "Enter your full name.";
    if (!isValidIndianMobile(phone)) found.phone = "Enter a valid 10-digit mobile number.";
    setErrors(found);
    setFormError(null);
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      const appt = await confirmChatBooking({
        proposal_token: proposal.token,
        patient_name: name.trim(),
        phone: phone.trim(),
        notification_consent: consent,
      });
      onDone(
        `Your appointment is confirmed! Reference: ${appt.appointment_reference}. ` +
          `${appt.doctor_name}, ${formatDate(appt.appointment_date)} at ${formatTime(appt.start_time)}.`,
      );
    } catch (err) {
      setFormError(
        err instanceof ApiError && err.code === "slot_unavailable"
          ? "Sorry, that time was just taken. Ask me for other times."
          : err instanceof ApiError
            ? err.message
            : "Something went wrong. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      noValidate
      aria-label="Confirm booking"
      className="space-y-3 rounded-xl border border-primary bg-surface p-3"
    >
      <div>
        <p className="font-semibold">{s.doctor_name}</p>
        <p className="text-xs text-muted">
          {s.specialization} · {formatDate(s.date)} at {formatTime(s.start_time)}{" "}
          · {formatFee(s.fee)}
        </p>
      </div>
      {formError && <Alert>{formError}</Alert>}
      <Field id="chat-name" label="Your name" error={errors.name}>
        <TextInput
          id="chat-name"
          value={name}
          error={errors.name}
          autoComplete="name"
          onChange={(e) => setName(e.target.value)}
        />
      </Field>
      <Field id="chat-phone" label="Mobile number" error={errors.phone}>
        <TextInput
          id="chat-phone"
          type="tel"
          value={phone}
          error={errors.phone}
          autoComplete="tel"
          onChange={(e) => setPhone(e.target.value)}
        />
      </Field>
      <label className="flex items-start gap-2 text-xs">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={consent}
          onChange={(e) => setConsent(e.target.checked)}
        />
        <span>Send confirmation and reminders on WhatsApp.</span>
      </label>
      <Button type="submit" disabled={busy} className="w-full">
        {busy ? "Booking…" : "Confirm booking"}
      </Button>
      <p className="text-[11px] text-muted">
        Your details go straight to the clinic, not to the chat assistant.
      </p>
    </form>
  );
}
