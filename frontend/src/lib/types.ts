export interface Specialization {
  id: string;
  name: string;
  description: string | null;
}

export interface Schedule {
  weekday: number; // Monday = 0 .. Sunday = 6
  session_type: "MORNING" | "EVENING";
  start_time: string;
  end_time: string;
  break_start: string | null;
  break_end: string | null;
}

export interface Doctor {
  id: string;
  full_name: string;
  qualifications: string | null;
  experience_years: number;
  consultation_fee: string;
  bio: string | null;
  photo_url: string | null;
  specialization: Specialization;
  schedules: Schedule[];
}

export interface Slot {
  start_time: string;
  end_time: string;
}

export interface SlotsResponse {
  doctor_id: string;
  date: string;
  slots: Slot[];
}

export interface BookingRequest {
  doctor_id: string;
  date: string;
  start_time: string;
  patient_name: string;
  phone: string;
  email?: string | null;
  reason_for_visit?: string | null;
  notification_consent: boolean;
}

export interface Appointment {
  appointment_reference: string;
  doctor_id: string;
  doctor_name: string;
  specialization: string;
  appointment_date: string;
  start_time: string;
  end_time: string;
  consultation_fee: string;
  status: string;
  patient_name: string;
  reason_for_visit: string | null;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ProposalSummary {
  doctor_name: string;
  specialization: string;
  date: string;
  start_time: string;
  fee: string;
}

export interface Proposal {
  token: string;
  summary: ProposalSummary;
}

export interface ChatResponse {
  reply: string;
  guard: "none" | "emergency" | "injection" | "medical";
  proposal: Proposal | null;
}

export interface ChatConfirmRequest {
  proposal_token: string;
  patient_name: string;
  phone: string;
  email?: string | null;
  notification_consent: boolean;
}

// ---------------------------------------------------------------- staff & patient portal
export type StaffRole = "ADMIN" | "DOCTOR";

export interface StaffUser {
  id: string;
  email: string;
  role: StaffRole;
  doctor_id: string | null;
  is_active: boolean;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: StaffUser;
}

export interface PatientToken {
  access_token: string;
  expires_in: number;
}

export interface StaffAppointment {
  appointment_reference: string;
  patient_name: string;
  patient_phone_masked: string;
  doctor_id: string;
  doctor_name: string;
  appointment_date: string;
  start_time: string;
  end_time: string;
  status: string;
  reason_for_visit: string | null;
  consultation_fee: string;
  notification_consent: boolean;
}

export interface AppointmentPage {
  items: StaffAppointment[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminDoctor {
  id: string;
  full_name: string;
  specialization: string;
  consultation_fee: string;
  is_active: boolean;
  upcoming_appointments: number;
}

export interface Leave {
  id: string;
  doctor_id: string;
  start_date: string;
  end_date: string;
  reason: string | null;
  affected_appointments: number;
}

export interface AuditEntry {
  id: string;
  created_at: string;
  actor_role: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
}

export interface Stats {
  today: string;
  today_total: number;
  today_by_status: Record<string, number>;
  upcoming_active: number;
  active_doctors: number;
  notifications: Record<string, number>;
}

export interface AppointmentFilters {
  date_from?: string;
  date_to?: string;
  status?: string;
  doctor_id?: string;
}
