import type { Metadata } from "next";
import { Geist } from "next/font/google";
import { ChatWidget } from "@/components/chat-widget";
import { SiteFooter, SiteHeader } from "@/components/site-chrome";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "Bindu Clinic — Book a doctor appointment online",
    template: "%s · Bindu Clinic",
  },
  description:
    "Find a doctor and book an appointment at Bindu Clinic in a few taps. No account needed.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:rounded focus:bg-surface focus:px-3 focus:py-2"
        >
          Skip to content
        </a>
        <SiteHeader />
        <main id="main" className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">
          {children}
        </main>
        <SiteFooter />
        <ChatWidget />
      </body>
    </html>
  );
}
