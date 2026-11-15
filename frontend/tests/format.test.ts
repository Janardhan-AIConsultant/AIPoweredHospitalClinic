import { describe, expect, it } from "vitest";
import {
  addDays,
  clinicToday,
  formatDate,
  formatFee,
  formatTime,
  isValidIndianMobile,
  weekdayIndex,
  workingDays,
} from "@/lib/format";

describe("format", () => {
  it("formats times in 12-hour clock", () => {
    expect(formatTime("09:00:00")).toBe("9:00 AM");
    expect(formatTime("12:30:00")).toBe("12:30 PM");
    expect(formatTime("00:05:00")).toBe("12:05 AM");
    expect(formatTime("17:00")).toBe("5:00 PM");
  });

  it("does not shift dates across timezones", () => {
    expect(formatDate("2030-01-07")).toContain("7 Jan 2030");
    expect(addDays("2030-01-31", 1)).toBe("2030-02-01");
    expect(addDays("2030-03-01", -1)).toBe("2030-02-28");
  });

  it("maps weekdays Monday=0 like the backend", () => {
    expect(weekdayIndex("2030-01-07")).toBe(0); // Monday
    expect(weekdayIndex("2030-01-13")).toBe(6); // Sunday
  });

  it("computes today in the clinic timezone", () => {
    // 20:00 UTC on 6 Jan is already 7 Jan 01:30 in India.
    expect(clinicToday(new Date("2030-01-06T20:00:00Z"))).toBe("2030-01-07");
    expect(clinicToday(new Date("2030-01-06T10:00:00Z"))).toBe("2030-01-06");
  });

  it("formats fee and working days", () => {
    expect(formatFee("1000.00")).toMatch(/1,000/);
    expect(workingDays([4, 0, 2, 0])).toBe("Mon, Wed, Fri");
  });

  it("validates Indian mobile numbers", () => {
    for (const ok of ["9876543210", "+91 98765 43210", "09876543210"]) {
      expect(isValidIndianMobile(ok)).toBe(true);
    }
    for (const bad of ["12345", "5876543210", "98765432101", ""]) {
      expect(isValidIndianMobile(bad)).toBe(false);
    }
  });
});
