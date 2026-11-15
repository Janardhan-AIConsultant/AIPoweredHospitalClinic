"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { useStaffSession } from "@/lib/staff-session";
import { Alert, Button, Card, Field, TextInput } from "../ui";

export function StaffLogin() {
  const router = useRouter();
  const { status, login } = useStaffSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (status === "authed") router.replace("/staff");
  }, [status, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password) {
      setError("Enter your email and password.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
      router.replace("/staff");
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 429
          ? "Too many attempts. Please wait a minute."
          : err instanceof ApiError
            ? err.message
            : "Something went wrong. Please try again.",
      );
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm space-y-6">
      <h1 className="text-3xl font-bold">Staff sign in</h1>
      <Card>
        <form onSubmit={submit} noValidate className="space-y-4" aria-label="Staff sign in">
          {error && <Alert>{error}</Alert>}
          <Field id="staff-email" label="Email">
            <TextInput
              id="staff-email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>
          <Field id="staff-password" label="Password">
            <TextInput
              id="staff-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
