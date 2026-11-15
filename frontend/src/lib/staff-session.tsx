"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiError, staffLogin, staffLogout, staffRefresh } from "./api";
import type { LoginResponse, StaffUser } from "./types";

type Status = "loading" | "anon" | "authed";

interface SessionValue {
  status: Status;
  user: StaffUser | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Run an authenticated call; on 401 refresh once and retry, otherwise end the session. */
  call: <T>(fn: (token: string) => Promise<T>) => Promise<T>;
}

const Ctx = createContext<SessionValue | null>(null);

// Refresh tokens rotate and are single-use: concurrent refreshes (React StrictMode, two components)
// must share one request or the second would look like token theft to the server.
let inflight: Promise<LoginResponse> | null = null;
function sharedRefresh(): Promise<LoginResponse> {
  inflight ??= staffRefresh().finally(() => {
    inflight = null;
  });
  return inflight;
}

/** Holds the short-lived access token in memory only (never localStorage). */
export function StaffSessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [user, setUser] = useState<StaffUser | null>(null);
  const token = useRef<string | null>(null);

  const adopt = useCallback((res: LoginResponse) => {
    token.current = res.access_token;
    setUser(res.user);
    setStatus("authed");
  }, []);

  const drop = useCallback(() => {
    token.current = null;
    setUser(null);
    setStatus("anon");
  }, []);

  useEffect(() => {
    let alive = true;
    sharedRefresh()
      .then((res) => alive && adopt(res))
      .catch(() => alive && drop());
    return () => {
      alive = false;
    };
  }, [adopt, drop]);

  const login = useCallback(
    async (email: string, password: string) => adopt(await staffLogin(email, password)),
    [adopt],
  );

  const logout = useCallback(async () => {
    try {
      await staffLogout();
    } finally {
      drop();
    }
  }, [drop]);

  const call = useCallback(
    async <T,>(fn: (t: string) => Promise<T>): Promise<T> => {
      if (!token.current) throw new ApiError("Please sign in.", 401, "unauthenticated");
      try {
        return await fn(token.current);
      } catch (e) {
        if (!(e instanceof ApiError) || e.status !== 401) throw e;
      }
      try {
        adopt(await sharedRefresh());
      } catch {
        drop();
        throw new ApiError("Your session has expired. Please sign in again.", 401, "unauthenticated");
      }
      return fn(token.current!);
    },
    [adopt, drop],
  );

  const value = useMemo(
    () => ({ status, user, login, logout, call }),
    [status, user, login, logout, call],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStaffSession(): SessionValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useStaffSession must be used inside StaffSessionProvider");
  return v;
}
