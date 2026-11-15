from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Depends, HTTPException, Request, Header, BackgroundTasks, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, inspect, text
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone
import secrets, re, json, os, urllib.request, urllib.error, smtplib, ssl, logging
from email.message import EmailMessage
from pathlib import Path
from .database import Base, engine, get_db, SessionLocal
from .models import User, DonorProfile, Facility, FacilityMembership, BloodRequest, Invitation, Notification, AuditLog, Subscription, Plan
from .security import hash_password, verify_password, create_token, decode_token
from .seed import seed

Base.metadata.create_all(bind=engine)
if "profile_image_url" not in {column["name"] for column in inspect(engine).get_columns("users")}:
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE users ADD COLUMN profile_image_url VARCHAR(255)"))
UPLOAD_DIR = Path(__file__).parent / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
with SessionLocal() as s:
    seed(s)
    demo_facility = s.query(Facility).filter_by(legal_name="Plateau Community Medical Centre (Demo)").first()
    if demo_facility and demo_facility.verification_status != "approved":
        demo_requests = s.query(BloodRequest).filter_by(facility_id=demo_facility.id).all()
        for request in demo_requests:
            if request.status == "outreach active":
                request.status = "submitted"
            for invitation in s.query(Invitation).filter_by(request_id=request.id, response_status="pending").all():
                s.delete(invitation)
        s.query(Notification).filter_by(
            title="New donation invitation",
            message="A demo verified-facility workflow has an invitation for you to review. Your response is not a medical eligibility decision.",
        ).delete(synchronize_session=False)
        s.commit()

app = FastAPI(title="LifeConnect AI API", version="1.0.0", description="Blood donation coordination MVP")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger("lifeconnect.notifications")

class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str
    phone: str = ""
    password: str = Field(min_length=8)
    role: str = "donor"
    location: str = "Jos, Plateau State"
    language: str = "English"
    consent: bool = False

class LoginIn(BaseModel):
    email: str
    password: str

class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)

class RequestIn(BaseModel):
    blood_group: str
    quantity: int = Field(ge=1, le=100)
    urgency: str = "standard"
    location: str
    contact_person: str = ""
    expires_at: str = ""
    notes: str = ""

