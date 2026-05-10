from flask import Flask, render_template, request, redirect, url_for, flash
from flask_mysqldb import MySQL
from datetime import date
import simplejson as json

app = Flask(__name__)
app.secret_key = 'many random bytes'

app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'cyberincident'

mysql = MySQL(app)


def get_db():
    return mysql.connect



@app.route('/')
def Index():
    cur = get_db().cursor()
    cur.execute("SELECT * FROM reporter ORDER BY reporterid DESC")
    data = cur.fetchall()
    cur.execute("SELECT * FROM incidentype ORDER BY incidentid")
    inci = cur.fetchall()
    cur.execute("SELECT * FROM gencategory")
    cat = cur.fetchall()
    cur.close()
    flash(date.today())
    return render_template('index2.html', students=data, incid=inci, cate=cat)



@app.route('/insert', methods = ['POST'])
def insert():

    if request.method == "POST":
        flash("Data Inserted Successfully")
        chk = request.form.getlist('check')
        incident = request.form.get('option')
        flash(incident)
        flash(chk)
        
       # cur = mysql.connection.cursor()
        
      #  cur.execute("INSERT INTO students (name, email, phone) VALUES (%s, %s, %s)", (name, email, phone))
       # mysql.connection.commit()
       
        return redirect(url_for('sample'))





@app.route('/delete/<string:id_data>', methods = ['GET'])
def delete(id_data):
    flash("Record Has Been Deleted Successfully")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM students WHERE id=%s", (id_data,))
    conn.commit()
    return redirect(url_for('Index'))





@app.route('/update',methods=['POST','GET'])
def update():

    if request.method == 'POST':
        id_data = request.form['id']
        name = request.form['name']
        email = request.form['email']
        phone = request.form['phone']
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""UPDATE students SET name=%s, email=%s, phone=%s WHERE id=%s""", (name, email, phone, id_data))
        flash("Data Updated Successfully")
        conn.commit()
        return redirect(url_for('Index'))

@app.route('/sample',methods=['POST','GET'])
def sample():
    cur = get_db().cursor()
    cur.execute("SELECT * FROM reporter ORDER BY reporterid DESC")
    data = cur.fetchall()
    cur.execute("SELECT * FROM incidentype ORDER BY incidentid")
    inci = cur.fetchall()
    cur.execute("SELECT * FROM csirtlevel")
    sirt = cur.fetchall()
    cur.execute("SELECT * FROM denialofserv")
    deny = cur.fetchall()
    cur.execute("SELECT * FROM devices")
    devv = cur.fetchall()
    cur.execute("SELECT * FROM dlbrtatck")
    dbt = cur.fetchall()
    cur.execute("SELECT * FROM hackingtype ORDER by hkngid DESC")
    hkng = cur.fetchall()
    cur.execute("SELECT * FROM prohibited")
    phbt = cur.fetchall()
    cur.execute("SELECT * FROM gencategory")
    cat = cur.fetchall()
    cur.close()
    flash(date.today())
    return render_template('sample.html', students=data, incid=inci, cate=cat, den=deny, dev=devv, dbts=dbt, hkg=hkng)
  
if __name__ == "__main__":
    app.run(debug = True)
