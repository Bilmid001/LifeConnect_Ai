# LifeConnect AI — Blood Donation Coordination Platform

A responsive, interactive MVP based on the supplied **LifeConnect AI Product & Technical Blueprint (v2.0, November 2026)**.

## What is included

- Public website: Home, About & Safety, verified-facility directory, hospitals, Help, Privacy and Terms; responsive local SVG artwork, an illustrative dashboard preview and synthetic sample metrics.
- Three main application roles: **Donor**, **Facility Staff**, and **Platform Administrator**.
- Demo sign-in and role-based dashboards with role-aware navigation.
- Donor registration/profile, availability, consent and channel preferences, invitation inbox, accept/decline/contact-me responses.
- Facility onboarding and verification queue; verified facility request submission creates invitations for active donors who opted in.
- In-app notification centre and delivery log; request alerts are emailed to opted-in donors when SMTP is configured.
- New in-app updates appear as pop-up notifications while a user is signed in.
- Plans/subscription screen, reports and operational analytics.
- Public landing-page help chat and facility/admin AI assistant for administrative request drafting and product help. Product help uses a built-in fallback and can use OpenAI when configured; outputs require staff review.
- Audit log, user management, facility management, security settings and configurable plans for administrators.
- SQLite database with synthetic seed data; FastAPI API; responsive HTML/CSS/JS interface.
- Interactive dialogs, toasts, search, filters, charts, tables, form validation, mobile navigation and confirmation prompts.
- Facility staff roster is view-only in this MVP. Staff invitations and role changes are not enabled.

## Run locally

Python 3.10+ is recommended.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8012
```

Open http://127.0.0.1:8012. Keep the server running while using the site; sign-in and account creation send requests to this local server.

The SQLite database and synthetic demo records are created automatically on first run.

## Demo accounts

All demo accounts use password `Demo123!`.

| Role | Email |
|---|---|
| Platform administrator | admin@lifeconnect.demo |
| Facility staff | staff@lifeconnect.demo |
| Donor | donor@lifeconnect.demo |

The seeded facility is explicitly labelled **DEMO / NOT VERIFIED FOR REAL-WORLD USE**. Admin can inspect and approve the synthetic facility in the verification workflow.

## Important configuration

- Set a strong `SECRET_KEY` in `.env` before deployment.
- The default database is SQLite for a quick demo. For production, use PostgreSQL and configure `DATABASE_URL`.
- Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, and `SMTP_FROM` in `.env` to send request alerts by email. Set `PUBLIC_APP_URL` to your site's public address so each email links back to the site. Without SMTP settings, opted-in donors still receive in-app invitations; the hospital sees that email is not configured.
- Unverified facilities can save requests as drafts but cannot invite donors. Verified facility request submission creates invitations only for active donors who consented and are available.
- SMS and payment live-mode integrations are intentionally not enabled in this MVP.
- The public help chat works with built-in product guidance. To enable generative product-help responses, set `OPENAI_API_KEY` in `.env`; `OPENAI_MODEL` can select a supported model. If the provider is unavailable, the assistant falls back to built-in guidance. Request drafting and translations remain local/demo workflows. Never use AI output to determine blood-group compatibility, donor eligibility, diagnosis, treatment, or transfusion decisions.
- Do not upload real patient or donor information into this demo. Use synthetic records only.

## Safety and scope

LifeConnect AI coordinates communication and workflow. It is **not** a blood marketplace and does not sell blood. It does not replace a hospital blood bank, transfusion service, clinician, laboratory testing, screening, grouping, crossmatching, storage, release, transfusion, or emergency services.

A donor accepting an invitation only indicates willingness to be contacted; it is not clinical eligibility. Facility staff must review and approve outreach. Qualified healthcare professionals and authorised facilities retain all clinical and operational responsibility.

Before a real-world pilot, obtain Nigerian legal, data-protection, clinical and regulatory review; confirm requirements with relevant authorities and partner facilities; approve consent wording, staff responsibilities, escalation paths, data retention, security and incident response. Do not claim partnerships, approvals or integrations that have not been formally confirmed.

## Project layout

```text
lifeconnect-ai/
├── app/
│   ├── main.py              # FastAPI API and server-rendered app entry
│   ├── database.py          # SQLAlchemy + SQLite setup
│   ├── models.py            # Core entities
│   ├── security.py          # Password hashing and JWT
│   ├── seed.py              # Synthetic demo data
│   ├── templates/index.html # SPA shell
│   └── static/
│       ├── styles.css
│       ├── polish.css
│       ├── lifeconnect-hero.svg
│       ├── favicon.svg
│       └── app.js
├── .env.example
├── requirements.txt
└── README.md
```
