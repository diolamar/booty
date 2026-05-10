from flask import Flask, request, render_template, make_response
from flask_mysqldb import MySQL
from flask_weasyprint import HTML, render_pdf
import pdfkit
import os
#config = pdfkit.configuration(wkhtmltopdf='C:\\Program Files\\wkhtmltopdf\\bin\\wkhtmltopdf.exe')

app = Flask(__name__)

app.secret_key = 'many random bytes'

app.config['MYSQL_HOST'] = 'localhost' 
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'logs'
mysql = MySQL(app)

@app.route('/')
def Index():
    
    return render_template('index.html')


@app.route('/ds')
def ds():
    path_wkhtmltopdf = 'C:\\Program Files\\wkhtmltopdf\\bin\\wkhtmltopdf.exe'
    config = pdfkit.configuration(wkhtmltopdf=path_wkhtmltopdf)
    rendered=render_template('index.html',test='hi')
    #cssPath=['static/css/resumeCss.css']
    pdf=pdfkit.from_string(rendered, False,configuration=config)
    response=make_response(pdf)
    response.headers['Content-Type']='application/pdf'
    # response.headers['Content-Disposition']='attachment; filename=Print Me.pdf'
    response.headers['Content-Disposition']='inline'
    return response


@app.route('/sampl')
def sampl():
    
    return render_template('sampl.html')


@app.route('/pdfweasprint')
def pdfweasprint():
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM country")
    data = cur.fetchall()
    cur.close()
   # html = render_template('pdfweasprint.html', data=data)
   # return render_pdf(HTML(string=html))
    return render_template('pdfweasprint.html', data=data)


if __name__ == '__main__':
    app.run(debug=True)
    