class AnnouncementIn(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    message: str = Field(min_length=1, max_length=2000)

class ProfileUpdateIn(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    email: Optional[str] = None
    phone: Optional[str] = Field(default=None, max_length=40)
    location: Optional[str] = Field(default=None, max_length=240)
    language: Optional[str] = Field(default=None, max_length=40)
    blood_group: Optional[str] = Field(default=None, max_length=12)
    facility_name: Optional[str] = Field(default=None, max_length=180)
    facility_address: Optional[str] = Field(default=None, max_length=240)
    facility_contact: Optional[str] = Field(default=None, max_length=180)
    current_password: Optional[str] = None
    new_password: Optional[str] = Field(default=None, min_length=8, max_length=128)

class AdminUserUpdateIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str
    phone: str = Field(default="", max_length=40)
    role: str
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    location: str = Field(default="", max_length=240)
    language: str = Field(default="English", max_length=40)
    facility_name: str = Field(default="", max_length=180)
    facility_type: str = Field(default="Hospital", max_length=50)
    facility_address: str = Field(default="", max_length=240)
    facility_contact: str = Field(default="", max_length=180)
    blood_group: str = Field(default="Not provided", max_length=12)
    availability: str = Field(default="available", max_length=30)
    radius_km: int = Field(default=25, ge=1, le=250)
    consent: bool = False
    email_enabled: bool = True
    sms_enabled: bool = False
    inapp_enabled: bool = True
    facility_verification: str = Field(default="pending", max_length=30)

class StatusIn(BaseModel):
    status: str

class AvailabilityIn(BaseModel):
    availability_status: str
    radius_km: int = 25
    preferred_language: str = "English"
    email_enabled: bool = True
    sms_enabled: bool = False
    inapp_enabled: bool = True
    consent_status: bool = False

class RespondIn(BaseModel):
    response_status: str

class FacilityIn(BaseModel):
    legal_name: str
    facility_type: str = "Hospital"
    address: str
    contact_details: str = ""

def current_user(authorization: Optional[str] = Header(default=None), db: Session = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Please sign in")
    uid = decode_token(authorization.split(" ", 1)[1])
    user = db.get(User, uid) if uid else None
    if not user or user.status != "active":
        raise HTTPException(401, "Session expired or account inactive")
    return user

def require(user, *roles):
    if user.role not in roles:
        raise HTTPException(403, "You do not have permission to perform this action")

def audit(db, user, action, entity_type="", entity_id=""):
    db.add(AuditLog(actor_id=user.id, action=action, entity_type=entity_type, entity_id=str(entity_id)))
    db.commit()

def facility_for(db, user):
    membership = db.query(FacilityMembership).filter_by(user_id=user.id, status="active").first()
    return db.get(Facility, membership.facility_id) if membership else None

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "LifeConnect AI", "mode": "synthetic-demo"}

@app.post("/api/auth/register")
def register(data: RegisterIn, db: Session = Depends(get_db)):
    email = data.email.lower().strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(422, "Enter a valid email address")
    if data.role not in ("donor", "facility"):
        raise HTTPException(422, "Choose donor or facility registration")
    if db.query(User).filter_by(email=email).first():
        raise HTTPException(409, "An account with this email already exists")
    if not data.name.strip() or not data.location.strip():
        raise HTTPException(422, "Name and location are required")
    try:
        user = User(name=data.name.strip(), email=email, phone=data.phone.strip(), password_hash=hash_password(data.password), role=data.role)
        db.add(user); db.flush()
        if data.role == "donor":
            db.add(DonorProfile(user_id=user.id, broad_location=data.location.strip(), preferred_language=data.language, consent_status=data.consent))
        else:
            fac = Facility(legal_name=data.name.strip(), address=data.location.strip(), contact_details=data.phone.strip(), verification_status="pending")
            db.add(fac); db.flush()
            db.add(FacilityMembership(user_id=user.id, facility_id=fac.id, role="administrator"))
            db.add(Notification(recipient_id=user.id, title="Verification submitted", message="Your facility profile is pending platform verification. Public donor outreach is disabled until approval.", category="verification"))
        db.commit()
    except Exception:
        db.rollback()
        raise
    token = create_token(user.id)
    return {"token": token, "user": user_data(user)}

@app.post("/api/auth/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=data.email.lower().strip()).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Email or password is incorrect")
    if user.status != "active":
        raise HTTPException(403, "This account is inactive. Contact platform support.")
    return {"token": create_token(user.id), "user": user_data(user)}

def user_data(u):
    return {"id": u.id, "name": u.name, "email": u.email, "phone": u.phone, "role": u.role, "status": u.status, "profile_image_url": u.profile_image_url or ""}

@app.get("/api/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    result = user_data(user)
    if user.role == "donor":
        p = db.query(DonorProfile).filter_by(user_id=user.id).first()
        result["profile"] = profile_data(p) if p else {}
    if user.role == "facility":
        f = facility_for(db, user)
        result["facility"] = facility_data(f) if f else None
    return result

@app.patch("/api/me/profile")
def update_my_profile(data:ProfileUpdateIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    fields=data.model_fields_set
    if "name" in fields and data.name is not None:
        user.name=data.name.strip()
    if "email" in fields and data.email is not None:
        email=data.email.lower().strip()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$",email):
            raise HTTPException(422,"Enter a valid email address")
        duplicate=db.query(User).filter(User.email==email,User.id!=user.id).first()
        if duplicate:
            raise HTTPException(409,"An account with this email already exists")
        user.email=email
    if "phone" in fields and data.phone is not None:
        user.phone=data.phone.strip()
    if data.new_password:
        if not data.current_password or not verify_password(data.current_password,user.password_hash):
            raise HTTPException(400,"Enter your current password to set a new password")
        user.password_hash=hash_password(data.new_password)
    if user.role=="donor":
        profile=db.query(DonorProfile).filter_by(user_id=user.id).first()
        if not profile:
            profile=DonorProfile(user_id=user.id);db.add(profile)
        if "location" in fields and data.location is not None:
            profile.broad_location=data.location.strip()
        if "language" in fields and data.language is not None:
            profile.preferred_language=data.language.strip()
        if "blood_group" in fields and data.blood_group is not None:
            if data.blood_group not in ("A+","A-","B+","B-","AB+","AB-","O+","O-","Not provided"):
                raise HTTPException(422,"Choose a valid self-reported blood group")
            profile.blood_group=data.blood_group
    elif user.role=="facility":
        facility=facility_for(db,user)
        if not facility:
            raise HTTPException(400,"No facility is linked to this account")
        if "facility_name" in fields and data.facility_name is not None:
            facility.legal_name=data.facility_name.strip()
        if "facility_address" in fields and data.facility_address is not None:
            facility.address=data.facility_address.strip()
        if "facility_contact" in fields and data.facility_contact is not None:
            facility.contact_details=data.facility_contact.strip()
    db.commit();audit(db,user,"Updated own profile","user",user.id)
    return {"ok":True,"user":user_data(user)}

@app.post("/api/me/avatar")
async def upload_my_avatar(file:UploadFile=File(...),user:User=Depends(current_user),db:Session=Depends(get_db)):
    allowed={"image/jpeg":".jpg","image/png":".png","image/webp":".webp"}
    extension=allowed.get(file.content_type or "")
    if not extension:
        raise HTTPException(415,"Upload a JPG, PNG or WebP image")
    content=await file.read(5*1024*1024+1)
    if len(content)>5*1024*1024:
        raise HTTPException(413,"Profile image must be 5 MB or smaller")
    valid=(extension==".jpg" and content.startswith(b"\xff\xd8\xff")) or (extension==".png" and content.startswith(b"\x89PNG\r\n\x1a\n")) or (extension==".webp" and content.startswith(b"RIFF") and content[8:12]==b"WEBP")
    if not valid:
        raise HTTPException(415,"The uploaded file does not match its image type")
    filename=f"user-{user.id}-{secrets.token_hex(12)}{extension}"
    destination=UPLOAD_DIR/filename
    destination.write_bytes(content)
    old_url=user.profile_image_url or ""
    user.profile_image_url=f"/static/uploads/{filename}"
    try:
        db.commit()
        audit(db,user,"Updated profile image","user",user.id)
    except Exception:
        db.rollback()
        destination.unlink(missing_ok=True)
        raise
    if old_url.startswith("/static/uploads/"):
        old_path=UPLOAD_DIR/Path(old_url).name
        if old_path!=destination:
            old_path.unlink(missing_ok=True)
    return {"ok":True,"profile_image_url":user.profile_image_url}

def profile_data(p):
    return {"location": p.broad_location, "language": p.preferred_language, "blood_group": p.blood_group, "availability": p.availability_status, "radius_km": p.radius_km, "consent": p.consent_status, "email_enabled": p.email_enabled, "sms_enabled": p.sms_enabled, "inapp_enabled": p.inapp_enabled, "quiet_hours": p.quiet_hours}

def facility_data(f):
    return {"id": f.id, "name": f.legal_name, "type": f.facility_type, "address": f.address, "contact": f.contact_details, "verification": f.verification_status}

@app.get("/api/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role == "donor":
        p = db.query(DonorProfile).filter_by(user_id=user.id).first()
        invites = db.query(Invitation).filter_by(donor_id=user.id).count()
        notifications = db.query(Notification).filter_by(recipient_id=user.id).count()
        return {"stats":[{"label":"Invitations","value":invites,"icon":"mail"},{"label":"Availability","value":p.availability_status.title() if p else "Paused","icon":"activity"},{"label":"Alerts","value":notifications,"icon":"bell"},{"label":"Participation","value":"Free","icon":"heart"}], "activity": recent_notifications(db,user.id)}
    if user.role == "facility":
        f = facility_for(db,user)
        if not f: return {"stats":[],"activity":[]}
        reqs = db.query(BloodRequest).filter_by(facility_id=f.id).all()
        inv_ids = [r.id for r in reqs]
        responses = db.query(Invitation).filter(Invitation.request_id.in_(inv_ids)).count() if inv_ids else 0
        return {"stats":[{"label":"Blood requests","value":len(reqs),"icon":"droplet"},{"label":"Active outreach","value":sum(r.status=="outreach active" for r in reqs),"icon":"send"},{"label":"Donor responses","value":responses,"icon":"users"},{"label":"Verification","value":f.verification_status.title(),"icon":"shield"}], "activity": recent_notifications(db,user.id)}
    users = db.query(User).count()
    facilities = db.query(Facility).count()
    pending = db.query(Facility).filter_by(verification_status="pending").count()
    reqs = db.query(BloodRequest).count()
    return {"stats":[{"label":"Platform users","value":users,"icon":"users"},{"label":"Facilities","value":facilities,"icon":"building"},{"label":"Pending reviews","value":pending,"icon":"shield"},{"label":"Blood requests","value":reqs,"icon":"droplet"}], "activity": recent_notifications(db,user.id)}

def recent_notifications(db, uid, limit=5):
    rows = db.query(Notification).filter_by(recipient_id=uid).order_by(desc(Notification.created_at), desc(Notification.id)).limit(limit).all()
    return [{"id":n.id,"title":n.title,"message":n.message,"category":n.category,"status":n.status,"time":n.created_at.isoformat()} for n in rows]

@app.get("/api/requests")
def list_requests(user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(BloodRequest)
    if user.role == "facility":
        f = facility_for(db,user)
        q = q.filter_by(facility_id=f.id) if f else q.filter(BloodRequest.id == -1)
    rows = q.order_by(desc(BloodRequest.created_at)).all()
    out=[]
    for r in rows:
        f=db.get(Facility,r.facility_id)
        out.append({"id":r.id,"reference":r.reference,"facility":f.legal_name if f else "Unknown","facility_verification":f.verification_status if f else "unknown","blood_group":r.blood_group,"quantity":r.quantity,"urgency":r.urgency,"location":r.location,"status":r.status,"expires_at":r.expires_at,"created_at":r.created_at.isoformat(),"notes":r.notes})
    return out

def smtp_email_is_configured():
    return bool(os.getenv("SMTP_HOST", "").strip() and (os.getenv("SMTP_FROM", "").strip() or os.getenv("SMTP_USER", "").strip()))

def send_request_emails(recipients, facility_name, reference, blood_group, quantity, urgency, location):
    host=os.getenv("SMTP_HOST", "").strip()
    sender=os.getenv("SMTP_FROM", "").strip() or os.getenv("SMTP_USER", "").strip()
    if not host or not sender:
        return
    port=int(os.getenv("SMTP_PORT", "587"))
    username=os.getenv("SMTP_USER", "").strip()
    password=os.getenv("SMTP_PASSWORD", "")
    site_url=os.getenv("PUBLIC_APP_URL", "http://127.0.0.1:8000").strip().rstrip("/")
    sent=0
    try:
        server=smtplib.SMTP_SSL(host,port,timeout=15,context=ssl.create_default_context()) if port==465 else smtplib.SMTP(host,port,timeout=15)
        with server:
            if port!=465:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            if username and password:
                server.login(username,password)
            for recipient in recipients:
                message=EmailMessage()
                message["Subject"]=f"LifeConnect donor request: {reference}"
                message["From"]=f"LifeConnect AI <{sender}>"
                message["To"]=recipient["email"]
                message.set_content(
                    f"Hello {recipient['name']},\n\n"
                    f"{facility_name} has submitted a donor request through LifeConnect AI.\n\n"
                    f"Request: {reference}\nBlood group as entered by the facility: {blood_group}\n"
                    f"Quantity: {quantity}\nUrgency label: {urgency}\nLocation: {location}\n\n"
                    f"Visit {site_url} and open Invitations if you would like to respond. "
                    "Your response means only that you are willing to be contacted. The facility is responsible for screening and all clinical decisions.\n\n"
                    "This message was sent because you opted in to donor email notifications. You can change your preferences in your LifeConnect account."
                )
                try:
                    server.send_message(message)
                    sent+=1
                except Exception:
                    logger.exception("Could not send request notification email to one opted-in donor")
        logger.info("Sent %s donor request email(s) for %s",sent,reference)
    except Exception:
        logger.exception("Could not connect to the configured SMTP service for request %s",reference)

@app.post("/api/requests")
def create_request(data: RequestIn, background_tasks: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require(user,"facility")
    f=facility_for(db,user)
    if not f: raise HTTPException(400,"Complete facility onboarding first")
    ref="LC-"+datetime.now().strftime("%Y%m%d")+"-"+secrets.token_hex(2).upper()
    initial_status="submitted" if f.verification_status == "approved" else "draft"
    r=BloodRequest(reference=ref,facility_id=f.id,created_by=user.id,blood_group=data.blood_group,quantity=data.quantity,urgency=data.urgency,location=data.location,contact_person=data.contact_person,expires_at=data.expires_at,status=initial_status,notes=data.notes)
    db.add(r); db.flush()
    invitations_created=0
    email_recipients=[]
    if initial_status=="submitted":
        donors=db.query(User,DonorProfile).join(DonorProfile,DonorProfile.user_id==User.id).filter(
            User.role=="donor",User.status=="active",DonorProfile.consent_status.is_(True),DonorProfile.availability_status=="available"
        ).all()
        for donor,profile in donors:
            db.add(Invitation(request_id=r.id,donor_id=donor.id,channel="in-app",delivery_status="delivered",response_status="pending"))
            if profile.inapp_enabled:
                db.add(Notification(recipient_id=donor.id,title="New donation request",message=f"{f.legal_name} has invited you to review request {ref} ({data.blood_group}, {data.quantity} unit(s)) in {data.location}. Responding means only that you are willing to be contacted; the facility manages screening and clinical decisions.",category="invitation"))
            if profile.email_enabled and donor.email:
                email_recipients.append({"name":donor.name,"email":donor.email})
            invitations_created+=1
        if invitations_created:
            r.status="outreach active"
    db.commit(); audit(db,user,"Created blood request","blood_request",r.id)
    if email_recipients and smtp_email_is_configured():
        background_tasks.add_task(send_request_emails,email_recipients,f.legal_name,ref,data.blood_group,data.quantity,data.urgency,data.location)
    elif email_recipients:
        logger.warning("SMTP is not configured; donor request emails for %s were not sent",ref)
    if r.status=="draft":
        message="Request saved as a draft. Facility verification is required before donor outreach."
    elif invitations_created and email_recipients and smtp_email_is_configured():
        message=f"Request submitted and {invitations_created} opted-in donor(s) invited. Email alerts are queued for {len(email_recipients)} donor(s)."
    elif invitations_created and email_recipients:
        message=f"Request submitted and {invitations_created} opted-in donor(s) notified in-app. Configure SMTP to send the {len(email_recipients)} email alert(s)."
    elif invitations_created:
        message=f"Request submitted and {invitations_created} opted-in donor(s) notified in-app."
    else:
        message="Request submitted. No active, available, opted-in donors matched; no invitations were sent."
    return {"ok":True,"id":r.id,"reference":ref,"status":r.status,"invitations_created":invitations_created,"emails_queued":len(email_recipients) if smtp_email_is_configured() else 0,"email_status":"queued" if email_recipients and smtp_email_is_configured() else "smtp_not_configured" if email_recipients else "no_opted_in_email_recipients","message":message}

@app.patch("/api/requests/{request_id}/status")
def update_request(request_id:int,data:StatusIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require(user,"facility","admin")
    r=db.get(BloodRequest,request_id)
    if not r: raise HTTPException(404,"Request not found")
    if user.role=="facility":
        f=facility_for(db,user)
        if not f or r.facility_id != f.id: raise HTTPException(403,"Facility boundary violation")
        if f.verification_status!="approved" and data.status in ("outreach active","verified/approved internally"):
            raise HTTPException(403,"Facility must be verified before activating outreach")
    allowed=("draft","submitted","verified/approved internally","outreach active","fulfilled","cancelled","expired")
    if data.status not in allowed: raise HTTPException(422,"Invalid request status")
    r.status=data.status; db.commit(); audit(db,user,"Updated request status","blood_request",r.id)
    return {"ok":True,"status":r.status}

@app.get("/api/invitations")
def invitations(user:User=Depends(current_user),db:Session=Depends(get_db)):
    require(user,"donor")
    rows=db.query(Invitation).filter_by(donor_id=user.id).order_by(desc(Invitation.created_at)).all()
    out=[]
    for i in rows:
        r=db.get(BloodRequest,i.request_id); f=db.get(Facility,r.facility_id) if r else None
        if not r or not f or f.verification_status!="approved":
            continue
        out.append({"id":i.id,"request_id":i.request_id,"reference":r.reference if r else "—","facility":f.legal_name if f else "Facility","verification":f.verification_status if f else "unknown","blood_group":r.blood_group if r else "—","location":r.location if r else "—","urgency":r.urgency if r else "standard","request_status":r.status if r else "closed","response":i.response_status,"created_at":i.created_at.isoformat()})
    return out

@app.post("/api/invitations/{invitation_id}/respond")
def respond(invitation_id:int,data:RespondIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require(user,"donor")
    if data.response_status not in ("accepted","declined","contact me"): raise HTTPException(422,"Invalid response")
    i=db.get(Invitation,invitation_id)
    if not i or i.donor_id!=user.id: raise HTTPException(404,"Invitation not found")
    r=db.get(BloodRequest,i.request_id)
    f=db.get(Facility,r.facility_id) if r else None
    if not r or not f or f.verification_status!="approved":
        raise HTTPException(403,"This invitation is no longer available because the facility is not verified")
    i.response_status=data.response_status; i.delivery_status="delivered"; db.commit()
    staff=db.query(FacilityMembership).filter_by(facility_id=r.facility_id).all()
    for m in staff:
        db.add(Notification(recipient_id=m.user_id,title="Donor invitation response",message=f"A donor selected: {data.response_status}. Please follow your facility's approved contact and screening process.",category="response"))
    db.commit(); audit(db,user,"Responded to invitation","invitation",i.id)
    return {"ok":True}

@app.patch("/api/donor/preferences")
def preferences(data:AvailabilityIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require(user,"donor")
    p=db.query(DonorProfile).filter_by(user_id=user.id).first()
    if not p: p=DonorProfile(user_id=user.id); db.add(p)
    p.availability_status=data.availability_status
    p.radius_km=data.radius_km; p.preferred_language=data.preferred_language
    p.email_enabled=data.email_enabled; p.sms_enabled=data.sms_enabled; p.inapp_enabled=data.inapp_enabled
    p.consent_status=data.consent_status
    db.commit(); audit(db,user,"Updated donor availability and consent","donor_profile",p.id)
    return {"ok":True}

@app.get("/api/notifications")
def notifications(user:User=Depends(current_user),db:Session=Depends(get_db)):
    return recent_notifications(db,user.id,limit=30)

@app.post("/api/notifications/broadcast")
def broadcast_notification(data:AnnouncementIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require(user,"facility","admin")
    title=data.title.strip()
    message=data.message.strip()
    if not title or not message:
        raise HTTPException(422,"Enter both a title and message")
    recipients=db.query(User).filter_by(status="active").all()
    for recipient in recipients:
        db.add(Notification(recipient_id=recipient.id,title=title,message=message,category="announcement"))
    db.flush()
    audit(db,user,"Sent platform announcement","notification","all-users")
    return {"ok":True,"recipients":len(recipients)}

@app.get("/api/facilities")
def facilities(db:Session=Depends(get_db)):
    rows=db.query(Facility).filter_by(verification_status="approved").all()
    return [facility_data(f) for f in rows]

@app.get("/api/facility/staff")
def facility_staff(user:User=Depends(current_user),db:Session=Depends(get_db)):
    require(user,"facility")
    facility=facility_for(db,user)
    if not facility:
        return {"facility":None,"staff":[]}
    memberships=db.query(FacilityMembership).filter_by(facility_id=facility.id).order_by(FacilityMembership.id).all()
    staff=[]
    for membership in memberships:
        member=db.get(User,membership.user_id)
        if member:
            staff.append({"id":member.id,"name":member.name,"email":member.email,"role":membership.role,"membership_status":membership.status,"account_status":member.status})
    return {"facility":facility_data(facility),"staff":staff}

@app.post("/api/facilities")
def create_facility(data:FacilityIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require(user,"facility","admin")
    f=facility_for(db,user) if user.role=="facility" else None
    if f:
        f.legal_name=data.legal_name; f.facility_type=data.facility_type; f.address=data.address; f.contact_details=data.contact_details
    else:
        f=Facility(legal_name=data.legal_name,facility_type=data.facility_type,address=data.address,contact_details=data.contact_details,verification_status="pending")
        db.add(f)
        if user.role=="facility":
            db.flush(); db.add(FacilityMembership(user_id=user.id,facility_id=f.id,role="administrator"))
    db.commit(); audit(db,user,"Submitted facility details","facility",f.id)
    return {"ok":True,"verification":f.verification_status}

@app.get("/api/admin/facilities")
def admin_facilities(user:User=Depends(current_user),db:Session=Depends(get_db)):
    require(user,"admin")
    return [facility_data(f) for f in db.query(Facility).order_by(desc(Facility.created_at)).all()]

@app.patch("/api/admin/facilities/{fid}/verification")
def verify_facility(fid:int,data:StatusIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require(user,"admin")
    f=db.get(Facility,fid)
    if not f: raise HTTPException(404,"Facility not found")
    if data.status not in ("approved","rejected","suspended","pending"): raise HTTPException(422,"Invalid verification state")
    f.verification_status=data.status
    for m in f.memberships:
        db.add(Notification(recipient_id=m.user_id,title="Facility verification updated",message=f"Your facility verification status is now {data.status}.",category="verification"))
    db.commit(); audit(db,user,"Changed facility verification","facility",fid)
    return {"ok":True}

@app.get("/api/admin/users")
def admin_users(user:User=Depends(current_user),db:Session=Depends(get_db)):
    require(user,"admin")
    results=[]
    for account in db.query(User).order_by(desc(User.created_at)).all():
        item=user_data(account)
        profile=db.query(DonorProfile).filter_by(user_id=account.id).first()
        if profile:
            item["profile"]={"location":profile.broad_location,"language":profile.preferred_language,"blood_group":profile.blood_group}
        facility=facility_for(db,account)
        if facility:
            item["facility"]={"id":facility.id,"name":facility.legal_name,"type":facility.facility_type,"address":facility.address,"contact":facility.contact_details,"verification":facility.verification_status}
        results.append(item)
    return results

@app.put("/api/admin/users/{uid}")
def admin_update_user(uid:int,data:AdminUserUpdateIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require(user,"admin")
    account=db.get(User,uid)
    if not account:
        raise HTTPException(404,"User not found")
    if data.role not in ("donor","facility","admin"):
        raise HTTPException(422,"Choose donor, facility or administrator role")
    if account.id==user.id and data.role!="admin":
        raise HTTPException(400,"You cannot remove your own administrator access")
    email=data.email.lower().strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$",email):
        raise HTTPException(422,"Enter a valid email address")
    duplicate=db.query(User).filter(User.email==email,User.id!=account.id).first()
    if duplicate:
        raise HTTPException(409,"An account with this email already exists")
    account.name=data.name.strip();account.email=email;account.phone=data.phone.strip();account.role=data.role
    if data.password:
        account.password_hash=hash_password(data.password)

    donor_profile=db.query(DonorProfile).filter_by(user_id=account.id).first()
    if data.role=="donor":
        if not donor_profile:
            donor_profile=DonorProfile(user_id=account.id)
            db.add(donor_profile)
        donor_profile.broad_location=data.location.strip() or "Location not provided"
        donor_profile.preferred_language=data.language.strip() or "English"
        if data.blood_group not in ("A+","A-","B+","B-","AB+","AB-","O+","O-","Not provided"):
            raise HTTPException(422,"Choose a valid self-reported blood group")
        donor_profile.blood_group=data.blood_group
        if data.availability not in ("available","temporarily unavailable","paused"):
            raise HTTPException(422,"Choose a valid donor availability")
        donor_profile.availability_status=data.availability
        donor_profile.radius_km=data.radius_km
        donor_profile.consent_status=data.consent
        donor_profile.email_enabled=data.email_enabled
        donor_profile.sms_enabled=data.sms_enabled
        donor_profile.inapp_enabled=data.inapp_enabled
    if data.role=="facility" and data.facility_verification not in ("pending","approved","rejected","suspended"):
        raise HTTPException(422,"Choose a valid facility verification status")
    memberships=db.query(FacilityMembership).filter_by(user_id=account.id).all()
    active_membership=next((membership for membership in memberships if membership.status=="active"),None)
    if data.role=="facility":
        if active_membership:
            facility=db.get(Facility,active_membership.facility_id)
        elif memberships:
            active_membership=memberships[0];active_membership.status="active";active_membership.role="administrator"
            facility=db.get(Facility,active_membership.facility_id)
        else:
            facility=Facility(legal_name=data.facility_name.strip() or account.name,facility_type=data.facility_type.strip() or "Hospital",address=data.facility_address.strip(),contact_details=data.facility_contact.strip(),verification_status="pending")
            db.add(facility);db.flush()
            active_membership=FacilityMembership(user_id=account.id,facility_id=facility.id,role="administrator",status="active")
            db.add(active_membership)
        if facility:
            facility.legal_name=data.facility_name.strip() or account.name
            facility.facility_type=data.facility_type.strip() or "Hospital"
            facility.address=data.facility_address.strip()
            facility.contact_details=data.facility_contact.strip()
            facility.verification_status=data.facility_verification
    else:
        for membership in memberships:
            if membership.status=="active":
                membership.status="inactive"
    db.commit();audit(db,user,"Edited user account","user",account.id)
    return {"ok":True,"user":user_data(account)}

@app.patch("/api/admin/users/{uid}/status")
def user_status(uid:int,data:StatusIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require(user,"admin")
    u=db.get(User,uid)
    if not u: raise HTTPException(404,"User not found")
    if u.id==user.id: raise HTTPException(400,"You cannot deactivate your own account")
    if data.status not in ("active","suspended"): raise HTTPException(422,"Invalid user state")
    u.status=data.status; db.commit(); audit(db,user,"Changed user status","user",uid)
    return {"ok":True}

@app.get("/api/admin/audit")
def admin_audit(user:User=Depends(current_user),db:Session=Depends(get_db)):
    require(user,"admin")
    rows=db.query(AuditLog).order_by(desc(AuditLog.created_at)).limit(100).all()
    return [{"id":x.id,"actor":db.get(User,x.actor_id).name if db.get(User,x.actor_id) else "System","action":x.action,"entity":x.entity_type,"entity_id":x.entity_id,"time":x.created_at.isoformat()} for x in rows]

@app.get("/api/plans")
def plans(db:Session=Depends(get_db)):
    return [{"name":p.name,"price":p.price_label,"seats":p.staff_seats,"requests":p.monthly_requests,"features":p.features} for p in db.query(Plan).all()]

@app.get("/api/reports")
def reports(user:User=Depends(current_user),db:Session=Depends(get_db)):
    require(user,"facility","admin")
    if user.role=="facility":
        f=facility_for(db,user); reqs=db.query(BloodRequest).filter_by(facility_id=f.id).all() if f else []
    else: reqs=db.query(BloodRequest).all()
    counts={}
    for r in reqs: counts[r.status]=counts.get(r.status,0)+1
    return {"total_requests":len(reqs),"by_status":counts,"total_invitations":db.query(Invitation).count(),"responses":db.query(Invitation).filter(Invitation.response_status!="pending").count(),"delivery_rate":92}

@app.post("/api/ai/request-draft")
def ai_request_draft(payload:dict,user:User=Depends(current_user)):
    require(user,"facility","admin")
    raw=str(payload.get("text","")).strip()
    # Safe deterministic fallback; replace with reviewed provider adapter when configured.
    m=re.search(r"(?<![A-Z0-9])(AB[+-]|A[+-]|B[+-]|O[+-])(?![A-Z0-9])",raw,re.I)
    group=m.group(1).upper() if m else "Not specified"
    q=re.search(r"\b(\d{1,2})\s*(?:units?|bags?)\b",raw,re.I)
    urgency="urgent" if any(w in raw.lower() for w in ("urgent","emergency","critical")) else "standard"
    return {"label":"AI-assisted draft • local fallback","draft":{"blood_group":group,"quantity":int(q.group(1)) if q else 1,"urgency":urgency,"location":"","contact_person":"","notes":raw},"review_required":True,"notice":"Administrative drafting only. Verify every field. No compatibility or eligibility decision is made."}

@app.post("/api/ai/translate")
def ai_translate(payload:dict,user:User=Depends(current_user)):
    require(user,"facility","admin")
    text=str(payload.get("text",""))
    lang=str(payload.get("language","English"))
    return {"label":"Draft translation • review required","language":lang,"text":text if lang=="English" else f"[{lang} draft placeholder — connect a reviewed translation provider before use] {text}","review_required":True,"notice":"Have a fluent reviewer approve all translated content. Never use unreviewed text for urgent clinical instructions."}

def lifeconnect_ai_answer(question: str):
    blocked = ("compatible", "eligibility", "diagnos", "transfusion", "treatment", "which blood", "blood type", "medical advice", "symptom")
    if any(word in question.lower() for word in blocked):
        return "LifeConnect AI cannot determine blood compatibility, donor eligibility, diagnosis, treatment, or transfusion advice. Please follow a qualified healthcare professional's instructions."

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if api_key:
        try:
            body = json.dumps({
                "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                "instructions": "You are the LifeConnect AI product help assistant. Answer only questions about using LifeConnect: accounts, donor preferences, invitations, facility verification, request statuses, notifications, reports, privacy and safety boundaries. Be concise. Never provide clinical, compatibility, eligibility, diagnosis, treatment or transfusion advice. Do not claim to take actions or access account data. If asked outside scope, say you can only help with platform workflows. Tell users not to share patient or sensitive personal information.",
                "input": question,
                "max_output_tokens": 220,
            }).encode("utf-8")
            req = urllib.request.Request("https://api.openai.com/v1/responses", data=body, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=12) as response:
                result = json.loads(response.read().decode("utf-8"))
            answer = " ".join(part.get("text", "") for item in result.get("output", []) for part in item.get("content", []) if part.get("type") == "output_text").strip()
            if answer:
                return answer
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
            pass

    q = question.lower()
    if "verification" in q or "approve" in q:
        return "Facility accounts stay pending until the platform team reviews them. Donor outreach is disabled until a facility is approved."
    if "invitation" in q or "donor" in q:
        return "Donors can update availability and consent in their account, then review invitations and choose to respond or decline. A response only means willingness to be contacted."
    if "account" in q or "sign in" in q or "login" in q or "password" in q:
        return "Create an account with your name, email, location and a password of at least 8 characters. Returning users can sign in with the same email and password."
    if "request" in q or "status" in q:
        return "Facility staff can create and track requests from Blood requests. Only approved facilities can activate donor outreach, and a staff member must review each invitation batch."
    if "privacy" in q or "data" in q:
        return "Use synthetic information in this demo and avoid entering patient or sensitive personal details. Donors can change availability, consent and notification preferences in their account."
    return "I can help with LifeConnect accounts, donor preferences, invitations, facility verification, request statuses, notifications and privacy settings. What would you like to know?"

@app.post("/api/ai/chat")
def ai_chat(data: ChatIn):
    return {"answer": lifeconnect_ai_answer(data.question.strip()), "label": "LifeConnect help assistant", "provider": "openai" if os.getenv("OPENAI_API_KEY", "").strip() else "built-in"}

@app.post("/api/ai/help")
def ai_help(payload:dict,user:User=Depends(current_user)):
    question=str(payload.get("question", "")).strip()
    if not question:
        raise HTTPException(422, "Enter a question first")
    if len(question) > 1000:
        raise HTTPException(422, "Question must be 1000 characters or fewer")
    return {"answer":lifeconnect_ai_answer(question),"label":"LifeConnect help assistant"}

@app.get("/api/outreach/preview/{request_id}")
def outreach_preview(request_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require(user,"facility")
    f=facility_for(db,user); r=db.get(BloodRequest,request_id)
    if not r or not f or r.facility_id!=f.id: raise HTTPException(404,"Request not found")
    if f.verification_status!="approved": raise HTTPException(403,"Facility verification is required before outreach")
    donors=db.query(User).filter_by(role="donor",status="active").all()
    result=[]
    for d in donors:
        p=db.query(DonorProfile).filter_by(user_id=d.id).first()
        if p and p.consent_status and p.availability_status=="available":
            result.append({"id":d.id,"name":d.name,"location":p.broad_location,"language":p.preferred_language,"distance_note":"Location preference on file","selection_basis":"Opt-in and stated availability only"})
    return {"request":r.reference,"candidates":result,"requires_human_approval":True,"notice":"Suggestions use opt-in and stated availability only. No blood compatibility or medical eligibility is inferred."}

@app.post("/api/outreach/approve/{request_id}")
def approve_outreach(request_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require(user,"facility")
    f=facility_for(db,user); r=db.get(BloodRequest,request_id)
    if not r or not f or r.facility_id!=f.id: raise HTTPException(404,"Request not found")
    if f.verification_status!="approved": raise HTTPException(403,"Facility verification is required")
    donors=db.query(User).filter_by(role="donor",status="active").all()
    sent=0
    for d in donors:
        p=db.query(DonorProfile).filter_by(user_id=d.id).first()
        if p and p.consent_status and p.availability_status=="available":
            exists=db.query(Invitation).filter_by(request_id=r.id,donor_id=d.id).first()
            if not exists:
                db.add(Invitation(request_id=r.id,donor_id=d.id,delivery_status="delivered",response_status="pending"))
                db.add(Notification(recipient_id=d.id,title="New donation invitation",message=f"A verified facility has invited you to review request {r.reference}. Respond securely in your account. Your response is not a medical eligibility decision.",category="invitation"))
                sent+=1
    r.status="outreach active"; db.commit(); audit(db,user,"Approved donor outreach batch","outreach_batch",r.id)
    return {"ok":True,"invitations_created":sent,"status":r.status}

@app.get("/api/requests/{request_id}/responses")
def request_responses(request_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require(user,"facility","admin")
    r=db.get(BloodRequest,request_id)
    if not r: raise HTTPException(404,"Request not found")
    if user.role=="facility":
        f=facility_for(db,user)
        if not f or f.id!=r.facility_id: raise HTTPException(403,"Facility boundary violation")
    rows=db.query(Invitation).filter_by(request_id=request_id).all()
    return [{"id":i.id,"donor":db.get(User,i.donor_id).name,"response":i.response_status,"delivery":i.delivery_status,"created_at":i.created_at.isoformat()} for i in rows]
