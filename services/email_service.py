"""Best-effort n8n webhook client. Failed webhooks never roll back clinic data."""
import requests
from flask import current_app

def notify(event, appointment=None, **extra):
    url = current_app.config['N8N_DOCTOR_INVITE_WEBHOOK'] if event == 'doctor_invitation' else current_app.config['N8N_APPOINTMENT_WEBHOOK']
    payload = {'event': event, **extra}
    if appointment:
        payload.update(patient_name=appointment.patient.name, patient_email=appointment.patient.email,
          doctor_name=appointment.doctor.user.name, appointment_date=appointment.appointment_date.isoformat(),
          appointment_time=appointment.start_time.strftime('%H:%M'))
    if not url: return False
    try:
        requests.post(url, json=payload, timeout=5).raise_for_status()
        return True
    except requests.RequestException:
        current_app.logger.warning('n8n notification failed for %s', event)
        return False
