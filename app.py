import os, secrets
from datetime import date, datetime, time, timedelta
from functools import wraps
from zoneinfo import ZoneInfo
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import Index, UniqueConstraint, and_, or_, text
from werkzeug.security import check_password_hash, generate_password_hash
from dotenv import load_dotenv
from config import Config

load_dotenv()
db=SQLAlchemy(); login_manager=LoginManager(); csrf=CSRFProtect()
ACTIVE={'Pending','Confirmed'}; TRANSITIONS={'Pending':{'Confirmed','Rejected','Cancelled'},'Confirmed':{'Cancelled','Completed','No-show'}}
def now(): return datetime.now(ZoneInfo(app.config['CLINIC_TIMEZONE']))
def start_dt(a): return datetime.combine(a.appointment_date,a.start_time,tzinfo=ZoneInfo(app.config['CLINIC_TIMEZONE']))

class User(UserMixin,db.Model):
 id=db.Column(db.Integer,primary_key=True); name=db.Column(db.String(120),nullable=False); email=db.Column(db.String(120),unique=True,index=True,nullable=False); phone=db.Column(db.String(30)); password_hash=db.Column(db.String(255),nullable=False); role=db.Column(db.String(15),nullable=False); is_active=db.Column(db.Boolean,default=True); created_at=db.Column(db.DateTime,default=datetime.utcnow)
 appointments=db.relationship('Appointment',foreign_keys='Appointment.patient_id',back_populates='patient')
 def set_password(self,p): self.password_hash=generate_password_hash(p)
 def check_password(self,p): return check_password_hash(self.password_hash,p)
class DoctorProfile(db.Model):
 id=db.Column(db.Integer,primary_key=True); user_id=db.Column(db.Integer,db.ForeignKey('user.id'),unique=True,nullable=False); specialty=db.Column(db.String(120),nullable=False); active=db.Column(db.Boolean,default=True); user=db.relationship('User',backref=db.backref('doctor_profile',uselist=False)); availability=db.relationship('Availability',cascade='all,delete-orphan')
class Availability(db.Model):
 id=db.Column(db.Integer,primary_key=True); doctor_id=db.Column(db.Integer,db.ForeignKey('doctor_profile.id'),nullable=False,index=True); weekday=db.Column(db.Integer,nullable=False); start_time=db.Column(db.Time,nullable=False); end_time=db.Column(db.Time,nullable=False)
class DoctorLeave(db.Model):
 id=db.Column(db.Integer,primary_key=True); doctor_id=db.Column(db.Integer,db.ForeignKey('doctor_profile.id'),nullable=False,index=True); leave_date=db.Column(db.Date,nullable=False); created_at=db.Column(db.DateTime,default=datetime.utcnow); __table_args__=(UniqueConstraint('doctor_id','leave_date'),)
class Appointment(db.Model):
 id=db.Column(db.Integer,primary_key=True); patient_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False,index=True); doctor_id=db.Column(db.Integer,db.ForeignKey('doctor_profile.id'),nullable=False,index=True); appointment_date=db.Column(db.Date,nullable=False,index=True); start_time=db.Column(db.Time,nullable=False); end_time=db.Column(db.Time,nullable=False); status=db.Column(db.String(15),default='Pending',nullable=False,index=True); visit_note=db.Column(db.Text); reminder_sent=db.Column(db.Boolean,default=False); created_at=db.Column(db.DateTime,default=datetime.utcnow); updated_at=db.Column(db.DateTime,default=datetime.utcnow,onupdate=datetime.utcnow)
 patient=db.relationship('User',foreign_keys=[patient_id],back_populates='appointments'); doctor=db.relationship('DoctorProfile'); __table_args__=(Index('unique_active_doctor_slot','doctor_id','appointment_date','start_time',unique=True,sqlite_where=text("status IN ('Pending','Confirmed')")),Index('unique_active_patient_slot','patient_id','appointment_date','start_time',unique=True,sqlite_where=text("status IN ('Pending','Confirmed')")))
class SetupToken(db.Model):
 id=db.Column(db.Integer,primary_key=True); doctor_id=db.Column(db.Integer,db.ForeignKey('doctor_profile.id'),nullable=False); token_hash=db.Column(db.String(255),nullable=False); expires_at=db.Column(db.DateTime,nullable=False); used=db.Column(db.Boolean,default=False); doctor=db.relationship('DoctorProfile')

