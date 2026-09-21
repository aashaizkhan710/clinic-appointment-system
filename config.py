import os
from pathlib import Path

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'change-this-development-secret')
    # Absolute path avoids Flask's instance-folder relative SQLite behavior.
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', f"sqlite:///{(Path(__file__).resolve().parent / 'database' / 'clinic.db').as_posix()}").replace('postgres://', 'postgresql://', 1)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    CLINIC_TIMEZONE = os.getenv('CLINIC_TIMEZONE', 'Asia/Karachi')
    N8N_APPOINTMENT_WEBHOOK = os.getenv('N8N_APPOINTMENT_WEBHOOK', '')
    N8N_DOCTOR_INVITE_WEBHOOK = os.getenv('N8N_DOCTOR_INVITE_WEBHOOK', '')
    N8N_AUTOMATION_SECRET = os.getenv('N8N_AUTOMATION_SECRET', '')
    WTF_CSRF_TIME_LIMIT = 3600
