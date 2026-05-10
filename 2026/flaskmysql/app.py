from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///demoAppDb.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your_secret_key'
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@app.after_request
def add_no_cache_headers(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class Subscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class RegistrationForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Register')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/favicon.ico')
def favicon():
    return redirect(url_for('static', filename='favicon.svg'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_pw = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        user = User(email=form.email.data, password=hashed_pw)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user)
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    flash('Logged out successfully', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    subscriptions = Subscription.query.filter_by(user_id=current_user.id).all()
    return render_template('dashboard.html', subscriptions=subscriptions)

@app.route('/subscription/add', methods=['GET', 'POST'])
@login_required
def add_subscription():
    if request.method == 'POST':
        name = request.form['name']
        price = request.form['price']
        new_subscription = Subscription(name=name, price=float(price), user_id=current_user.id)
        db.session.add(new_subscription)
        db.session.commit()
        flash('Subscription added!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('add_subscription.html')

@app.route('/subscription/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_subscription(id):
    sub = Subscription.query.get_or_404(id)
    if request.method == 'POST':
        sub.name = request.form['name']
        sub.price = request.form['price']
        db.session.commit()
        flash('Subscription updated!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('edit_subscription.html', sub=sub)

@app.route('/subscription/delete/<int:id>', methods=['POST'])
@login_required
def delete_subscription(id):
    sub = Subscription.query.get_or_404(id)
    db.session.delete(sub)
    db.session.commit()
    flash('Subscription deleted!', 'info')
    return redirect(url_for('dashboard'))

@app.route('/get_users', methods=['GET'])
def get_users_page():
    users = User.query.all()
    return render_template('get_users.html', users=users)

@app.route('/get_user/<int:id>', methods=['GET'])
def get_user_page(id):
    user = User.query.get_or_404(id) 
    return render_template('view_user.html', user=user)


@app.route('/api/users', methods=['GET'])
def get_users():
    users = User.query.all()
    return jsonify([{'id': user.id, 'email': user.email} for user in users])

@app.route('/api/user/<int:id>', methods=['GET'])
def get_user(id):
    user = User.query.get_or_404(id)
    return jsonify({'id': user.id, 'email': user.email})

@app.route('/api/subscriptions', methods=['GET'])
@login_required
def get_subscriptions():
    subscriptions = Subscription.query.filter_by(user_id=current_user.id).all()
    return jsonify([{'id': sub.id, 'name': sub.name, 'price': sub.price} for sub in subscriptions])

@app.route('/api/subscription/<int:id>', methods=['GET'])
@login_required
def get_subscription(id):
    sub = Subscription.query.get_or_404(id)
    return jsonify({'id': sub.id, 'name': sub.name, 'price': sub.price})

if __name__ == '__main__':
    # Ensure that db.create_all() runs within the application context
    with app.app_context():
        db.create_all()
    app.run(debug=True)
