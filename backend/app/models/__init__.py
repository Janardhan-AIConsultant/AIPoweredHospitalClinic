"""Import every model so Base.metadata is complete for Alembic and tests."""

from app.models.accounts import Patient, User
from app.models.appointments import Appointment
from app.models.auth import RefreshToken
from app.models.doctors import Doctor, DoctorLeave, DoctorSchedule, Specialization
from app.models.notifications import NotificationLog, NotificationOutbox
from app.models.otp import OtpChallenge
from app.models.system import AuditLog, ChatbotFeedback, ClinicSetting

__all__ = [
    "Appointment",
    "AuditLog",
    "ChatbotFeedback",
    "ClinicSetting",
    "Doctor",
    "DoctorLeave",
    "DoctorSchedule",
    "NotificationLog",
    "NotificationOutbox",
    "OtpChallenge",
    "Patient",
    "RefreshToken",
    "RefreshToken",
    "Specialization",
    "User",
]
