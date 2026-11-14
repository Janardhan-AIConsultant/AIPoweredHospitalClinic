import type { Metadata } from "next";
import { Alert } from "@/components/ui";

export const metadata: Metadata = { title: "Privacy" };

const H2 = "mt-8 text-xl font-semibold";

export default function PrivacyPage() {
  return (
    <article className="mx-auto max-w-2xl space-y-3 leading-relaxed">
      <h1 className="text-3xl font-bold">How we handle your information</h1>
      <Alert tone="info">
        Draft for the clinic&apos;s legal review. It describes what this website actually does today; the
        clinic must add its legal entity, contact details, retention periods and complaint process before launch.
      </Alert>

      <h2 className={H2}>What we collect</h2>
      <p>
        To book an appointment: your name, mobile number, the doctor and time you choose, and optionally your
        email address and a short reason for the visit. You do not need an account.
      </p>

      <h2 className={H2}>How it is protected</h2>
      <ul className="list-disc space-y-1 pl-5">
        <li>Mobile numbers and email addresses are encrypted before they are stored.</li>
        <li>Clinic staff see mobile numbers only in masked form (for example +91*****3210).</li>
        <li>
          Names and visit reasons are stored in the clinic&apos;s database, which is encrypted by the hosting
          provider, but they are not separately encrypted fields.
        </li>
        <li>Our logs do not contain names, phone numbers, email addresses or chat messages.</li>
      </ul>

      <h2 className={H2}>WhatsApp messages</h2>
      <p>
        If you tick the box when booking, we send your confirmation, any change or cancellation and a reminder
        on WhatsApp. Reply STOP at any time to stop messages. When you ask to view your appointments we send a
        one-time verification code to your number on WhatsApp.
      </p>

      <h2 className={H2}>The chat assistant</h2>
      <p>
        The assistant helps you find a doctor and prepare a booking. It cannot give medical advice, and it cannot
        confirm a booking by itself: you enter your details in a separate form that goes straight to the clinic.
        Phone numbers and email addresses typed into the chat are masked before the message is processed by the
        AI service. Chat messages are not stored by the clinic. Please do not share health details in the chat.
      </p>

      <h2 className={H2}>How long we keep it</h2>
      <p>
        Verification codes are deleted after one day and sign-in sessions after they expire. Finished message
        records are deleted after 90 days. [Clinic to state how long appointment records are kept.]
      </p>

      <h2 className={H2}>Your choices</h2>
      <p>
        You can ask the clinic to correct or delete your information. [Clinic to add contact details and the
        process for these requests.]
      </p>
    </article>
  );
}
