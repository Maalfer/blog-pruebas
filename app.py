from flask import Flask, render_template, redirect, url_for, flash, request, session, send_from_directory, jsonify
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
import markdown as md
import bleach
import re

try:
    from apscheduler.schedulers.background import BackgroundScheduler
except Exception:
    BackgroundScheduler = None

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'key-pruebas-local')
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['DATABASE'] = 'blog.db'
app.config['CLEANUP_INTERVAL_MINUTES'] = int(os.environ.get('CLEANUP_INTERVAL_MINUTES', '5'))

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
    'img'
})

ALLOWED_ATTRS = {
    **bleach.sanitizer.ALLOWED_ATTRIBUTES,
    'a': ['href', 'title', 'rel', 'target'],
    'img': ['src', 'alt', 'title'],
    'code': ['class'],
    'th': ['align'], 'td': ['align'],
}

def delete_image_file(filename):
    if not filename:
        return
    default_images = {'default-bg.jpg', 'default-bg2.jpg', 'default-bg3.jpg'}
    if filename in default_images:
        return
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.abspath(filepath).startswith(os.path.abspath(app.config['UPLOAD_FOLDER'])) and os.path.exists(filepath):
        try:
            os.remove(filepath)
        except Exception as e:
            print(f"Error al eliminar imagen {filename}: {e}")

def extract_upload_filenames(text: str) -> set:
    if not text:
        return set()
    names = set()
    for m in re.findall(r'(?i)(?:https?://[^\s)"\'>]+)?(/uploads/[^\s)"\'>]+)', text):
        p = m.split('?', 1)[0].split('#', 1)[0]
        names.add(os.path.basename(p))
    return names

def render_markdown_safe(md_text: str) -> str:
    html = md.markdown(md_text or '', extensions=MD_EXTENSIONS, output_format='html5')
    clean = bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
    clean = bleach.linkify(clean)
    return clean

def is_image_used_elsewhere(conn, filename: str, exclude_post_id: int | None = None) -> bool:
    like_pattern = f"%/uploads/{filename}%"
    if exclude_post_id is None:
        row = conn.execute("SELECT COUNT(*) AS c FROM posts WHERE content LIKE ?", (like_pattern,)).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) AS c FROM posts WHERE id <> ? AND content LIKE ?", (exclude_post_id, like_pattern)).fetchone()
    return (row["c"] or 0) > 0

def list_upload_filenames_on_disk() -> set:
    try:
        return {f for f in os.listdir(app.config['UPLOAD_FOLDER']) if os.path.isfile(os.path.join(app.config['UPLOAD_FOLDER'], f))}
    except Exception:
        return set()

def collect_used_upload_filenames(conn) -> set:
    used = set()
    rows = conn.execute("SELECT content, image FROM posts").fetchall()
    for r in rows:
        used |= extract_upload_filenames(r["content"] or "")
        img = r["image"] or ""
        if img and img not in {'default-bg.jpg', 'default-bg2.jpg', 'default-bg3.jpg'}:
            used.add(img)
    return used

def cleanup_orphan_uploads() -> dict:
    with get_db_connection() as conn:
        used = collect_used_upload_filenames(conn)
    disk = list_upload_filenames_on_disk()
    protected = {'default-bg.jpg', 'default-bg2.jpg', 'default-bg3.jpg'}
    deletable = {f for f in disk if f not in used and f not in protected}
    deleted = []
    for f in deletable:
        delete_image_file(f)
        deleted.append(f)
    return {"checked": len(disk), "used": len(used), "deleted": deleted}

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/admin/upload-inline-image', methods=['POST'])
def upload_inline_image():
    if 'user' not in session:
        return jsonify({'error': 'No autorizado'}), 401
    file = request.files.get('image')
    if not file or not file.filename:
        return jsonify({'error': 'No se envió ninguna imagen'}), 400
    filename = save_image(file)
    if not filename:
        return jsonify({'error': 'No se pudo guardar la imagen'}), 500
    file_url = url_for('uploaded_file', filename=filename)
    return jsonify({'url': file_url}), 200

@app.route('/admin/delete-inline-image', methods=['POST'])
def delete_inline_image():
    if 'user' not in session:
        return jsonify({'error': 'No autorizado'}), 401
    data = request.get_json(silent=True) or {}
    url = (data.get('url') or '').strip()
    if not url.startswith('/uploads/'):
        return jsonify({'error': 'URL inválida'}), 400
    filename = os.path.basename(url)
    with get_db_connection() as conn:
        if is_image_used_elsewhere(conn, filename, exclude_post_id=None):
            return jsonify({'skipped': True}), 200
    delete_image_file(filename)
    return jsonify({'deleted': True, 'filename': filename}), 200

@app.route('/admin/cleanup-orphans', methods=['POST', 'GET'])
def cleanup_orphans_endpoint():
    if 'user' not in session:
        return jsonify({'error': 'No autorizado'}), 401
    result = cleanup_orphan_uploads()
    if request.method == 'GET':
        flash(f"Archivos eliminados: {len(result['deleted'])}", 'info')
        return redirect(url_for('dashboard'))
    return jsonify(result), 200

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
        content_html = render_markdown_safe(post['content'])
        post_dict = {
            'id': post['id'],
            'title': post['title'],
            'content': post['content'],
            'content_html': content_html,
            'author': post['author'],
            'category': post['category'],
            'image': post['image'],
            'date_created': post['date_created']
        }
        return render_template('post.html', post=post_dict)

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
        post = conn.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()
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
            old_image = post['image']
            old_inline = extract_upload_filenames(post['content'])
            if form.image.data:
                image_filename = save_image(form.image.data)
                if image_filename:
                    update_data['image'] = image_filename
                    delete_image_file(old_image)
            set_clause = ', '.join([f"{key} = ?" for key in update_data.keys()])
            values = list(update_data.values())
            values.append(post_id)
            conn.execute(f'UPDATE posts SET {set_clause} WHERE id = ?', values)
            conn.commit()
            new_inline = extract_upload_filenames(update_data['content'])
            removed = old_inline - new_inline
            for fn in removed:
                if not is_image_used_elsewhere(conn, fn, exclude_post_id=post_id):
                    delete_image_file(fn)
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
        post = conn.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()
        if not post:
            flash('El post no existe', 'danger')
            return redirect(url_for('dashboard'))
        if post['author'] != session['user']:
            flash('No tienes permisos para eliminar este post', 'danger')
            return redirect(url_for('dashboard'))
        inline_files = extract_upload_filenames(post['content'])
        for fn in inline_files:
            if not is_image_used_elsewhere(conn, fn, exclude_post_id=post_id):
                delete_image_file(fn)
        delete_image_file(post['image'])
        conn.execute('DELETE FROM posts WHERE id = ?', (post_id,))
        conn.commit()
    flash('¡Post eliminado exitosamente!', 'success')
    return redirect(url_for('dashboard'))

def start_scheduler():
    if BackgroundScheduler is None:
        return
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        scheduler = BackgroundScheduler(daemon=True)
        scheduler.add_job(func=cleanup_orphan_uploads, trigger='interval', minutes=app.config['CLEANUP_INTERVAL_MINUTES'], max_instances=1, coalesce=True)
        scheduler.start()

if __name__ == '__main__':
    init_db()
    start_scheduler()
    app.run(debug=True)
