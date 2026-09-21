import unittest
from datetime import date, datetime, time, timedelta
from app import app, db, seed, User, DoctorProfile, Appointment, Availability, slots

class ClinicTests(unittest.TestCase):
 def setUp(self):
  app.config.update(TESTING=True,WTF_CSRF_ENABLED=False,N8N_AUTOMATION_SECRET='test-secret'); self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all();seed();self.client=app.test_client();self.doctor=DoctorProfile.query.one();self.patient=User.query.filter_by(email='patient@clinic.local').one();self.day=date.today()+timedelta(days=(7-date.today().weekday())%7 or 7)
 def tearDown(self): db.session.remove();db.drop_all();self.ctx.pop()
 def login(self,email,password): return self.client.post('/login',data={'email':email,'password':password})
 def make_appt(self,patient=None,doctor=None,day=None,slot=time(9),status='Pending'):
  a=Appointment(patient=patient or self.patient,doctor=doctor or self.doctor,appointment_date=day or self.day,start_time=slot,end_time=(datetime.combine(day or self.day,slot)+timedelta(minutes=30)).time(),status=status);db.session.add(a);db.session.commit();return a
 def test_01_signup_role_protection(self):
  self.client.post('/signup',data={'name':'New','phone':'1','email':'new@example.com','password':'password1','confirm':'password1'});self.assertEqual(User.query.filter_by(email='new@example.com').one().role,'patient');self.assertEqual(self.client.get('/admin').status_code,403)
 def test_02_book_and_confirm(self):
  self.login('patient@clinic.local','Patient123!');self.client.post(f'/patient/book/{self.doctor.id}',data={'day':self.day.isoformat(),'slot':'09:00'});a=Appointment.query.one();self.client.get('/logout');self.login('doctor@clinic.local','Doctor123!');self.client.post(f'/doctor/appointment/{a.id}/status',data={'status':'Confirmed'});self.assertEqual(db.session.get(Appointment,a.id).status,'Confirmed')
 def test_03_double_booking(self):
  self.make_appt(); other=User(name='Other',email='other@example.com',role='patient');other.set_password('password1');db.session.add(other);db.session.commit();self.login('other@example.com','password1');self.client.post(f'/patient/book/{self.doctor.id}',data={'day':self.day.isoformat(),'slot':'09:00'});self.assertEqual(Appointment.query.count(),1)
 def test_04_past_outside_inactive(self):
  self.login('patient@clinic.local','Patient123!');self.client.post(f'/patient/book/{self.doctor.id}',data={'day':self.day.isoformat(),'slot':'15:00'});self.client.post(f'/patient/book/{self.doctor.id}',data={'day':(date.today()-timedelta(days=1)).isoformat(),'slot':'09:00'});self.doctor.active=False;db.session.commit();self.client.post(f'/patient/book/{self.doctor.id}',data={'day':self.day.isoformat(),'slot':'09:00'});self.assertEqual(Appointment.query.count(),0)
 def test_05_slots_and_overlap(self):
  self.assertEqual([x.strftime('%H:%M') for x in slots(self.doctor,self.day)][:4],['09:00','09:30','10:00','10:30']);self.login('doctor@clinic.local','Doctor123!');self.client.post('/doctor/availability',data={'weekday':self.day.weekday(),'start':'10:00','end':'12:00'});self.assertEqual(Availability.query.filter_by(doctor_id=self.doctor.id).count(),5)
 def test_06_leave_cancels(self):
  a=self.make_appt(status='Confirmed');self.login('doctor@clinic.local','Doctor123!');self.client.post('/doctor/leave',data={'leave_date':self.day.isoformat()});self.assertEqual(db.session.get(Appointment,a.id).status,'Cancelled');self.assertEqual(slots(self.doctor,self.day),[])
 def test_07_cancel_reschedule(self):
  a=self.make_appt(status='Confirmed');self.login('patient@clinic.local','Patient123!');self.client.post(f'/patient/appointment/{a.id}/cancel');self.assertEqual(db.session.get(Appointment,a.id).status,'Cancelled');a=self.make_appt(slot=time(9,30),status='Confirmed');self.client.post(f'/patient/appointment/{a.id}/reschedule',data={'day':self.day.isoformat(),'slot':'10:00'});a=db.session.get(Appointment,a.id);self.assertEqual((a.status,a.start_time),('Pending',time(10)))
 def test_08_privacy_and_permissions(self):
  a=self.make_appt(status='Confirmed');a.visit_note='private';db.session.commit();self.login('admin@clinic.local','Admin123!');self.assertNotIn(b'private',self.client.get('/admin/appointments').data);self.client.get('/logout');self.login('patient@clinic.local','Patient123!');self.assertEqual(self.client.get('/doctor').status_code,403)
 def test_09_complete_after_start(self):
  a=self.make_appt(status='Confirmed');self.login('doctor@clinic.local','Doctor123!');self.client.post(f'/doctor/appointment/{a.id}/status',data={'status':'Completed','note':'future'});self.assertEqual(db.session.get(Appointment,a.id).status,'Confirmed');a.appointment_date=date.today();a.start_time=time(0);db.session.commit();self.client.post(f'/doctor/appointment/{a.id}/status',data={'status':'Completed','note':'done'});self.assertEqual(db.session.get(Appointment,a.id).status,'Completed')
 def test_10_automation(self):
  a=self.make_appt(day=date.today()+timedelta(days=1),status='Confirmed');r=self.client.post('/api/automation/reminders',headers={'X-Automation-Secret':'test-secret'});self.assertEqual(r.json['reminders'],1);self.assertTrue(db.session.get(Appointment,a.id).reminder_sent);self.assertEqual(self.client.post('/api/automation/reminders',headers={'X-Automation-Secret':'test-secret'}).json['reminders'],0);old=self.make_appt(day=date.today(),slot=time(0,30));self.client.post('/api/automation/expire-pending',headers={'X-Automation-Secret':'test-secret'});self.assertEqual(db.session.get(Appointment,old.id).status,'Cancelled')
if __name__=='__main__':unittest.main()
