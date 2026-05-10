#!/usr/local/bin/python
# -*- coding: UTF-8 -*-

from flask import Flask, render_template, request, url_for, redirect, redirect

from flask_sqlalchemy import SQLAlchemy


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite'

db = SQLAlchemy(app)


class Pessoa(db.Model):
	__tablename__ = 'pessoa'
	_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
	nome = db.Column(db.String)
	rua = db.Column(db.String)
	numero = db.Column(db.String)
	bairro = db.Column(db.String)
	cidade = db.Column(db.String)
	estado = db.Column(db.String)
	fone = db.Column(db.String)
	cpf = db.Column(db.String)
	email = db.Column(db.String)

	def __init__(self, nome, rua, numero, bairro, cidade, estado, fone, cpf, email):
		self.nome = nome
		self.rua = rua
		self.numero = numero
		self.bairro = bairro
		self.cidade = cidade
		self.estado = estado
		self.fone = fone
		self.cpf = cpf
		self.email = email


db.create_all()


@app.route("/")
def list():
	pessoas = Pessoa.query.all()
	return render_template("index.html", pessoas=pessoas)

@app.route("/cadastrar")
def cadastrar():
	return render_template("cadastro.html")

def voltar():
	return render_template("home")

@app.route("/cadastro", methods=['GET', 'POST'])
def cadastro():
	if request.method == "POST":
		nome = (request.form.get("name"))
		rua = (request.form.get("city"))
		numero = (request.form.get("num"))
		bairro = (request.form.get("bara"))
		cidade = (request.form.get("city"))
		estado = (request.form.get("state"))
		fone = (request.form.get("phone"))
		cpf = (request.form.get("cpf"))
		email = (request.form.get("email"))

		if nome and rua and numero and bairro and cidade and estado and fone and cpf and email:
			p = Pessoa(nome, rua, numero, bairro, cidade, estado, fone, cpf, email)
			db.session.commit()
			
	return redirect(url_for("list"))



@app.route("/atualizar/<int:id>", methods=['GET', 'POST'])
def atualizar(id):
	pessoa = Pessoa.query.filter_by(_id=id).first()
	if request.method == "POST":
		nome = (request.form.get("nome"))
		rua = (request.form.get("rua"))
		numero = (request.form.get("numero"))
		bairro = (request.form.get("bairro"))
		cidade = (request.form.get("cidade"))
		estado = (request.form.get("estado"))
		fone = (request.form.get("fone"))
		email = (request.form.get("email"))

		if nome and rua and numero and bairro and cidade and estado and fone and email:
			pessoa.nome = nome
			pessoa.rua= rua
			pessoa.numero = numero
			pessoa.bairro = bairro
			pessoa.cidade = cidade
			pessoa.estado = estado
			pessoa.fone = fone
			pessoa.email = email
			db.session.commit()

	return render_template("atualizar.html", pessoa=pessoa)

@app.route("/excluir/<int:id>")
def excluir(id):
	pessoa = Pessoa.query.filter_by(_id=id).first()

	db.session.delete(pessoa)
	db.session.commit()
	
	pessoas = Pessoa.query.all()
	return render_template("index.html", pessoas=pessoas)





if __name__ == "__main__":
	app.run(debug=True)
