from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import (MetaData, Table, Column, Integer, String, FLOAT, VARCHAR)
import os

app = Flask(__name__)
app.secret_key = "Secret Key"

path = os.path.abspath( os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = "sqlite:///" + os.path.join(path , 'database.sqlite')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class Crud(db.Model):
    id = db.Column(db.Integer, primary_key = True)
    name = db.Column(db.VARCHAR(100), nullable=False)
    phone = db.Column(db.Integer, nullable=False)
    rating = db.Column(db.FLOAT(100,2), nullable=False)
    kwh = db.Column(db.FLOAT(100,2), nullable=False)
    price = db.Column(db.FLOAT(100,2), nullable=False)

    def __init__(self, name, phone, rating, kwh, price):

        self.name = name
        self.phone = phone
        self.rating = rating
        self.kwh = kwh
        self.price = price
    


@app.route('/')
def index():
    all_data = Crud.query.all()
    return render_template("index.html", all_data = all_data)

@app.route('/insert', methods = ['POST'])
def insert():
    
    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        rating = request.form['rating']
        kwh = request.form['kwh']
        price = int(rating) * int(kwh)
        
        my_data = Crud(name, phone, rating, kwh, price)
        db.session.add(my_data)
        db.session.commit()

        flash("Employee Inserted Successfully")
        return redirect(url_for('index'))

@app.route('/update', methods = ['POST'])
def update():
    if request.method == "POST":
        my_date = Crud.query.get(request.form.get('id'))
        my_date.name = request.form['name']
        my_date.phone = request.form['phone']
        my_date.rating = request.form['rating']
        my_date.kwh = request.form['kwh']
        my_date.price = float(my_date.rating) * float(my_date.kwh)

        db.session.commit()
        flash("Employee Updated Successfully")
        return redirect(url_for('index'))

@app.route('/delete/<id>/')
def delete(id):
    my_data = Crud.query.get(id)
    db.session.delete(my_data)
    db.session.commit()

    flash("Employee Data Deleted Successfully")
    return redirect(url_for('index'))

if __name__ == "__main__":
    app.run(debug = True)

