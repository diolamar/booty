from flask import Blueprint,render_template,redirect,url_for
from forms import CreateForm, UpdateForm
from models import TodoModel

view = Blueprint('view',__name__)

@view.route('/')
def home():
    todo = TodoModel.all()
    print(todo)
    return render_template('index.html',todo=todo)

@view.route('/new', methods=['POST', 'GET'])
def new():
    form = CreateForm()
    if form.validate_on_submit():
        todo = TodoModel(fullname=form.fullname.data,age=form.age.data,gender=form.gender.data,placeofdeath=form.placeofdeath.data,causeofdeath=form.causeofdeath.data)
        todo.save_to_db()
        return redirect(url_for('view.home'))
    return render_template('create.html',form = form)

@view.route('/update/<int:_id>',methods = ['POST','GET'])
def update(_id):
    todo = TodoModel.find_by_id(_id)
    form = UpdateForm(obj=todo)
    if form.validate_on_submit():
        todo.fullname = form.fullname.data
        todo.age = form.age.data
        todo.gender = form.gender.data
        todo.placeofdeath = form.placeofdeath.data
        todo.causeofdeath = form.causeofdeath.data
        todo.save_to_db()
        return redirect(url_for('view.home'))
    return render_template('update.html',form = form,todo = todo)

@view.route('/delete/<int:_id>')
def delete(_id):
    todo = TodoModel.find_by_id(_id)
    todo.delete_to_db()
    return redirect(url_for('view.home'))