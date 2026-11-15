from .models import User, DonorProfile, Facility, FacilityMembership, BloodRequest, Notification, AuditLog, Subscription, Plan
from .security import hash_password

def seed(db):
    if db.query(User).count():
        return
    admin = User(name="Amina Yusuf", email="admin@lifeconnect.demo", phone="+234 800 000 0001", password_hash=hash_password("Demo123!"), role="admin")
    staff = User(name="Dr. Daniel Musa", email="staff@lifeconnect.demo", phone="+234 800 000 0002", password_hash=hash_password("Demo123!"), role="facility")
    donor = User(name="Sarah James", email="donor@lifeconnect.demo", phone="+234 800 000 0003", password_hash=hash_password("Demo123!"), role="donor")
    db.add_all([admin, staff, donor]); db.flush()
    facility = Facility(legal_name="Plateau Community Medical Centre (Demo)", facility_type="Hospital", address="Rayfield, Jos, Plateau State, Nigeria", contact_details="demo@facility.example", verification_status="pending")
    db.add(facility); db.flush()
    db.add(FacilityMembership(user_id=staff.id, facility_id=facility.id, role="administrator"))
    db.add(DonorProfile(user_id=donor.id, broad_location="Jos, Plateau State", preferred_language="Hausa", blood_group="O+", availability_status="available", radius_km=25, consent_status=True))
    req1 = BloodRequest(reference="LC-2026-001", facility_id=facility.id, created_by=staff.id, blood_group="O+", quantity=3, urgency="urgent", location="Rayfield, Jos", contact_person="Duty Blood Bank Officer", status="submitted", notes="Synthetic demo request. Facility review required.")
    req2 = BloodRequest(reference="LC-2026-002", facility_id=facility.id, created_by=staff.id, blood_group="A+", quantity=2, urgency="standard", location="Rayfield, Jos", contact_person="Duty Blood Bank Officer", status="submitted", notes="Synthetic demo request.")
    db.add_all([req1, req2]); db.flush()
    db.add(Notification(recipient_id=staff.id, title="Facility verification pending", message="Complete the facility verification workflow before activating public donor outreach.", category="verification"))
    db.add_all([
        Plan(name="Community Free", price_label="Free", staff_seats=2, monthly_requests=5, features="Basic dashboard, in-app notifications"),
        Plan(name="Clinic Starter", price_label="Contact us", staff_seats=5, monthly_requests=30, features="Email alerts, request history, standard reports"),
        Plan(name="Hospital Professional", price_label="Contact us", staff_seats=25, monthly_requests=200, features="Advanced dashboards, bulk outreach review, audit exports"),
        Plan(name="Enterprise / Network", price_label="Custom", staff_seats=100, monthly_requests=1000, features="Multi-facility administration, API integrations, custom roles")
    ])
    db.add(Subscription(facility_id=facility.id, plan="Community Free", status="demo"))
    db.add(AuditLog(actor_id=admin.id, action="Seeded synthetic demo environment", entity_type="system", entity_id="1"))
    db.commit()
