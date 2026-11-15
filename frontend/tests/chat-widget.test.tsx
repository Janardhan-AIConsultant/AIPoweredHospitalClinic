import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChatWidget } from "@/components/chat-widget";
import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({ sendChat: vi.fn(), confirmChatBooking: vi.fn() }));

vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  sendChat: api.sendChat,
  confirmChatBooking: api.confirmChatBooking,
}));

const PROPOSAL = {
  token: "signed.proposal.token",
  summary: {
    doctor_name: "Dr. Anil Kumar",
    specialization: "General Physician",
    date: "2030-01-02",
    start_time: "10:00",
    fee: "500",
  },
};

const CONFIRMED = {
  appointment_reference: "20300102-0001",
  doctor_id: "11111111-1111-4111-8111-111111111111",
  doctor_name: "Dr. Anil Kumar",
  specialization: "General Physician",
  appointment_date: "2030-01-02",
  start_time: "10:00:00",
  end_time: "10:30:00",
  consultation_fee: "500.00",
  status: "CONFIRMED",
  patient_name: "Asha Rao",
  reason_for_visit: null,
  notification_consent: false,
};

beforeEach(() => {
  api.sendChat.mockReset();
  api.confirmChatBooking.mockReset();
});

async function openChat() {
  const user = userEvent.setup();
  render(<ChatWidget />);
  await user.click(screen.getByRole("button", { name: "Chat with Mitra" }));
  return user;
}

async function ask(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.type(screen.getByLabelText("Your message"), text);
  await user.click(screen.getByRole("button", { name: "Send" }));
}

