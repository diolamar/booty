from flask import Flask, render_template, request
from flask_paginate import Pagination, get_page_args, get_page_parameter
from flask_mysqldb import MySQL 
import simplejson as json

app = Flask(__name__)

app.secret_key = 'many random bytes'

app.config['MYSQL_HOST'] = 'localhost' 
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'logs'
mysql = MySQL(app)


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

app.template_folder = ''
users = list(labels)

def get_users(offset=0, per_page=10):
    return users[offset: offset + per_page]


@app.route('/')
def index():
    page, per_page, offset = get_page_args(page_parameter='page',per_page_parameter='per_page')
    total = len(users)
    pagination_users = get_users(offset=offset, per_page=per_page)
    pagination = Pagination(page=page, per_page=per_page, total=total,
                            css_framework='bootstrap4')
    return render_template('index.html',
                           users=pagination_users,
                           page=page,
                           per_page=per_page,
                           pagination=pagination,
                           )

@app.route('/sample')
def sample():
    page = request.args.get(get_page_parameter(), type=int, default=1)
    limit = 20
    offset = page * limit - limit
    cursor = mysql.connection.cursor()

    cursor.execute("SELECT * from country")

    result = cursor.fetchall()
    total = len(result)
    cursor.execute("SELECT * FROM country ORDER BY coutryid ASC LIMIT %s OFFSET %s", (limit, offset))
    data = cursor.fetchall()
    cursor.close()

    pagination = Pagination(page=page, per_page=limit, total=total, css_framework='bootstrap4')
    return render_template('sample.html', pagination=pagination, country=data)


@app.route('/sampl', defaults={'page':1})
@app.route('/sampl/page/<int:page>')
def abc(page):
    perpage=20
    startat=page*perpage
    #db = mysql.connect('localhost', 'root', '', 'logs')
    cur = mysql.connection.cursor()
    #cursor = db.cursor()
    cur.execute('SELECT * FROM country limit %s, %s;', (startat,perpage))
    data = list(cur.fetchall())
    return render_template('sampl.html', data=data)



@app.route('/samp', defaults={'page':1})
@app.route('/samp/page/<int:page>')
def abcc(page):
    perpage=20
    startat=page*perpage
    #db = mysql.connect('localhost', 'root', '', 'logs')
    cur = mysql.connection.cursor()
    #cursor = db.cursor()
    cur.execute('SELECT * FROM country limit %s, %s;', (startat,perpage))
    data = list(cur.fetchall())
    return render_template('sampl.html', data=data)

if __name__ == '__main__':
    app.run(debug=True)