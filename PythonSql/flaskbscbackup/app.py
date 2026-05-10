from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_mysqldb import MySQL

app = Flask(__name__)
app.secret_key = 'flash message'

app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'flusk_crud'

mySql = MySQL(app)

all_post = [
    {
        'title': 'hello world',
        'author': 'abc'
    },
    {
        'title': 'hello world 2',
    }
]

@app.route('/')
def Index():
    cur = mySql.connection.cursor()
    cur.execute('SELECT * FROM posts')
    rawData = cur.fetchall()
    cur.close()
    data = []
    content = {}

    # for row in rawData:
    #     content = {'id': row[0], 'title': row[1], 'description': row[2], 'author': row[3]}
    #     data.append(content)
    #     content = {}

    return render_template('index.html', posts=rawData)

@app.route('/post')
def post():
    return render_template('post.html', posts=all_post)

@app.route('/add-post')
def addPostView():
    return render_template('add-post.html')

@app.route('/api/add-post', methods=['POST'])
def addPost():
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        author = request.form['author']

        cur = mySql.connection.cursor()
        cur.execute("INSERT INTO posts (title, description, author) VALUES (%s, %s, %s)", (title, description, author))
        mySql.connection.commit()
        flash("data inserted successfully")
        return redirect(url_for('Index'))


@app.route('/api/get-post/<string:postId>')
def getPost(postId):
    cur = mySql.connection.cursor()
    cur.execute('SELECT * FROM posts WHERE id = '+ postId)
    data = cur.fetchall()
    cur.close()
    return render_template('edit-post.html', post=data)

@app.route('/api/update', methods=['POST'])
def update():
    if request.method == 'POST':
        id = request.form['id']
        title = request.form['title']
        author = request.form['author']
        description = request.form['description']

        cur = mySql.connection.cursor()
        cur.execute('UPDATE posts SET title=%s, description=%s, author=%s WHERE id=%s', (title, description, author, id))
        mySql.connection.commit()
        return redirect(url_for('Index'))


@app.route('/api/delete/<string:postId>')
def delete(postId):
    cur = mySql.connection.cursor()
    cur.execute('DELETE FROM posts WHERE id=%s',(postId))
    mySql.connection.commit()
    return redirect(url_for('Index'))

if __name__ == "__main__":
    app.run(debug=True)