def role_required(*roles):
 def deco(f):
  @wraps(f)
  def wrapped(*a,**k):
   if not current_user.is_authenticated: return login_manager.unauthorized()
   if current_user.role not in roles: abort(403)
   return f(*a,**k)
  return wrapped
 return deco
@login_manager.user_loader
def load_user(uid): return db.session.get(User,int(uid))

def slots(profile, day):
 if not profile.active or day < date.today() or DoctorLeave.query.filter_by(doctor_id=profile.id,leave_date=day).first(): return []
 taken={a.start_time for a in Appointment.query.filter_by(doctor_id=profile.id,appointment_date=day).filter(Appointment.status.in_(ACTIVE))}
 result=[]
 for av in profile.availability:
  if av.weekday==day.weekday():
   cursor=datetime.combine(day,av.start_time); end=datetime.combine(day,av.end_time)
   while cursor+timedelta(minutes=30)<=end:
    t=cursor.time()
    if cursor.replace(tzinfo=ZoneInfo(app.config['CLINIC_TIMEZONE']))>now() and t not in taken: result.append(t)
    cursor+=timedelta(minutes=30)
 return sorted(set(result))
def validate_slot(patient,doctor,day,slot,exclude=None):
 if not doctor.active: return 'This doctor is not accepting bookings.'
 if day<date.today() or datetime.combine(day,slot,tzinfo=ZoneInfo(app.config['CLINIC_TIMEZONE']))<=now(): return 'Appointments must be in the future.'
 if slot not in slots(doctor,day): return 'This slot is unavailable or outside working hours.'
 q=Appointment.query.filter_by(patient_id=patient.id,appointment_date=day,start_time=slot).filter(Appointment.status.in_(ACTIVE))
 if exclude: q=q.filter(Appointment.id!=exclude)
 if q.first(): return 'You already have an active appointment at that time.'
 return None
def notify(event,a=None,**x):
 from services.email_service import notify as send; send(event,a,**x)
def transition(a,status,note=None):
 if status not in TRANSITIONS.get(a.status,set()): raise ValueError('Invalid appointment status transition.')
 a.status=status
 if note is not None: a.visit_note=note.strip()[:2000]

app=Flask(__name__); app.config.from_object(Config); db.init_app(app); login_manager.init_app(app); login_manager.login_view='login'; csrf.init_app(app)
@app.context_processor
def inject(): return {'today':date.today()}
@app.route('/')
def index(): return render_template('index.html', doctors=DoctorProfile.query.filter_by(active=True).limit(3).all())
@app.route('/signup',methods=['GET','POST'])
def signup():
 if request.method=='POST':
  name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower(); password=request.form.get('password',''); phone=request.form.get('phone','').strip()
  if not name or '@' not in email or len(password)<8 or password!=request.form.get('confirm'): flash('Enter a valid name/email and matching password of at least 8 characters.','danger')
  elif User.query.filter_by(email=email).first(): flash('That email is already registered.','danger')
  else:
   u=User(name=name,email=email,phone=phone,role='patient');u.set_password(password);db.session.add(u);db.session.commit();login_user(u);return redirect(url_for('dashboard'))
 return render_template('auth/signup.html')
