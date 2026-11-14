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

beforeEach(() => {
  api.sendChat.mockReset();
  api.confirmChatBooking.mockReset();
});

async function openChat() {
  const user = userEvent.setup();
  render(<ChatWidget />);
  await user.click(screen.getByRole("button", { name: "Chat with us" }));
  return user;
}

async function ask(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.type(screen.getByLabelText("Your message"), text);
  await user.click(screen.getByRole("button", { name: "Send" }));
}

describe("ChatWidget", () => {
  it("opens, shows the safety banner and closes", async () => {
    const user = await openChat();
    expect(screen.getByRole("dialog", { name: "Appointment assistant" })).toBeInTheDocument();
    expect(screen.getByText(/No medical advice/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close chat" }));
    expect(screen.getByRole("button", { name: "Chat with us" })).toBeInTheDocument();
  });

  it("sends the conversation and renders the reply", async () => {
    api.sendChat.mockResolvedValue({ reply: "We have Cardiologist.", guard: "none", proposal: null });
    const user = await openChat();
    await ask(user, "which specialties");
    expect(await screen.findByText("We have Cardiologist.")).toBeInTheDocument();
    expect(api.sendChat).toHaveBeenCalledWith([{ role: "user", content: "which specialties" }]);

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
    expect(bubble.className).toContain("text-danger");
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
    api.confirmChatBooking.mockResolvedValue({
      appointment_reference: "ABCDE23456",
      doctor_name: "Dr. Anil Kumar",
      appointment_date: "2030-01-02",
      start_time: "10:00:00",
    });
    const user = await openChat();
    await ask(user, "book dr anil");
    const form = await screen.findByRole("form", { name: "Confirm booking" });
    expect(form).toHaveTextContent("Dr. Anil Kumar");

    await user.click(screen.getByRole("button", { name: "Confirm booking" }));
    expect(await screen.findByText("Enter your full name.")).toBeInTheDocument();
    expect(api.confirmChatBooking).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText("Your name"), "Asha Rao");
    await user.type(screen.getByLabelText("Mobile number"), "9876543210");
    await user.click(screen.getByRole("button", { name: "Confirm booking" }));

    expect(await screen.findByText(/ABCDE23456/)).toBeInTheDocument();
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
