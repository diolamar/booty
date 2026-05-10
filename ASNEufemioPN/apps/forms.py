from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, SelectField,TextAreaField, validators

class CreateForm(FlaskForm):
     fullname = StringField('Enter Full Name : ',[validators.InputRequired()])
     age = StringField('Enter Age: ',[validators.InputRequired()])
     gender = StringField('Enter Gender: ',[validators.InputRequired()])
     placeofdeath = StringField('Enter Place of Death: ',[validators.InputRequired()])
     causeofdeath = StringField('Enter Cause of Death: ',[validators.InputRequired()])
     save = SubmitField('Save')

class UpdateForm(FlaskForm):
     fullname = StringField('Enter Full Name : ',[validators.InputRequired()])
     age = StringField('Enter Age: ',[validators.InputRequired()])
     gender = StringField('Enter Gender: ',[validators.InputRequired()])
     placeofdeath = StringField('Enter Place of Death: ',[validators.InputRequired()])
     causeofdeath = StringField('Enter Cause of Death: ',[validators.InputRequired()])
     update = SubmitField('Update')