@app.route('/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  u=User.query.filter_by(email=request.form.get('email','').lower()).first()
  if u and u.is_active and u.check_password(request.form.get('password','')): login_user(u);return redirect(url_for('dashboard'))
  flash('Invalid email or password.','danger')
 return render_template('auth/login.html')
@app.route('/logout')
@login_required
def logout(): logout_user();flash('You have been signed out.','success');return redirect(url_for('index'))
@app.route('/dashboard')
@login_required
def dashboard():
 if current_user.role=='patient': return redirect(url_for('patient_dashboard'))
 if current_user.role=='doctor': return redirect(url_for('doctor_dashboard'))
 return redirect(url_for('admin_dashboard'))
@app.route('/doctors')
def doctors(): return render_template('patient/doctors.html',doctors=DoctorProfile.query.filter_by(active=True).all())
@app.route('/patient')
@role_required('patient')
def patient_dashboard(): return render_template('patient/dashboard.html',appointments=Appointment.query.filter_by(patient_id=current_user.id).order_by(Appointment.appointment_date,Appointment.start_time).limit(5).all(),doctors=DoctorProfile.query.filter_by(active=True).all())
@app.route('/patient/appointments')
@role_required('patient')
def patient_appointments():
 q=Appointment.query.filter_by(patient_id=current_user.id); status=request.args.get('status');
 if status: q=q.filter_by(status=status)
 return render_template('patient/appointments.html',appointments=q.order_by(Appointment.appointment_date.desc(),Appointment.start_time.desc()).all())
@app.route('/patient/appointment/<int:aid>/reschedule',methods=['GET'])
@role_required('patient')
def reschedule_page(aid):
 a=Appointment.query.filter_by(id=aid,patient_id=current_user.id).first_or_404()
 if a.status not in ACTIVE or start_dt(a)-now()<timedelta(hours=2): abort(403)
 try: chosen=date.fromisoformat(request.args.get('day',a.appointment_date.isoformat()))
 except ValueError: chosen=a.appointment_date
 return render_template('patient/reschedule.html',appointment=a,day=chosen,slots=slots(a.doctor,chosen))
@app.route('/patient/book/<int:doctor_id>',methods=['GET','POST'])
@role_required('patient')
def book(doctor_id):
 d=db.session.get(DoctorProfile,doctor_id) or abort(404); selected=request.values.get('day',''); day=date.fromisoformat(selected) if selected else date.today()+timedelta(days=1)
 if request.method=='POST':
  try: slot=time.fromisoformat(request.form['slot']); err=validate_slot(current_user,d,day,slot)
  except (KeyError,ValueError): err='Choose a valid date and slot.'
  if err: flash(err,'danger')
  else:
   a=Appointment(patient=current_user,doctor=d,appointment_date=day,start_time=slot,end_time=(datetime.combine(day,slot)+timedelta(minutes=30)).time())
   try: db.session.add(a);db.session.commit();flash('Appointment requested. The doctor will review it.','success');return redirect(url_for('patient_appointments'))
   except Exception: db.session.rollback();flash('That slot was just booked. Please choose another.','danger')
 return render_template('patient/book_appointment.html',doctor=d,day=day,slots=slots(d,day))
@app.route('/api/doctors/<int:doctor_id>/slots')
@role_required('patient')
def api_slots(doctor_id):
 try: day=date.fromisoformat(request.args['date'])
 except (KeyError,ValueError): return jsonify(error='Invalid date'),400
 d=db.session.get(DoctorProfile,doctor_id)
 return jsonify(slots=[x.strftime('%H:%M') for x in slots(d,day)]) if d else (jsonify(error='Doctor not found'),404)
@app.route('/patient/appointment/<int:aid>/cancel',methods=['POST'])
@role_required('patient')
def patient_cancel(aid):
 a=Appointment.query.filter_by(id=aid,patient_id=current_user.id).first_or_404()
 if a.status not in ACTIVE or start_dt(a)-now()<timedelta(hours=2): flash('Cancellation requires an active appointment at least 2 hours away.','danger')
 else: transition(a,'Cancelled');db.session.commit();notify('appointment_cancelled',a);flash('Appointment cancelled.','success')
 return redirect(url_for('patient_appointments'))
@app.route('/patient/appointment/<int:aid>/reschedule',methods=['POST'])
@role_required('patient')
def reschedule(aid):
 a=Appointment.query.filter_by(id=aid,patient_id=current_user.id).first_or_404()
 try: day=date.fromisoformat(request.form['day']); slot=time.fromisoformat(request.form['slot']); err=validate_slot(current_user,a.doctor,day,slot,a.id)
 except (KeyError,ValueError): err='Choose a valid new slot.'
 if a.status not in ACTIVE or start_dt(a)-now()<timedelta(hours=2): err='Rescheduling requires an active appointment at least 2 hours away.'
 if err: flash(err,'danger')
 else:
  a.appointment_date,a.start_time,a.end_time,a.status=day,slot,(datetime.combine(day,slot)+timedelta(minutes=30)).time(),'Pending'
  try: db.session.commit();flash('Rescheduled. It now awaits doctor confirmation.','success')
  except Exception: db.session.rollback();flash('Slot conflict; no changes were made.','danger')
 return redirect(url_for('patient_appointments'))
@app.route('/doctor')
@role_required('doctor')
def doctor_dashboard():
 d=current_user.doctor_profile; ap=Appointment.query.filter_by(doctor_id=d.id); return render_template('doctor/dashboard.html',today_ap=ap.filter_by(appointment_date=date.today()).all(),pending=ap.filter_by(status='Pending').count(),upcoming=ap.filter(Appointment.appointment_date>=date.today(),Appointment.status.in_(ACTIVE)).count())
@app.route('/doctor/appointments')
@role_required('doctor')
def doctor_appointments():
 q=Appointment.query.filter_by(doctor_id=current_user.doctor_profile.id); status=request.args.get('status'); return render_template('doctor/appointments.html',appointments=(q.filter_by(status=status) if status else q).order_by(Appointment.appointment_date,Appointment.start_time).all())
@app.route('/doctor/appointment/<int:aid>/status',methods=['POST'])
@role_required('doctor')
def doctor_status(aid):
 a=Appointment.query.filter_by(id=aid,doctor_id=current_user.doctor_profile.id).first_or_404(); target=request.form.get('status'); note=request.form.get('note','')
 try:
  if target in ('Completed','No-show') and start_dt(a)>now(): raise ValueError('Cannot complete or mark no-show before the appointment start.')
  transition(a,target,note if target in ('Completed','No-show') else None); db.session.commit(); notify('appointment_'+target.lower().replace('-','_'),a); flash('Appointment updated.','success')
 except ValueError as e: flash(str(e),'danger')
 return redirect(url_for('doctor_appointments'))
@app.route('/doctor/availability',methods=['GET','POST'])
@role_required('doctor')
def availability():
 d=current_user.doctor_profile
 if request.method=='POST':
  try:
   wd=int(request.form['weekday']); st=time.fromisoformat(request.form['start']); en=time.fromisoformat(request.form['end'])
   if not 0<=wd<=6 or en<=st: raise ValueError('End time must be later than start time.')
   overlap=Availability.query.filter_by(doctor_id=d.id,weekday=wd).filter(Availability.start_time<en,Availability.end_time>st).first()
   if overlap: raise ValueError('Working hours overlap an existing period.')
   db.session.add(Availability(doctor_id=d.id,weekday=wd,start_time=st,end_time=en));db.session.commit();flash('Availability added.','success')
  except (KeyError,ValueError) as e: flash(str(e),'danger')
 return render_template('doctor/availability.html',availability=d.availability)
@app.route('/doctor/availability/<int:avid>/edit',methods=['POST'])
@role_required('doctor')
def edit_availability(avid):
 a=Availability.query.filter_by(id=avid,doctor_id=current_user.doctor_profile.id).first_or_404()
 try:
  wd=int(request.form['weekday']); st=time.fromisoformat(request.form['start']); en=time.fromisoformat(request.form['end'])
  if not 0<=wd<=6 or en<=st: raise ValueError('End time must be later than start time.')
  overlap=Availability.query.filter_by(doctor_id=a.doctor_id,weekday=wd).filter(Availability.id!=a.id,Availability.start_time<en,Availability.end_time>st).first()
  if overlap: raise ValueError('Working hours overlap an existing period.')
  a.weekday,a.start_time,a.end_time=wd,st,en;db.session.commit();flash('Availability updated.','success')
 except (KeyError,ValueError) as e: flash(str(e),'danger')
 return redirect(url_for('availability'))
@app.route('/doctor/availability/<int:avid>/delete',methods=['POST'])
@role_required('doctor')
def delete_availability(avid):
 a=Availability.query.filter_by(id=avid,doctor_id=current_user.doctor_profile.id).first_or_404();db.session.delete(a);db.session.commit();flash('Availability removed.','success');return redirect(url_for('availability'))
@app.route('/doctor/leave',methods=['GET','POST'])
@role_required('doctor')
def leave():
 d=current_user.doctor_profile
 if request.method=='POST':
  try:
   day=date.fromisoformat(request.form['leave_date'])
   if day<date.today(): raise ValueError('Leave cannot be in the past.')
   if DoctorLeave.query.filter_by(doctor_id=d.id,leave_date=day).first(): raise ValueError('Leave is already recorded.')
   db.session.add(DoctorLeave(doctor_id=d.id,leave_date=day)); affected=Appointment.query.filter_by(doctor_id=d.id,appointment_date=day).filter(Appointment.status.in_(ACTIVE)).all()
   for a in affected: transition(a,'Cancelled')
   db.session.commit()
   for a in affected: notify('doctor_leave',a)
   flash(f'Leave saved; {len(affected)} active appointment(s) cancelled.','success')
  except (KeyError,ValueError) as e: flash(str(e),'danger')
 return render_template('doctor/leave.html',leaves=DoctorLeave.query.filter_by(doctor_id=d.id).order_by(DoctorLeave.leave_date).all())
@app.route('/doctor/patient/<int:pid>')
@role_required('doctor')
def patient_history(pid):
 d=current_user.doctor_profile; history=Appointment.query.filter_by(patient_id=pid,doctor_id=d.id).order_by(Appointment.appointment_date.desc()).all()
 if not history: abort(403)
 return render_template('doctor/patient_history.html',patient=db.session.get(User,pid),appointments=history)
@app.route('/admin')
@role_required('admin')
def admin_dashboard():
 ap=Appointment.query; doctors=DoctorProfile.query.all(); stats={d.id:{s:Appointment.query.filter_by(doctor_id=d.id,status=s).count() for s in ['Pending','Confirmed','Completed','No-show','Cancelled','Rejected']} for d in doctors}; return render_template('admin/dashboard.html',active_doctors=DoctorProfile.query.filter_by(active=True).count(),patients=User.query.filter_by(role='patient').count(),today_count=ap.filter_by(appointment_date=date.today()).count(),upcoming=ap.filter(Appointment.appointment_date>=date.today(),Appointment.status.in_(ACTIVE)).count(),doctors=doctors,stats=stats)
@app.route('/admin/doctors',methods=['GET','POST'])
@role_required('admin')
def admin_doctors():
 if request.method=='POST':
  name=request.form.get('name','').strip();email=request.form.get('email','').lower().strip();specialty=request.form.get('specialty','').strip()
  if not name or '@' not in email or not specialty or User.query.filter_by(email=email).first(): flash('Enter a unique valid email, name, and specialty.','danger')
  else:
   u=User(name=name,email=email,role='doctor',password_hash=generate_password_hash(secrets.token_urlsafe(24)));d=DoctorProfile(user=u,specialty=specialty);token=secrets.token_urlsafe(32);db.session.add_all([u,d]);db.session.flush();db.session.add(SetupToken(doctor_id=d.id,token_hash=generate_password_hash(token),expires_at=datetime.utcnow()+timedelta(days=2)));db.session.commit();notify('doctor_invitation',None,doctor_name=name,doctor_email=email,setup_link=url_for('setup_password',token=token,_external=True));flash('Doctor added. Invite webhook triggered.','success')
 return render_template('admin/doctors.html',doctors=DoctorProfile.query.all())
@app.route('/admin/doctors/<int:did>/toggle',methods=['POST'])
@role_required('admin')
def doctor_toggle(did):
 d=db.session.get(DoctorProfile,did) or abort(404);d.active=not d.active;db.session.commit();flash('Doctor status updated. Existing appointments are retained; inactive doctors cannot receive new bookings.','success');return redirect(url_for('admin_doctors'))
@app.route('/admin/doctors/<int:did>/edit',methods=['POST'])
@role_required('admin')
def doctor_edit(did):
 d=db.session.get(DoctorProfile,did) or abort(404); name=request.form.get('name','').strip(); specialty=request.form.get('specialty','').strip()
 if not name or not specialty: flash('Name and specialty are required.','danger')
 else: d.user.name=name;d.specialty=specialty;db.session.commit();flash('Doctor details updated.','success')
 return redirect(url_for('admin_doctors'))
@app.route('/setup-password/<token>',methods=['GET','POST'])
def setup_password(token):
 rec=next((x for x in SetupToken.query.filter_by(used=False).all() if x.expires_at>datetime.utcnow() and check_password_hash(x.token_hash,token)),None)
 if not rec: abort(404)
 if request.method=='POST':
  p=request.form.get('password','');
  if len(p)<8 or p!=request.form.get('confirm'): flash('Use matching passwords of at least 8 characters.','danger')
  else: rec.doctor.user.set_password(p);rec.used=True;db.session.commit();flash('Password configured. You can now sign in.','success');return redirect(url_for('login'))
 return render_template('auth/setup_password.html')
@app.route('/admin/patients')
@role_required('admin')
def admin_patients():
 q=request.args.get('q',''); patients=User.query.filter_by(role='patient').filter(or_(User.name.ilike(f'%{q}%'),User.email.ilike(f'%{q}%'))).all();return render_template('admin/patients.html',patients=patients,q=q)
@app.route('/admin/appointments')
@role_required('admin')
def admin_appointments():
 q=Appointment.query; status=request.args.get('status'); doctor=request.args.get('doctor'); day=request.args.get('date')
 if status:q=q.filter_by(status=status)
 if doctor:q=q.filter_by(doctor_id=doctor)
 if day:
  try:q=q.filter_by(appointment_date=date.fromisoformat(day))
  except ValueError:pass
 return render_template('admin/appointments.html',appointments=q.order_by(Appointment.appointment_date.desc()).all(),doctors=DoctorProfile.query.all())
@app.route('/admin/appointment/<int:aid>/cancel',methods=['POST'])
@role_required('admin')
def admin_cancel(aid):
 a=db.session.get(Appointment,aid) or abort(404)
 try:transition(a,'Cancelled');db.session.commit();notify('appointment_cancelled',a);flash('Appointment cancelled.','success')
 except ValueError as e:flash(str(e),'danger')
 return redirect(url_for('admin_appointments'))
def automation_ok(): return app.config['N8N_AUTOMATION_SECRET'] and request.headers.get('X-Automation-Secret')==app.config['N8N_AUTOMATION_SECRET']
@app.route('/api/automation/expire-pending',methods=['POST'])
@csrf.exempt
def expire_pending():
 if not automation_ok(): return jsonify(error='Unauthorized'),401
 expired=[a for a in Appointment.query.filter_by(status='Pending').all() if start_dt(a)<=now()]
 for a in expired: transition(a,'Cancelled')
 db.session.commit()
 for a in expired: notify('pending_expired',a)
 return jsonify(cancelled=len(expired))
@app.route('/api/automation/reminders',methods=['POST'])
@csrf.exempt
def reminders():
 if not automation_ok(): return jsonify(error='Unauthorized'),401
 target=date.today()+timedelta(days=1); rows=Appointment.query.filter_by(status='Confirmed',appointment_date=target,reminder_sent=False).all()
 for a in rows:a.reminder_sent=True
 db.session.commit()
 for a in rows:notify('appointment_reminder',a)
 return jsonify(reminders=len(rows))
@app.errorhandler(403)
def forbidden(e):return render_template('errors/error.html',code=403,message='You do not have permission to view this page.'),403
@app.errorhandler(404)
def missing(e):return render_template('errors/error.html',code=404,message='We could not find that page.'),404
@app.errorhandler(500)
def broken(e):db.session.rollback();return render_template('errors/error.html',code=500,message='Something went wrong. Please try again.'),500
def seed():
 if User.query.filter_by(email='admin@clinic.local').first():return
 admin=User(name='Clinic Administrator',email='admin@clinic.local',role='admin');admin.set_password('Admin123!')
 doc=User(name='Dr. Ayesha Khan',email='doctor@clinic.local',role='doctor');doc.set_password('Doctor123!'); profile=DoctorProfile(user=doc,specialty='ENT Specialist')
 patient=User(name='Demo Patient',email='patient@clinic.local',phone='0300-0000000',role='patient');patient.set_password('Patient123!')
 db.session.add_all([admin,doc,patient,profile]);db.session.flush()
 for wd in range(5): db.session.add(Availability(doctor_id=profile.id,weekday=wd,start_time=time(9),end_time=time(13)))
 db.session.commit()
if __name__=='__main__':
 with app.app_context(): db.create_all();seed()
 app.run(debug=False)
