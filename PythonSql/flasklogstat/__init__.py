from flask import Flask, render_template, request, redirect, url_for, flash, Markup, make_response
from flask_mysqldb import MySQL
from datetime import date
import simplejson as json
from flask import Blueprint
from flask_paginate import Pagination, get_page_parameter
import pdfkit
import os
pdfconfig = pdfkit.configuration(wkhtmltopdf='C:\\Program Files\\wkhtmltopdf\\bin\\wkhtmltopdf.exe')

mod = Blueprint('users', __name__)
app = Flask(__name__)
app.secret_key = 'many random bytes'

app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'logs'

mysql = MySQL(app)


def get_db():
    return mysql.connect

labels = [
    'JAN', 'FEB', 'MAR', 'APR',
    'MAY', 'JUN', 'JUL', 'AUG',
    'SEP', 'OCT', 'NOV', 'DEC'
]

values = [
    967.67, 1190.89, 1079.75, 1349.19,
    2328.91, 2504.28, 2873.83, 4764.87,
    4349.29, 6458.30, 9907, 16297
]

colors = [
    "#F7464A", "#46BFBD", "#FDB45C", "#FEDCBA",
    "#ABCDEF", "#DDDDDD", "#ABCABC", "#4169E1",
    "#C71585", "#FF4500", "#FEDCBA", "#46BFBD"]

@app.route('/')
def Index():
    page = request.args.get(get_page_parameter(), type=int, default=1)
    limit = 10
    offset = page * limit - limit
    cur = get_db().cursor()
    cur.execute("SELECT ip.country FROM month an, ipvv4 ip where (INET_ATON(an.address) BETWEEN INET_ATON(ip.start) AND INET_ATON(ip.end))GROUP BY ip.country")
    lenght = cur.fetchall()
    total = len(lenght)
    print(total)
    cur.execute("SELECT ip.country, an.activities, an.address, sum(an.hits) AS hits FROM month an, ipvv4 ip where (INET_ATON(an.address) BETWEEN INET_ATON(ip.start) AND INET_ATON(ip.end))GROUP BY ip.country ORDER BY hits DESC LIMIT %s OFFSET %s", (limit, offset))
    data = cur.fetchall()
    cur.close()
    flash(date.today())
    pagination = Pagination(page=page, per_page=limit, total=total, css_framework='bootstrap4')
    return render_template('index2.html', students=data, pagination=pagination)

#def fedd():
    #pdfkit.from_string("index.html,")

#@app.route('/hello_<name>.pdf')
#def hello_pdf(name):
    # Make a PDF straight from HTML in a string.
    #html = render_template('bar.html', name=name)
    #return render_pdf(HTML(string=html))

@app.route('/delete/<string:id_data>', methods = ['GET'])
def delete(id_data):
    flash("Record Has Been Deleted Successfully")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM students WHERE id=%s", (id_data,))
    conn.commit()
    return redirect(url_for('Index'))

@app.route('/charty')
def charty():
    cur = get_db().cursor()
    cur.execute("SELECT an.id, an.activities, ip.country, sum(an.hits) AS hits from month an, ipv4 ip WHERE (INET_ATON(an.address) BETWEEN INET_ATON(ip.start) AND INET_ATON(ip.end))GROUP BY ip.country ORDER BY hits DESC")
    data = cur.fetchall()
    flash(data)
    cur.close()
    return render_template('charty.html', student=data)

@app.route('/bar')
def bar():
    cur = get_db().cursor()
    cur.execute("SELECT an.id, ip.country, an.activities, sum(an.hits) AS hits from month an, ipvv4 ip where (INET_ATON(an.address) BETWEEN INET_ATON(ip.start) AND INET_ATON(ip.end))GROUP BY ip.country ORDER BY hits DESC LIMIT 10")    #SELECT v.name, l.lname from value v, labels l WHERE v.id=l.id"
    dat = cur.fetchall()
    cur.close()
    flash(date.today())
    return render_template('bar.html', x=dat)

@app.route('/pdd')
def pdd():
    pdfkit_options = {
            'margin-top': '0',
            'margin-right': '0',
            'margin-bottom': '0',
            'margin-left': '0',
            'encoding': 'UTF-8',
            'javascript-delay': '9000',
            'no-stop-slow-scripts': '',
        }

    pdfkit.from_url('http://127.0.0.1:5000/bar', 'out-test.pdf', configuration=pdfconfig, options=pdfkit_options)
    return redirect(url_for('bar'))

@app.route('/barr')
def barr():
    cur = get_db().cursor()
    cur.execute("SELECT an.id, ip.country, an.activities, sum(an.hits) AS hits from month an, ipv4 ip where (INET_ATON(an.address) BETWEEN INET_ATON(ip.start) AND INET_ATON(ip.end))GROUP BY ip.country ORDER BY hits DESC LIMIT 10")    #SELECT v.name, l.lname from value v, labels l WHERE v.id=l.id"
    dat = cur.fetchall()
    cur.close()
    flash(date.today())
    return render_template('barr.html',title='Monthly Top 10 Country Attackers', max=300, x=dat)

@app.route('/sumar')
def sumar():
    cur = get_db().cursor()
    cur.execute("SELECT sum(hits) as hits FROM month")
    hit = cur.fetchall()
    cur.execute("SELECT sum(an.hits), ip.country AS hits from month an, ipv4 ip where (INET_ATON(an.address) BETWEEN INET_ATON(ip.start) AND INET_ATON(ip.end))GROUP BY ip.country ORDER BY hits DESC LIMIT 1")
    total = cur.fetchall()
    cur.close()
    return render_template('sumar.html', hits=hit, tot=total)

@app.route('/topip')
def topip():
    cur = get_db().cursor()
    cur.execute("SELECT an.address, ip.country, sum(an.hits) AS hits FROM month an, ipvv4 ip where (INET_ATON(an.address) BETWEEN INET_ATON(ip.start) AND INET_ATON(ip.end))GROUP BY ip.country ORDER BY hits DESC LIMIT 10")
    data = cur.fetchall()
    cur.close()
    return render_template('topip.html', ip=data)

@app.route('/mail')
def mail():
    cur = get_db().cursor()
    cur.execute("SELECT * FROM mailmonth")
    data = cur.fetchall()
    cur.close()
    return render_template('mail.html', x=data)
  
if __name__ == "__main__":
    app.run(debug = True)

    #bar_labels=labels
    #bar_values=values
    #return render_template('barr.html', title='Bitcoin Monthly Price in USD', max=17000, labels=bar_labels, values=bar_values)


    
