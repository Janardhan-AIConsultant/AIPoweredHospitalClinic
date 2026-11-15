"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, confirmChatBooking, sendChat } from "@/lib/api";
import { formatDate, formatFee, formatTime, isValidIndianMobile } from "@/lib/format";
import type { Appointment, ChatMessage, Proposal, SlotsOffer } from "@/lib/types";
import { ConfirmationCard, timeRange } from "./appointment-summary";
import { ChatText } from "./chat-text";
import { Alert, Button, Field, TextInput, WhatsAppChoice, cx } from "./ui";

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
  confirmation?: Appointment; // rendered as a structured card; `content` is its plain-text summary
}

export function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [offer, setOffer] = useState<SlotsOffer | null>(null);
  const nextId = useRef(1);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [entries, proposal, busy, open]);

  // The assistant message that announced the booking card, so confirming can replace it
  // instead of leaving two messages ("prepared" and "confirmed") in the chat.
  const proposalEntry = useRef<number | null>(null);

  const add = (m: ChatMessage, extra: Partial<Entry> = {}): number => {
    const id = nextId.current++;
    setEntries((prev) => [...prev, { ...m, id, ...extra }]);
    return id;
  };

  function showConfirmation(appt: Appointment) {
    const target = proposalEntry.current;
    proposalEntry.current = null;
    setProposal(null);
    // Plain-text twin of the card: this is what later chat turns (and screen-reader history) see.
    const content =
      `Appointment confirmed. Reference ${appt.appointment_reference}: ${appt.doctor_name}, ` +
      `${formatDate(appt.appointment_date)}, ${timeRange(appt)}.`;
    setEntries((prev) =>
      target !== null && prev.some((e) => e.id === target)
        ? prev.map((e) => (e.id === target ? { ...e, content, confirmation: appt, emergency: false } : e))
        : [...prev, { role: "assistant", content, confirmation: appt, id: nextId.current++ }],
    );
  }

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
      const res = await sendChat(history, offer);
      const replyId = add(
        { role: "assistant", content: res.reply },
        { emergency: res.guard === "emergency" },
      );
      proposalEntry.current = res.proposal ? replyId : null;
      setProposal(res.proposal);
      // Keep what the patient was last shown so a bare "10:00 AM" still means that doctor and date.
      if (res.slots) setOffer(res.slots);
      else if (res.clear_slots || res.proposal) setOffer(null);
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
        className="fixed bottom-4 right-4 z-40 flex items-center gap-2 rounded-full bg-primary px-5 py-3 text-sm font-semibold text-white shadow-lg transition hover:bg-primary-hover dark:text-[#06201d]"
      >
        <span aria-hidden="true" className="text-base leading-none">
          💬
        </span>
        Chat with Mitra
      </button>
    );
  }

  return (
    <section
      role="dialog"
      aria-label="Mitra, appointment assistant"
      className="fixed inset-x-2 bottom-2 z-40 flex h-[min(36rem,85vh)] flex-col overflow-hidden rounded-2xl border border-border bg-surface shadow-2xl sm:inset-x-auto sm:right-4 sm:bottom-4 sm:w-[26rem]"
    >
      <header className="flex items-center gap-3 bg-primary px-4 py-3 text-white dark:text-[#06201d]">
        <span
          aria-hidden="true"
          className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/20 text-base font-bold"
        >
          M
          <span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-primary bg-green-400" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold leading-tight">Mitra</h2>
          <p className="truncate text-xs opacity-90">Bindu Clinic assistant · No medical advice</p>
        </div>
        {entries.length > 0 && (
          <button
            type="button"
            onClick={() => {
              setEntries([]);
              setProposal(null);
              proposalEntry.current = null;
              setOffer(null);
              setError(null);
            }}
            className="rounded px-2 py-1 text-xs font-medium opacity-90 hover:bg-white/15"
          >
            New chat
          </button>
        )}
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label="Close chat"
          className="rounded p-1 text-xl leading-none hover:bg-white/15"
        >
          ×
        </button>
      </header>

      <div
        ref={logRef}
        role="log"
        aria-live="polite"
        className="flex-1 space-y-3 overflow-y-auto bg-background px-3 py-4 text-sm"
      >
        {entries.length === 0 && (
          <div className="space-y-3">
            <Bubble role="assistant">
              <p>
                Hi! I&apos;m Mitra. I can help you find a doctor, check times and prepare a
                booking. Please don&apos;t share personal details here.
              </p>
            </Bubble>
            <div className="flex flex-wrap gap-2 pl-9">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => void send(s)}
                  className="rounded-full border border-primary/40 bg-surface px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary-soft"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {entries.map((m) => (
          <Bubble key={m.id} role={m.role} emergency={m.emergency}>
            {m.confirmation ? (
              <ConfirmationCard appt={m.confirmation} />
            ) : m.role === "assistant" ? (
              <ChatText text={m.content} />
            ) : (
              <p className="whitespace-pre-line break-words">{m.content}</p>
            )}
          </Bubble>
        ))}
        {busy && (
          <Bubble role="assistant">
            <span className="sr-only">Mitra is typing…</span>
            <span aria-hidden="true" className="flex items-center gap-1 py-1">
              {[0, 150, 300].map((d) => (
                <span
                  key={d}
                  style={{ animationDelay: `${d}ms` }}
                  className="h-2 w-2 rounded-full bg-muted motion-safe:animate-bounce"
                />
              ))}
            </span>
          </Bubble>
        )}
        {offer && !proposal && !busy && (
          <SlotPicker offer={offer} onPick={(label) => void send(`Book ${label}`)} />
        )}
        {proposal && (
          <ProposalCard
            key={proposal.token}
            proposal={proposal}
            onDone={showConfirmation}
          />
        )}
        {error && <Alert>{error}</Alert>}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
        className="flex items-center gap-2 border-t border-border bg-surface p-3"
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
          className="min-w-0 flex-1 rounded-full border border-border bg-background px-4 py-2 text-sm focus:border-primary focus:outline-none"
        />
        <Button type="submit" disabled={busy || !input.trim()} className="rounded-full px-4">
          Send
        </Button>
      </form>
      <p className="bg-surface px-3 pb-2 text-center text-[11px] text-muted">
        Automated assistant. In an emergency call 112.
      </p>
    </section>
  );
}

