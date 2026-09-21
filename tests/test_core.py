import unittest
from datetime import date, timedelta
from app import app, db, seed, User, DoctorProfile, Appointment

class ClinicTests(unittest.TestCase):
 def setUp(self):
  app.config.update(TESTING=True,WTF_CSRF_ENABLED=False,SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
  self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all();seed();self.client=app.test_client()
 def tearDown(self): db.session.remove();db.drop_all();self.ctx.pop()
 def login(self,email,password): return self.client.post('/login',data={'email':email,'password':password})
 def test_patient_signup_and_role_protection(self):
  self.client.post('/signup',data={'name':'New','phone':'1','email':'new@example.com','password':'password1','confirm':'password1'})
  self.assertEqual(User.query.filter_by(email='new@example.com').one().role,'patient')
  self.assertEqual(self.client.get('/admin').status_code,403)
 def test_booking_and_duplicate_block(self):
  self.login('patient@clinic.local','Patient123!'); d=DoctorProfile.query.one(); day=date.today()+timedelta(days=(7-date.today().weekday())%7 or 7)
  r=self.client.post(f'/patient/book/{d.id}',data={'day':day.isoformat(),'slot':'09:00'},follow_redirects=True);self.assertIn(b'Appointment requested',r.data);self.assertEqual(Appointment.query.count(),1)
  r=self.client.post(f'/patient/book/{d.id}',data={'day':day.isoformat(),'slot':'09:00'},follow_redirects=True);self.assertIn(b'unavailable',r.data)
if __name__=='__main__':unittest.main()
