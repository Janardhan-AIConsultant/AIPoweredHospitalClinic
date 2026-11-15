import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, createAppointment, getSlots } from "@/lib/api";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockImplementation(async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("builds the slots URL and parses the response", async () => {
    const fn = mockFetch(200, { doctor_id: "d", date: "2030-01-07", slots: [] });
    const res = await getSlots("abc", "2030-01-07");
    expect(res.slots).toEqual([]);
    expect(fn.mock.calls[0][0]).toBe(
      "http://localhost:8000/doctors/abc/slots?date=2030-01-07",
    );
  });

  it("sends the idempotency key and JSON body", async () => {
    const fn = mockFetch(201, { appointment_reference: "ABC" });
    await createAppointment(
      {
        doctor_id: "d",
        date: "2030-01-07",
        start_time: "09:00",
        patient_name: "Asha",
        phone: "9876543210",
        notification_consent: false,
      },
      "key-1234",
    );
    const init = fn.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["Idempotency-Key"]).toBe(
      "key-1234",
    );
  });

  it("surfaces the safe error envelope and field errors", async () => {
    mockFetch(422, {
      error: {
        code: "validation_error",
        message: "Invalid request.",
        details: [{ field: "body.phone", message: "bad phone" }],
      },
    });
    const err = await getSlots("a", "b").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    const api = err as ApiError;
    expect(api.status).toBe(422);
    expect(api.code).toBe("validation_error");
    expect(api.fieldErrors.phone).toBe("bad phone");
  });

  it("maps network failures to a friendly error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("boom")));
    const err = (await getSlots("a", "b").catch((e: unknown) => e)) as ApiError;
    expect(err.code).toBe("network_error");
    expect(err.message).not.toContain("boom");
  });

  it("tolerates non-JSON error bodies", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("<html>", { status: 502 })),
    );
    const err = (await getSlots("a", "b").catch((e: unknown) => e)) as ApiError;
    expect(err.status).toBe(502);
    expect(err.code).toBe("http_error");
  });
});

describe("staff and patient api", () => {
  it("sends credentials and a CSRF header for cookie endpoints", async () => {
    const fn = mockFetch(200, { access_token: "t" });
    await staffRefreshForTest();
    const [url, init] = fn.mock.calls[0];
    expect(url).toBe("http://localhost:8000/auth/refresh");
    expect(init.credentials).toBe("include");
    expect(init.headers["X-CSRF-Token"]).toBe("1");
  });

  it("returns undefined for 204 responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    const { staffLogout } = await import("@/lib/api");
    await expect(staffLogout()).resolves.toBeUndefined();
  });

  it("sends the bearer token and skips empty filters", async () => {
    const fn = mockFetch(200, { items: [], total: 0, limit: 100, offset: 0 });
    const { getStaffAppointments } = await import("@/lib/api");
    await getStaffAppointments("tok", "DOCTOR", { date_from: "2030-01-01", status: "" });
    const [url, init] = fn.mock.calls[0];
    expect(url).toBe("http://localhost:8000/doctor/appointments?date_from=2030-01-01&limit=100");
    expect(init.headers.Authorization).toBe("Bearer tok");
  });

  it("routes leave creation by role", async () => {
    const fn = mockFetch(201, {});
    const { addLeave } = await import("@/lib/api");
    await addLeave("t", "ADMIN", "d1", { start_date: "a", end_date: "b" });
    await addLeave("t", "DOCTOR", null, { start_date: "a", end_date: "b" });
    expect(fn.mock.calls[0][0]).toBe("http://localhost:8000/admin/doctors/d1/leave");
    expect(fn.mock.calls[1][0]).toBe("http://localhost:8000/doctor/leave");
  });

  it("patient calls carry the token and JSON bodies", async () => {
    const fn = mockFetch(200, {});
    const { rescheduleMyAppointment, verifyOtp } = await import("@/lib/api");
    await verifyOtp("9876543210", "123456");
    await rescheduleMyAppointment("tok", "REF1", "2030-01-02", "10:00");
    expect(JSON.parse(fn.mock.calls[0][1].body)).toEqual({ phone: "9876543210", code: "123456" });
    expect(fn.mock.calls[1][1].headers.Authorization).toBe("Bearer tok");
    expect(JSON.parse(fn.mock.calls[1][1].body)).toEqual({ date: "2030-01-02", start_time: "10:00" });
  });
});

async function staffRefreshForTest() {
  const { staffRefresh } = await import("@/lib/api");
  return staffRefresh();
}
