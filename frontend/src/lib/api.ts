import type {
  AdminDoctor,
  Appointment,
  AppointmentFilters,
  AppointmentPage,
  AuditEntry,
  BookingRequest,
  ChatConfirmRequest,
  ChatMessage,
  ChatResponse,
  SlotsOffer,
  Doctor,
  Leave,
  LoginResponse,
  PatientToken,
  SlotsResponse,
  Specialization,
  Stats,
  StaffAppointment,
  StaffRole,
  StaffUser,
} from "./types";

// Browser: NEXT_PUBLIC_API_URL, either an absolute API origin or "/api" (same-origin proxy, see next.config.ts).
// Server components cannot use a relative URL, so they call the backend directly via API_INTERNAL_URL.
const PUBLIC_API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const API_URL = (
  typeof window === "undefined" && process.env.API_INTERNAL_URL
    ? process.env.API_INTERNAL_URL
    : PUBLIC_API_URL
).replace(/\/$/, "");

/** Error returned by the backend's safe error envelope (or a network failure). */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly fieldErrors: Record<string, string> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface ErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
    details?: { field: string; message: string }[];
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      cache: "no-store",
      ...init,
      headers: { Accept: "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(
      "We could not reach the clinic service. Please try again.",
      0,
      "network_error",
    );
  }
  if (!res.ok) {
    let body: ErrorEnvelope = {};
    try {
      body = (await res.json()) as ErrorEnvelope;
    } catch {
      /* non-JSON error body */
    }
    const fieldErrors: Record<string, string> = {};
    for (const d of body.error?.details ?? []) {
      fieldErrors[d.field.split(".").pop() ?? d.field] = d.message;
    }
    throw new ApiError(
      body.error?.message ?? "Something went wrong. Please try again.",
      res.status,
      body.error?.code ?? "http_error",
      fieldErrors,
    );
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const JSON_HEADERS = { "Content-Type": "application/json" };
const bearer = (token: string) => ({ Authorization: `Bearer ${token}` });
const post = (body?: unknown) => ({
  method: "POST",
  headers: JSON_HEADERS,
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const getSpecializations = () =>
  request<Specialization[]>("/specializations");

export const getDoctors = () => request<Doctor[]>("/doctors");

export const getDoctor = (id: string) =>
  request<Doctor>(`/doctors/${encodeURIComponent(id)}`);

export const getSlots = (doctorId: string, date: string) =>
  request<SlotsResponse>(
    `/doctors/${encodeURIComponent(doctorId)}/slots?date=${encodeURIComponent(date)}`,
  );

export const createAppointment = (body: BookingRequest, idempotencyKey: string) =>
  request<Appointment>("/appointments", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify(body),
  });

export const sendChat = (messages: ChatMessage[], context: SlotsOffer | null = null) =>
  request<ChatResponse>("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(context ? { messages, context } : { messages }),
  });

export const confirmChatBooking = (body: ChatConfirmRequest) =>
  request<Appointment>("/chat/confirm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

// ------------------------------------------------------------ patient self-service (OTP)
export const requestOtp = (phone: string) =>
  request<{ message: string }>("/patient/otp/request", post({ phone }));

export const verifyOtp = (phone: string, code: string) =>
  request<PatientToken>("/patient/otp/verify", post({ phone, code }));

export const getMyAppointments = (token: string) =>
  request<Appointment[]>("/patient/appointments", { headers: bearer(token) });

export const cancelMyAppointment = (token: string, reference: string) =>
  request<Appointment>(`/patient/appointments/${encodeURIComponent(reference)}/cancel`, {
    ...post(),
    headers: { ...JSON_HEADERS, ...bearer(token) },
  });

export const rescheduleMyAppointment = (
  token: string,
  reference: string,
  date: string,
  startTime: string,
) =>
  request<Appointment>(`/patient/appointments/${encodeURIComponent(reference)}/reschedule`, {
    ...post({ date, start_time: startTime }),
    headers: { ...JSON_HEADERS, ...bearer(token) },
  });

// ------------------------------------------------------------------- staff auth
// The refresh token is an HttpOnly cookie, so these calls must send credentials.
const CSRF = { "X-CSRF-Token": "1" };

export const staffLogin = (email: string, password: string) =>
  request<LoginResponse>("/auth/login", { ...post({ email, password }), credentials: "include" });

export const staffRefresh = () =>
  request<LoginResponse>("/auth/refresh", { method: "POST", headers: CSRF, credentials: "include" });

export const staffLogout = () =>
  request<void>("/auth/logout", { method: "POST", headers: CSRF, credentials: "include" });

export const staffMe = (token: string) =>
  request<StaffUser>("/auth/me", { headers: bearer(token) });

// ------------------------------------------------------------ staff dashboards
const scope = (role: StaffRole) => (role === "ADMIN" ? "/admin" : "/doctor");
const authed = (token: string, init: RequestInit = {}): RequestInit => ({
  ...init,
  headers: { ...JSON_HEADERS, ...init.headers, ...bearer(token) },
});

export const getStaffAppointments = (
  token: string,
  role: StaffRole,
  filters: AppointmentFilters = {},
) => {
  const qs = new URLSearchParams(
    Object.entries({ ...filters, limit: "100" }).filter(([, v]) => v) as [string, string][],
  );
  return request<AppointmentPage>(`${scope(role)}/appointments?${qs}`, authed(token));
};

export const cancelStaffAppointment = (token: string, role: StaffRole, reference: string) =>
  request<Appointment>(
    `${scope(role)}/appointments/${encodeURIComponent(reference)}/cancel`,
    authed(token, post()),
  );

export const setAppointmentStatus = (
  token: string,
  role: StaffRole,
  reference: string,
  status: "COMPLETED" | "NO_SHOW",
) =>
  request<StaffAppointment>(
    `${scope(role)}/appointments/${encodeURIComponent(reference)}/status`,
    authed(token, post({ status })),
  );

export const getStats = (token: string) => request<Stats>("/admin/stats", authed(token));

export const getAdminDoctors = (token: string) =>
  request<AdminDoctor[]>("/admin/doctors", authed(token));

export const patchDoctor = (
  token: string,
  id: string,
  patch: { consultation_fee?: string; is_active?: boolean },
) =>
  request<AdminDoctor>(`/admin/doctors/${encodeURIComponent(id)}`, {
    ...authed(token),
    method: "PATCH",
    body: JSON.stringify(patch),
  });

export const getLeave = (token: string, role: StaffRole) =>
  request<Leave[]>(`${scope(role)}/leave`, authed(token));

export const addLeave = (
  token: string,
  role: StaffRole,
  doctorId: string | null,
  body: { start_date: string; end_date: string; reason?: string | null },
) =>
  request<Leave>(
    role === "ADMIN" ? `/admin/doctors/${encodeURIComponent(doctorId ?? "")}/leave` : "/doctor/leave",
    authed(token, post(body)),
  );

export const deleteLeave = (token: string, role: StaffRole, id: string) =>
  request<void>(`${scope(role)}/leave/${encodeURIComponent(id)}`, {
    ...authed(token),
    method: "DELETE",
  });

export const getAuditLogs = (token: string) =>
  request<AuditEntry[]>("/admin/audit-logs?limit=50", authed(token));
