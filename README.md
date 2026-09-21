# Nowshera Family Clinic

A Flask, SQLite, Bootstrap clinic appointment system with patient, doctor, and admin roles.

## Quick start (Windows)

1. Open PowerShell in this folder.
2. Run `python -m venv .venv`
3. Run `.venv\Scripts\activate`
4. Run `pip install -r requirements.txt`
5. Copy `.env.example` to `.env` and replace `SECRET_KEY`.
6. Run `run.bat` (or `python app.py`).
7. Visit `http://127.0.0.1:5000`.

SQLite data is stored in `database/clinic.db` and survives restarts. The first start creates schema and development demo data.

## Publish online with Render

For a public URL that works on any computer, create a Render Web Service from this GitHub repository. Use build command `pip install -r requirements.txt` and start command `gunicorn app:app`. Render's Flask guide uses these commands. Add `SECRET_KEY`, `CLINIC_TIMEZONE=Asia/Karachi`, your n8n webhook variables, and `N8N_AUTOMATION_SECRET` as Render environment variables. For permanent hosted data, create Render Postgres in the same region and set the web service `DATABASE_URL` to its internal connection URL. Never put these values in GitHub. See [Render's Flask deployment guide](https://render.com/docs/deploy-flask) and [Render Postgres setup](https://render.com/docs/postgresql-creating-connecting).

## Demo accounts

| Role | Email | Password |
|---|---|---|
| Admin | admin@clinic.local | Admin123! |
| Doctor | doctor@clinic.local | Doctor123! |
| Patient | patient@clinic.local | Patient123! |

These are development-only credentials: change or remove them before any deployment.

## Features

- Password-hashed accounts, Flask sessions, CSRF-protected browser forms, and server-enforced roles.
- 30-minute availability slots; SQLite uniqueness constraints prevent doctor or patient double booking.
- Pending slots are held; cancellation and rescheduling enforce the two-hour rule.
- Doctors manage schedules, editable availability, leave, confirmation/rejection, completion/no-show and their own patients only.
- Admins manage doctors/patients/appointments. Visit notes are intentionally never rendered in admin pages.
- Leave automatically cancels active appointments. Inactive doctors retain existing appointments but accept no new ones.

## n8n

Set `N8N_APPOINTMENT_WEBHOOK` for appointment events and `N8N_DOCTOR_INVITE_WEBHOOK` for invitations. Each receives JSON with `event`, patient/doctor names and email, date and time (when applicable). Configure n8n to send email based on `event`.

Set a long `N8N_AUTOMATION_SECRET`, then make authenticated POST calls with header `X-Automation-Secret`:

- `/api/automation/reminders` daily: sends one reminder for confirmed appointments tomorrow and records `reminder_sent`.
- `/api/automation/expire-pending` periodically: cancels pending appointments once their start time arrives.

Clinic time uses `CLINIC_TIMEZONE` (default `Asia/Karachi`) consistently for slots, reminders, and the two-hour rule.

Import `n8n-clinic-email-workflow.json` into n8n, connect the Gmail node to your own account, publish the workflow, and add its Production Webhook URL to both webhook variables in `.env`.

## Tests

Run `python -m unittest discover -s tests -v`. The automated suite has 10 passing scenarios: signup/roles, booking/confirmation, duplicate booking, past/outside/inactive validation, slots/overlap validation, leave cancellation, cancellation/rescheduling, note privacy, completion timing, and reminder/pending-expiry automation.

## Structure

`app.py` contains the intentionally compact Flask application, models, role checks, routes, and business rules. `services/email_service.py` isolates n8n delivery. Templates and styling are under `templates/` and `static/`.
