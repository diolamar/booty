from flask_bootstrap import Bootstrap
from flask_fontawesome import FontAwesome
from flask import Flask

from models import db
from views import view as view_blueprint

app = Flask(__name__)
app.config.from_pyfile('config.py')

bootstrap = Bootstrap(app)
fontawesome = FontAwesome(app)

db.init_app(app)

with app.app_context():
    db.create_all()

app.register_blueprint(view_blueprint)


if __name__ == '__main__':
    app.run(debug=True)