describe("ChatWidget", () => {
  it("opens, shows the safety banner and closes", async () => {
    const user = await openChat();
    expect(screen.getByRole("dialog", { name: "Mitra, appointment assistant" })).toBeInTheDocument();
    expect(screen.getByText(/No medical advice/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close chat" }));
    expect(screen.getByRole("button", { name: "Chat with Mitra" })).toBeInTheDocument();
  });

  it("sends the conversation and renders the reply", async () => {
    api.sendChat.mockResolvedValue({ reply: "We have Cardiologist.", guard: "none", proposal: null });
    const user = await openChat();
    await ask(user, "which specialties");
    expect(await screen.findByText("We have Cardiologist.")).toBeInTheDocument();
    expect(api.sendChat).toHaveBeenCalledWith([{ role: "user", content: "which specialties" }], null);

    api.sendChat.mockResolvedValue({ reply: "Sure.", guard: "none", proposal: null });
    await ask(user, "thanks");
    await screen.findByText("Sure.");
    expect(api.sendChat.mock.calls[1][0]).toEqual([
      { role: "user", content: "which specialties" },
      { role: "assistant", content: "We have Cardiologist." },
      { role: "user", content: "thanks" },
    ]);
  });

  it("sends only the last 12 messages", async () => {
    api.sendChat.mockResolvedValue({ reply: "ok", guard: "none", proposal: null });
    const user = await openChat();
    for (let i = 0; i < 8; i++) {
      await ask(user, `m${i}`);
      await waitFor(() => expect(api.sendChat).toHaveBeenCalledTimes(i + 1));
      await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeDisabled());
    }
    const last = api.sendChat.mock.calls[7][0];
    expect(last.length).toBe(12);
    expect(last[last.length - 1]).toEqual({ role: "user", content: "m7" });
  });

  it("runs a suggestion chip", async () => {
    api.sendChat.mockResolvedValue({ reply: "ok", guard: "none", proposal: null });
    const user = await openChat();
    await user.click(screen.getByRole("button", { name: "I need a pediatrician" }));
    await waitFor(() => expect(api.sendChat).toHaveBeenCalled());
  });

  it("highlights emergency replies", async () => {
    api.sendChat.mockResolvedValue({ reply: "Please call 112 now.", guard: "emergency", proposal: null });
    const user = await openChat();
    await ask(user, "chest pain");
    const bubble = await screen.findByText("Please call 112 now.");
    expect(bubble.closest('[class*="rounded-2xl"]')?.className).toContain("text-danger");
  });

  it("shows friendly errors, including rate limiting", async () => {
    api.sendChat.mockRejectedValueOnce(new ApiError("Too many", 429, "rate_limited"));
    const user = await openChat();
    await ask(user, "hi");
    expect(await screen.findByText(/too quickly/i)).toBeInTheDocument();
    api.sendChat.mockRejectedValueOnce(new ApiError("The assistant is temporarily unavailable.", 503, "service_unavailable"));
    await ask(user, "hi again");
    expect(await screen.findByText(/temporarily unavailable/i)).toBeInTheDocument();
  });

  it("confirms a proposal with the patient's own details", async () => {
    api.sendChat.mockResolvedValue({ reply: "Prepared.", guard: "none", proposal: PROPOSAL });
    api.confirmChatBooking.mockResolvedValue(CONFIRMED);
    const user = await openChat();
    await ask(user, "book dr anil");
    const form = await screen.findByRole("form", { name: "Confirm booking" });
    expect(form).toHaveTextContent("Dr. Anil Kumar");

    await user.click(screen.getByRole("button", { name: "Confirm booking" }));
    expect(await screen.findByText("Enter your full name.")).toBeInTheDocument();
    expect(screen.getByText("Please choose Yes or No.")).toBeInTheDocument(); // WhatsApp question must be answered
    expect(api.confirmChatBooking).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText("Your name"), "Asha Rao");
    await user.type(screen.getByLabelText("Mobile number"), "9876543210");
    await user.click(screen.getByLabelText("No, thanks"));
    await user.click(screen.getByRole("button", { name: "Confirm booking" }));

    // one structured confirmation replaces the "Prepared." message (and the card)
    const card = await screen.findByRole("region", { name: "Appointment confirmed" });
    expect(screen.queryByText("Prepared.")).not.toBeInTheDocument();
    expect(screen.getAllByRole("region", { name: "Appointment confirmed" })).toHaveLength(1);
    expect(card).toHaveTextContent("20300102-0001"); // the reference starts with the appointment date
    expect(screen.getByTestId("appointment-reference")).toHaveTextContent(/^20300102-0001$/);
    expect(card).toHaveTextContent("Dr. Anil Kumar");
    expect(card).toHaveTextContent("General Physician");
    expect(card).toHaveTextContent("Wed, 2 Jan 2030");
    expect(card).toHaveTextContent("10:00 AM – 10:30 AM");
    expect(card).toHaveTextContent("Asha Rao");
    expect(card).toHaveTextContent("₹500");
    expect(card).toHaveTextContent(/WhatsApp updatesNo/);
    expect(card).toHaveTextContent("arrive 10 minutes early");
    expect(card.querySelector('a[href="/my-appointments"]')).not.toBeNull();
    expect(api.confirmChatBooking).toHaveBeenCalledWith({
      proposal_token: "signed.proposal.token",
      patient_name: "Asha Rao",
      phone: "9876543210",
      notification_consent: false,
    });
    expect(screen.queryByRole("form", { name: "Confirm booking" })).not.toBeInTheDocument();
    // personal details are never part of what is sent to the assistant
    expect(JSON.stringify(api.sendChat.mock.calls)).not.toContain("9876543210");
  });

  it("explains when the proposed slot was just taken", async () => {
    api.sendChat.mockResolvedValue({ reply: "Prepared.", guard: "none", proposal: PROPOSAL });
    api.confirmChatBooking.mockRejectedValue(new ApiError("taken", 409, "slot_unavailable"));
    const user = await openChat();
    await ask(user, "book");
    await screen.findByRole("form", { name: "Confirm booking" });
    await user.type(screen.getByLabelText("Your name"), "Asha Rao");
    await user.type(screen.getByLabelText("Mobile number"), "9876543210");
    await user.click(screen.getByLabelText("No, thanks"));
    await user.click(screen.getByRole("button", { name: "Confirm booking" }));
    expect(await screen.findByText(/just taken/i)).toBeInTheDocument();
  });

  it("drops a stale proposal when the user asks something new", async () => {
    api.sendChat.mockResolvedValueOnce({ reply: "Prepared.", guard: "none", proposal: PROPOSAL });
    const user = await openChat();
    await ask(user, "book");
    await screen.findByRole("form", { name: "Confirm booking" });
    api.sendChat.mockResolvedValueOnce({ reply: "Anything else?", guard: "none", proposal: null });
    await ask(user, "never mind");
    await screen.findByText("Anything else?");
    expect(screen.queryByRole("form", { name: "Confirm booking" })).not.toBeInTheDocument();
  });
});


const OFFER = {
  doctor_id: "11111111-1111-4111-8111-111111111111",
  doctor_name: "Dr. Priya Sharma",
  date: "2030-01-07",
  date_label: "Mon, 7 Jan 2030",
  times: [
    { time: "10:00", label: "10:00 AM" },
    { time: "16:30", label: "4:30 PM" },
  ],
};

