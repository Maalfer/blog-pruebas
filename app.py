from flask import Flask, render_template, redirect, url_for, flash, request, session, send_from_directory
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, PasswordField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, EqualTo
from datetime import datetime
import secrets
import os
import sqlite3
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image
from contextlib import contextmanager

# --- NUEVO: Markdown + saneado ---
import markdown as md
import bleach

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['DATABASE'] = 'blog.db'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                author TEXT NOT NULL,
                category TEXT NOT NULL,
                image TEXT NOT NULL,
                date_created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (author) REFERENCES users (username)
            )
        ''')
        admin_exists = conn.execute(
            'SELECT id FROM users WHERE username = ?', ('admin',)
        ).fetchone()
        if not admin_exists:
            password_hash = generate_password_hash('admin123')
            conn.execute(
                'INSERT INTO users (username, password_hash) VALUES (?, ?)',
                ('admin', password_hash)
            )
        conn.commit()

def save_image(image_file):
    if image_file and image_file.filename:
        filename = secure_filename(image_file.filename)
        unique_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        image_file.save(filepath)
        try:
            img = Image.open(filepath)
            if img.size[0] > 1200 or img.size[1] > 800:
                img.thumbnail((1200, 800), Image.Resampling.LANCZOS)
                img.save(filepath, optimize=True, quality=85)
        except Exception as e:
            print(f"Error optimizando imagen: {e}")
        return unique_filename
    return None

# --- NUEVO: Conversor Markdown seguro ---
MD_EXTENSIONS = [
    'extra',
    'fenced_code',
    'sane_lists',
    'toc',
    'tables',
]

ALLOWED_TAGS = bleach.sanitizer.ALLOWED_TAGS.union({
    'p', 'pre', 'code', 'hr', 'br',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'blockquote', 'ul', 'ol', 'li',
})

ALLOWED_ATTRS = {
    **bleach.sanitizer.ALLOWED_ATTRIBUTES,
    'a': ['href', 'title', 'rel', 'target'],
    'img': ['src', 'alt', 'title'],
    'code': ['class'],
    'th': ['align'], 'td': ['align'],
}

def render_markdown_safe(md_text: str) -> str:
    html = md.markdown(md_text or '', extensions=MD_EXTENSIONS, output_format='html5')
    clean = bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
    clean = bleach.linkify(clean, callbacks=[bleach.linkifier.DEFAULT_CALLBACK])
    return clean

class LoginForm(FlaskForm):
    username = StringField('Usuario', validators=[DataRequired()])
    password = PasswordField('Contraseña', validators=[DataRequired()])
    submit = SubmitField('Iniciar Sesión')

class RegisterForm(FlaskForm):
    username = StringField('Usuario', validators=[DataRequired(), Length(min=4, max=20)])
    password = PasswordField('Contraseña', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirmar Contraseña', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Registrarse')

class PostForm(FlaskForm):
    title = StringField('Título', validators=[DataRequired(), Length(max=100)])
    content = TextAreaField('Contenido', validators=[DataRequired()])
    category = StringField('Categoría', validators=[DataRequired(), Length(max=30)])
    image = FileField('Imagen de Fondo', validators=[
        FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Solo imágenes permitidas!')
    ])
    submit = SubmitField('Publicar Post')

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/')
def home():
    q = request.args.get('q', '', type=str).strip()
    with get_db_connection() as conn:
        if q:
            like = f"%{q.lower()}%"
            posts = conn.execute('''
                SELECT id, title, content, author, category, image, date_created
                FROM posts
                WHERE LOWER(title) LIKE ? OR LOWER(content) LIKE ? OR LOWER(category) LIKE ?
                ORDER BY date_created DESC
            ''', (like, like, like)).fetchall()
        else:
            posts = conn.execute('''
                SELECT id, title, content, author, category, image, date_created
                FROM posts
                ORDER BY date_created DESC
            ''').fetchall()
        posts_list = []
        for post in posts:
            posts_list.append({
                'id': post['id'],
                'title': post['title'],
                'content': post['content'],
                'author': post['author'],
                'category': post['category'],
                'image': post['image'],
                'date_created': post['date_created']
            })
        return render_template('home.html', posts=posts_list, q=q)

@app.route('/search')
def search():
    q = request.args.get('q', '', type=str).strip()
    with get_db_connection() as conn:
        if q:
            like = f"%{q.lower()}%"
            posts = conn.execute('''
                SELECT id, title, content, author, category, image, date_created
                FROM posts
                WHERE LOWER(title) LIKE ? OR LOWER(content) LIKE ? OR LOWER(category) LIKE ?
                ORDER BY date_created DESC
            ''', (like, like, like)).fetchall()
        else:
            posts = conn.execute('''
                SELECT id, title, content, author, category, image, date_created
                FROM posts
                ORDER BY date_created DESC
            ''').fetchall()
    posts_list = []
    for p in posts:
        posts_list.append({
            'id': p['id'],
            'title': p['title'],
            'content': p['content'],
            'author': p['author'],
            'category': p['category'],
            'image': p['image'],
            'date_created': p['date_created']
        })
    return render_template('partials/_posts_grid.html', posts=posts_list)

@app.route('/latest-publications')
def latest_publications():
    with get_db_connection() as conn:
        posts = conn.execute('''
            SELECT * FROM posts 
            ORDER BY date_created DESC 
            LIMIT 4
        ''').fetchall()
        posts_list = []
        for post in posts:
            posts_list.append({
                'id': post['id'],
                'title': post['title'],
                'content': post['content'],
                'author': post['author'],
                'category': post['category'],
                'image': post['image'],
                'date_created': post['date_created']
            })
        return render_template('latest_publications.html', posts=posts_list)

@app.route('/categorias')
def categories():
    with get_db_connection() as conn:
        rows = conn.execute('''
            SELECT category, COUNT(*) AS total
            FROM posts
            GROUP BY category
            ORDER BY total DESC, category ASC
        ''').fetchall()
        posts = conn.execute('''
            SELECT id, title, content, author, category, image, date_created
            FROM posts
            ORDER BY date_created DESC
        ''').fetchall()
    grouped = {}
    for p in posts:
        grouped.setdefault(p["category"], []).append(p)
    return render_template('categories.html', categories=rows, grouped_posts=grouped)

@app.route('/categoria/<string:cat_name>')
def category_detail(cat_name):
    with get_db_connection() as conn:
        posts = conn.execute('''
            SELECT id, title, content, author, category, image, date_created
            FROM posts
            WHERE category = ?
            ORDER BY date_created DESC
        ''', (cat_name,)).fetchall()
    if not posts:
        return render_template('category_empty.html', cat_name=cat_name), 404
    return render_template('category_detail.html', cat_name=cat_name, posts=posts)

@app.route('/sobre-nosotros')
def about():
    with get_db_connection() as conn:
        posts = conn.execute('''
            SELECT id, title, content, author, category, image, date_created
            FROM posts
            WHERE LOWER(category) = 'noticias'
            ORDER BY date_created DESC
        ''').fetchall()
    return render_template('sobre-nosotros.html', posts=posts)

@app.route('/contacto')
def contact():
    return render_template('contact.html')

@app.route('/post/<int:post_id>')
def view_post(post_id):
    with get_db_connection() as conn:
        post = conn.execute(
            'SELECT * FROM posts WHERE id = ?', (post_id,)
        ).fetchone()
        if not post:
            flash('El post no existe', 'danger')
            return redirect(url_for('home'))

        # --- NUEVO: convertir Markdown a HTML seguro ---
        content_html = render_markdown_safe(post['content'])

        post_dict = {
            'id': post['id'],
            'title': post['title'],
            'content': post['content'],          # markdown crudo (útil si luego editas)
            'content_html': content_html,        # HTML saneado para mostrar
            'author': post['author'],
            'category': post['category'],
            'image': post['image'],
            'date_created': post['date_created']
        }
        return render_template('post.html', post=post_dict)

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        with get_db_connection() as conn:
            user = conn.execute(
                'SELECT * FROM users WHERE username = ?', (username,)
            ).fetchone()
            if user and check_password_hash(user['password_hash'], password):
                session['user'] = username
                session['user_id'] = user['id']
                flash('¡Sesión iniciada correctamente!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Usuario o contraseña incorrectos', 'danger')
    return render_template('login.html', form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        with get_db_connection() as conn:
            existing_user = conn.execute(
                'SELECT id FROM users WHERE username = ?', (username,)
            ).fetchone()
            if existing_user:
                flash('El usuario ya existe', 'danger')
            else:
                password_hash = generate_password_hash(password)
                conn.execute(
                    'INSERT INTO users (username, password_hash) VALUES (?, ?)',
                    (username, password_hash)
                )
                conn.commit()
                flash('¡Registro exitoso! Ahora puedes iniciar sesión', 'success')
                return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        flash('Debes iniciar sesión para acceder al dashboard', 'warning')
        return redirect(url_for('login'))
    with get_db_connection() as conn:
        user_posts = conn.execute(
            'SELECT * FROM posts WHERE author = ? ORDER BY date_created DESC',
            (session['user'],)
        ).fetchall()
        posts_list = []
        for post in user_posts:
            posts_list.append({
                'id': post['id'],
                'title': post['title'],
                'content': post['content'],
                'author': post['author'],
                'category': post['category'],
                'image': post['image'],
                'date_created': post['date_created']
            })
        return render_template('dashboard.html', username=session['user'], posts=posts_list)

@app.route('/logout')
def logout():
    session.pop('user', None)
    session.pop('user_id', None)
    flash('Sesión cerrada correctamente', 'info')
    return redirect(url_for('home'))

@app.route('/admin/create', methods=['GET', 'POST'])
def create_post():
    if 'user' not in session:
        flash('Debes iniciar sesión para crear posts', 'warning')
        return redirect(url_for('login'))
    form = PostForm()
    if form.validate_on_submit():
        image_filename = save_image(form.image.data)
        if not image_filename:
            default_images = ['default-bg.jpg', 'default-bg2.jpg', 'default-bg3.jpg']
            import random
            image_filename = random.choice(default_images)
        with get_db_connection() as conn:
            conn.execute('''
                INSERT INTO posts (title, content, author, category, image)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                form.title.data,
                form.content.data,
                session['user'],
                form.category.data,
                image_filename
            ))
            conn.commit()
        flash('¡Post creado exitosamente con imagen!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('create_post.html', form=form)

@app.route('/admin/edit/<int:post_id>', methods=['GET', 'POST'])
def edit_post(post_id):
    if 'user' not in session:
        flash('Debes iniciar sesión para editar posts', 'warning')
        return redirect(url_for('login'))
    with get_db_connection() as conn:
        post = conn.execute(
            'SELECT * FROM posts WHERE id = ?', (post_id,)
        ).fetchone()
        if not post:
            flash('El post no existe', 'danger')
            return redirect(url_for('dashboard'))
        if post['author'] != session['user']:
            flash('No tienes permisos para editar este post', 'danger')
            return redirect(url_for('dashboard'))
        form = PostForm()
        if form.validate_on_submit():
            update_data = {
                'title': form.title.data,
                'content': form.content.data,
                'category': form.category.data
            }
            if form.image.data:
                image_filename = save_image(form.image.data)
                if image_filename:
                    update_data['image'] = image_filename
            set_clause = ', '.join([f"{key} = ?" for key in update_data.keys()])
            values = list(update_data.values())
            values.append(post_id)
            conn.execute(
                f'UPDATE posts SET {set_clause} WHERE id = ?',
                values
            )
            conn.commit()
            flash('¡Post actualizado exitosamente!', 'success')
            return redirect(url_for('dashboard'))
        elif request.method == 'GET':
            form.title.data = post['title']
            form.content.data = post['content']
            form.category.data = post['category']
        post_dict = {
            'id': post['id'],
            'title': post['title'],
            'content': post['content'],
            'author': post['author'],
            'category': post['category'],
            'image': post['image'],
            'date_created': post['date_created']
        }
    return render_template('edit_post.html', form=form, post=post_dict)

@app.route('/admin/delete/<int:post_id>')
def delete_post(post_id):
    if 'user' not in session:
        flash('Debes iniciar sesión para eliminar posts', 'warning')
        return redirect(url_for('login'))
    with get_db_connection() as conn:
        post = conn.execute(
            'SELECT * FROM posts WHERE id = ?', (post_id,)
        ).fetchone()
        if not post:
            flash('El post no existe', 'danger')
            return redirect(url_for('dashboard'))
        if post['author'] != session['user']:
            flash('No tienes permisos para eliminar este post', 'danger')
            return redirect(url_for('dashboard'))
        conn.execute('DELETE FROM posts WHERE id = ?', (post_id,))
        conn.commit()
    flash('¡Post eliminado exitosamente!', 'success')
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