function SlotPicker({ offer, onPick }: { offer: SlotsOffer; onPick: (label: string) => void }) {
  return (
    <section
      aria-label={`Open times for ${offer.doctor_name} on ${offer.date_label}`}
      className="ml-9 space-y-2 rounded-xl border border-primary/40 bg-surface p-3"
    >
      <p className="text-xs">
        <span className="font-semibold">{offer.doctor_name}</span> · {offer.date_label}
      </p>
      <div className="flex flex-wrap gap-2">
        {offer.times.map((t) => (
          <button
            key={t.time}
            type="button"
            onClick={() => onPick(t.label)}
            className="rounded-full border border-primary px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary hover:text-white dark:hover:text-[#06201d]"
          >
            {t.label}
          </button>
        ))}
      </div>
      <p className="text-[11px] text-muted">Tap a time to book it.</p>
    </section>
  );
}

function Bubble({
  role,
  emergency,
  children,
}: {
  role: "user" | "assistant";
  emergency?: boolean;
  children: React.ReactNode;
}) {
  const mine = role === "user";
  return (
    <div className={cx("flex items-end gap-2", mine ? "justify-end" : "justify-start")}>
      {!mine && (
        <span
          aria-hidden="true"
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-bold text-white dark:text-[#06201d]"
        >
          M
        </span>
      )}
      <div
        className={cx(
          "max-w-[82%] rounded-2xl px-3.5 py-2.5 leading-relaxed shadow-sm",
          mine
            ? "rounded-br-md bg-primary text-white dark:text-[#06201d]"
            : emergency
              ? "rounded-bl-md border border-danger bg-danger-soft text-danger"
              : "rounded-bl-md border border-border bg-surface",
        )}
      >
        {children}
      </div>
    </div>
  );
}

function ProposalCard({
  proposal,
  onDone,
}: {
  proposal: Proposal;
  onDone: (appt: Appointment) => void;
}) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [consent, setConsent] = useState<boolean | null>(null);
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
    if (consent === null) found.consent = "Please choose Yes or No.";
    setErrors(found);
    setFormError(null);
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      const appt = await confirmChatBooking({
        proposal_token: proposal.token,
        patient_name: name.trim(),
        phone: phone.trim(),
        notification_consent: consent === true,
      });
      onDone(appt);
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
      <WhatsAppChoice
        name="chat-whatsapp-consent"
        compact
        value={consent}
        error={errors.consent}
        onChange={(next) => {
          setConsent(next);
          setErrors((prev) => ({ ...prev, consent: "" }));
        }}
      />
      <Button type="submit" disabled={busy} className="w-full">
        {busy ? "Booking…" : "Confirm booking"}
      </Button>
      <p className="text-[11px] text-muted">
        Your details go straight to the clinic, not to Mitra, the chat assistant.
      </p>
    </form>
  );
}