describe("ChatWidget: offered times never get lost", () => {
  it("shows the offered times as buttons and sends the pick together with the doctor and date", async () => {
    api.sendChat.mockResolvedValueOnce({
      reply: "Open times for Dr. Priya Sharma.",
      guard: "none",
      proposal: null,
      slots: OFFER,
      clear_slots: false,
    });
    const user = await openChat();
    await ask(user, "2030-01-07");

    const picker = await screen.findByRole("region", { name: /Open times for Dr\. Priya Sharma on Mon, 7 Jan 2030/ });
    expect(picker).toHaveTextContent("Dr. Priya Sharma");
    expect(picker).toHaveTextContent("Mon, 7 Jan 2030");

    api.sendChat.mockResolvedValueOnce({ reply: "Prepared.", guard: "none", proposal: PROPOSAL, slots: null, clear_slots: true });
    await user.click(screen.getByRole("button", { name: "10:00 AM" }));

    await screen.findByRole("form", { name: "Confirm booking" });
    const [messages, context] = api.sendChat.mock.calls[1];
    expect(messages.at(-1)).toEqual({ role: "user", content: "Book 10:00 AM" });
    expect(context).toEqual(OFFER); // the server knows which doctor and date "10:00 AM" refers to
    expect(screen.queryByRole("region", { name: /Open times/ })).not.toBeInTheDocument();
  });

  it("keeps sending the offer when the patient types instead of tapping", async () => {
    api.sendChat.mockResolvedValueOnce({ reply: "Times.", guard: "none", proposal: null, slots: OFFER });
    const user = await openChat();
    await ask(user, "2030-01-07");
    await screen.findByRole("region", { name: /Open times/ });

    api.sendChat.mockResolvedValueOnce({ reply: "Ok.", guard: "none", proposal: null });
    await ask(user, "Morning: 10:00 AM");
    await screen.findByText("Ok.");
    expect(api.sendChat.mock.calls[1][1]).toEqual(OFFER);
    // an answer without new slots does not wipe what the patient can still pick
    expect(screen.getByRole("region", { name: /Open times/ })).toBeInTheDocument();
  });

  it("drops the old offer when the date just checked has no times", async () => {
    api.sendChat.mockResolvedValueOnce({ reply: "Times.", guard: "none", proposal: null, slots: OFFER });
    const user = await openChat();
    await ask(user, "2030-01-07");
    await screen.findByRole("region", { name: /Open times/ });

    api.sendChat.mockResolvedValueOnce({ reply: "No times on that date. Try Tue, 8 Jan 2030?", guard: "none", proposal: null, slots: null, clear_slots: true });
    await ask(user, "2030-01-12");
    await screen.findByText(/No times on that date/);
    expect(screen.queryByRole("region", { name: /Open times/ })).not.toBeInTheDocument();
  });

  it("starts clean after New chat", async () => {
    api.sendChat.mockResolvedValueOnce({ reply: "Times.", guard: "none", proposal: null, slots: OFFER });
    const user = await openChat();
    await ask(user, "2030-01-07");
    await screen.findByRole("region", { name: /Open times/ });
    await user.click(screen.getByRole("button", { name: "New chat" }));
    expect(screen.queryByRole("region", { name: /Open times/ })).not.toBeInTheDocument();

    api.sendChat.mockResolvedValueOnce({ reply: "Hello.", guard: "none", proposal: null });
    await ask(user, "hi");
    await screen.findByText("Hello.");
    expect(api.sendChat.mock.calls[1][1]).toBeNull();
  });
});


describe("ChatWidget: booking confirmation", () => {
  it("keeps a plain-text summary of the confirmation for later chat turns", async () => {
    api.sendChat.mockResolvedValueOnce({ reply: "Prepared.", guard: "none", proposal: PROPOSAL });
    api.confirmChatBooking.mockResolvedValue(CONFIRMED);
    const user = await openChat();
    await ask(user, "book dr anil");
    await screen.findByRole("form", { name: "Confirm booking" });
    await user.type(screen.getByLabelText("Your name"), "Asha Rao");
    await user.type(screen.getByLabelText("Mobile number"), "9876543210");
    await user.click(screen.getByLabelText("Yes, message me"));
    await user.click(screen.getByRole("button", { name: "Confirm booking" }));
    await screen.findByRole("region", { name: "Appointment confirmed" });

    api.confirmChatBooking.mockReset();
    api.sendChat.mockResolvedValueOnce({ reply: "You're welcome.", guard: "none", proposal: null });
    await ask(user, "thanks");
    await screen.findByText("You're welcome.");
    const sent = api.sendChat.mock.calls[1][0] as { role: string; content: string }[];
    expect(sent.some((m) => m.role === "assistant" && m.content.includes("20300102-0001"))).toBe(true);
    expect(JSON.stringify(sent)).not.toContain("9876543210"); // the phone number never reaches the model
  });

  it("shows WhatsApp updates as Yes when the patient opted in", async () => {
    api.sendChat.mockResolvedValueOnce({ reply: "Prepared.", guard: "none", proposal: PROPOSAL });
    api.confirmChatBooking.mockResolvedValue({ ...CONFIRMED, notification_consent: true });
    const user = await openChat();
    await ask(user, "book dr anil");
    await screen.findByRole("form", { name: "Confirm booking" });
    await user.type(screen.getByLabelText("Your name"), "Asha Rao");
    await user.type(screen.getByLabelText("Mobile number"), "9876543210");
    await user.click(screen.getByLabelText("Yes, message me"));
    await user.click(screen.getByRole("button", { name: "Confirm booking" }));
    const card = await screen.findByRole("region", { name: "Appointment confirmed" });
    expect(card).toHaveTextContent(/WhatsApp updatesYes/);
  });
});
