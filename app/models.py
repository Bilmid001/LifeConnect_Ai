from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone
from .database import Base

def now():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(40), default="")
    profile_image_url: Mapped[str] = mapped_column(String(255), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30), default="donor")
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    donor_profile = relationship("DonorProfile", back_populates="user", uselist=False)
    memberships = relationship("FacilityMembership", back_populates="user")

class DonorProfile(Base):
    __tablename__ = "donor_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    broad_location: Mapped[str] = mapped_column(String(120), default="Jos, Plateau")
    preferred_language: Mapped[str] = mapped_column(String(40), default="English")
    blood_group: Mapped[str] = mapped_column(String(12), default="Not provided")
    availability_status: Mapped[str] = mapped_column(String(30), default="available")
    radius_km: Mapped[int] = mapped_column(Integer, default=25)
    consent_status: Mapped[bool] = mapped_column(Boolean, default=False)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sms_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    inapp_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    quiet_hours: Mapped[str] = mapped_column(String(60), default="21:00–07:00")
    user = relationship("User", back_populates="donor_profile")

class Facility(Base):
    __tablename__ = "facilities"
    id: Mapped[int] = mapped_column(primary_key=True)
    legal_name: Mapped[str] = mapped_column(String(180))
    facility_type: Mapped[str] = mapped_column(String(50), default="Hospital")
    address: Mapped[str] = mapped_column(String(240))
    contact_details: Mapped[str] = mapped_column(String(180), default="")
    verification_status: Mapped[str] = mapped_column(String(30), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    memberships = relationship("FacilityMembership", back_populates="facility")

class FacilityMembership(Base):
    __tablename__ = "facility_memberships"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"))
    role: Mapped[str] = mapped_column(String(40), default="staff")
    status: Mapped[str] = mapped_column(String(30), default="active")
    user = relationship("User", back_populates="memberships")
    facility = relationship("Facility", back_populates="memberships")

class BloodRequest(Base):
    __tablename__ = "blood_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    blood_group: Mapped[str] = mapped_column(String(12))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    urgency: Mapped[str] = mapped_column(String(30), default="standard")
    location: Mapped[str] = mapped_column(String(180))
    contact_person: Mapped[str] = mapped_column(String(120), default="")
    expires_at: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(40), default="draft")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Invitation(Base):
    __tablename__ = "donor_invitations"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("blood_requests.id"))
    donor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    channel: Mapped[str] = mapped_column(String(30), default="in-app")
    delivery_status: Mapped[str] = mapped_column(String(30), default="queued")
    response_status: Mapped[str] = mapped_column(String(30), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Notification(Base):
    __tablename__ = "notification_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(180))
    message: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40), default="update")
    status: Mapped[str] = mapped_column(String(30), default="sent")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(140))
    entity_type: Mapped[str] = mapped_column(String(50), default="")
    entity_id: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"))
    plan: Mapped[str] = mapped_column(String(80), default="Community Free")
    status: Mapped[str] = mapped_column(String(30), default="trial")
    period_end: Mapped[str] = mapped_column(String(40), default="")

class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    price_label: Mapped[str] = mapped_column(String(40))
    staff_seats: Mapped[int] = mapped_column(Integer, default=3)
    monthly_requests: Mapped[int] = mapped_column(Integer, default=10)
    features: Mapped[str] = mapped_column(Text, default="")
