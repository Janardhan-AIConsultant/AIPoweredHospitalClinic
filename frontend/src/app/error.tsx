"use client";

import { Button } from "@/components/ui";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="space-y-4 py-10 text-center">
      <h1 className="text-3xl font-bold">Something went wrong</h1>
      <p className="text-muted">Please try again.</p>
      <Button onClick={reset}>Try again</Button>
    </div>
  );
}
