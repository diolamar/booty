from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
db = SQLAlchemy()

class TodoModel(db.Model):
    id = db.Column('id', db.Integer,primary_key=True)
    fullname = db.Column('fullname', db.String(100),nullable=False)
    age = db.Column('age', db.String(100),nullable=False)
    gender = db.Column('gender', db.String(100),nullable=False)
    placeofdeath = db.Column('placeofdeath', db.String(100),nullable=False)
    causeofdeath = db.Column('causeofdeath', db.String(100),nullable=False)
    date_created = db.Column('date_created',db.DateTime,default=datetime.today())

    def __init__(self, fullname, age, gender,placeofdeath, causeofdeath):
        self.fullname = fullname
        self.age = age
        self.gender = gender
        self.placeofdeath = placeofdeath
        self.causeofdeath = causeofdeath
    @classmethod
    def all(cls):
        return cls.query.all()
    @classmethod
    def find_by_id(cls, _id):
        return cls.query.filter_by(id = _id).first()

    def save_to_db(self):
        db.session.add(self)
        db.session.commit()
        return True

    def delete_to_db(self):
        db.session.delete(self)
        db.session.commit()
        return True

    def __repr__(self):
        return 'Todo ({id}, {fullname}, {age}, {gender}, {placeofdeath}, {causeofdeath})'.format(
            id = self.id,
            fullname = self.fullname,
            age = self.age,
            gender = self.gender,
            placeofdeath = self.placeofdeath,
            causeofdeath = self.causeofdeath
        )
