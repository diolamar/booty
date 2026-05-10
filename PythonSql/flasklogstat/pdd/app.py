from flask import Flask, render_template, url_for, make_response, Response
import pdfkit
from fpdf import FPDF
from flask_mysqldb import MySQL

app = Flask(__name__)
app.secret_key = 'many random bytes'

app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'roytuts'

mysql = MySQL(app)


@app.route("/")
def index():
    name = "Giovanni Smith"
    return render_template('index.html', name=name)


@app.route("/pdf")
def pdf():
    name = "Giovanni Smith"
    html = render_template("index.html", name=name)
    pdf = pdfkit.from_string(html, False)
    response = make_response(pdf)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = "inline; filename=output.pdf"
    return response


@app.route('/sample')
def report():
	try:
		conn = mysql.connection.cursor()
		conn.execute("SELECT emp_id, emp_first_name, emp_last_name, emp_designation FROM employee")
		result = conn.fetchall()
		
		pdf = FPDF()
		pdf.add_page()
		
		page_width = pdf.w - 2 * pdf.l_margin
		
		pdf.set_font('Times','B',14.0) 
		pdf.cell(page_width, 0.0, 'Employee Data', align='C')
		pdf.ln(10)

		pdf.set_font('Courier', '', 12)
		
		col_width = page_width/4
		
		pdf.ln(1)
		
		th = pdf.font_size
		
		for row in result:
			pdf.cell(col_width, th, str(row['emp_id']), border=1)
			pdf.cell(col_width, th, row['emp_first_name'], border=1)
			pdf.cell(col_width, th, row['emp_last_name'], border=1)
			pdf.cell(col_width, th, row['emp_designation'], border=1)
			pdf.ln(th)
		
		pdf.ln(10)
		
		pdf.set_font('Times','',10.0) 
		pdf.cell(page_width, 0.0, '- end of report -', align='C')
		
		return Response(pdf.output(dest='S').encode('latin-1'), mimetype='application/pdf', headers={'Content-Disposition':'attachment;filename=employee_report.pdf'})
	except Exception as e:
		print(e)
	finally:
		conn.close()
		
if __name__ == '__main__':
    app.run(debug=True)