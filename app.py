from flask import Flask, render_template, redirect, url_for, flash, request, session, send_from_directory
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, PasswordField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, EqualTo
from datetime import datetime
import secrets
import os
from werkzeug.utils import secure_filename
from PIL import Image

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Crear directorio de uploads si no existe
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Simulación de base de datos
users = {}
blog_posts = [
    {
        'id': 1,
        'title': 'Bienvenido al Blog Oscuro',
        'content': 'Este es el primer post de nuestro blog en la oscuridad. ¡Bienvenidos a las sombras!',
        'author': 'admin',
        'date_created': '2024-01-01',
        'category': 'General',
        'image': 'default-bg.jpg'
    },
    {
        'id': 2,
        'title': 'Cómo empezar con Flask en la Oscuridad',
        'content': 'Flask es un microframework de Python muy poderoso para desarrollo web. Perfecto para temas oscuros.',
        'author': 'admin',
        'date_created': '2024-01-02',
        'category': 'Tutorial',
        'image': 'default-bg2.jpg'
    }
]
next_post_id = 3

# Función para procesar y guardar imágenes
def save_image(image_file):
    if image_file and image_file.filename:
        # Generar nombre único para el archivo
        filename = secure_filename(image_file.filename)
        unique_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        
        # Guardar imagen
        image_file.save(filepath)
        
        # Optimizar imagen si es muy grande
        try:
            img = Image.open(filepath)
            if img.size[0] > 1200 or img.size[1] > 800:
                img.thumbnail((1200, 800), Image.Resampling.LANCZOS)
                img.save(filepath, optimize=True, quality=85)
        except Exception as e:
            print(f"Error optimizando imagen: {e}")
        
        return unique_filename
    return None

# Formularios
class LoginForm(FlaskForm):
    username = StringField('Usuario', validators=[DataRequired()])
    password = PasswordField('Contraseña', validators=[DataRequired()])
    submit = SubmitField('Iniciar Sesión')

class RegisterForm(FlaskForm):
    username = StringField('Usuario', validators=[DataRequired(), Length(min=4, max=20)])
    password = PasswordField('Contraseña', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirmar Contraseña', 
                                   validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Registrarse')

class PostForm(FlaskForm):
    title = StringField('Título', validators=[DataRequired(), Length(max=100)])
    content = TextAreaField('Contenido', validators=[DataRequired()])
    category = StringField('Categoría', validators=[DataRequired(), Length(max=30)])
    image = FileField('Imagen de Fondo', validators=[
        FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Solo imágenes permitidas!')
    ])
    submit = SubmitField('Publicar Post')

# Ruta para servir archivos upload
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Rutas principales
@app.route('/')
def home():
    return render_template('home.html', posts=blog_posts)

@app.route('/post/<int:post_id>')
def view_post(post_id):
    post = next((p for p in blog_posts if p['id'] == post_id), None)
    if not post:
        flash('El post no existe', 'danger')
        return redirect(url_for('home'))
    return render_template('post.html', post=post)

# Rutas de autenticación
@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        
        if username in users and users[username] == password:
            session['user'] = username
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
        
        if username in users:
            flash('El usuario ya existe', 'danger')
        else:
            users[username] = password
            flash('¡Registro exitoso! Ahora puedes iniciar sesión', 'success')
            return redirect(url_for('login'))
    
    return render_template('register.html', form=form)

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        flash('Debes iniciar sesión para acceder al dashboard', 'warning')
        return redirect(url_for('login'))
    
    user_posts = [post for post in blog_posts if post['author'] == session['user']]
    return render_template('dashboard.html', username=session['user'], posts=user_posts)

@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('Sesión cerrada correctamente', 'info')
    return redirect(url_for('home'))

# Rutas de administración de posts
@app.route('/admin/create', methods=['GET', 'POST'])
def create_post():
    if 'user' not in session:
        flash('Debes iniciar sesión para crear posts', 'warning')
        return redirect(url_for('login'))
    
    form = PostForm()
    if form.validate_on_submit():
        global next_post_id
        
        # Procesar imagen
        image_filename = save_image(form.image.data)
        if not image_filename:
            # Usar imagen por defecto si no se subió ninguna
            default_images = ['default-bg.jpg', 'default-bg2.jpg', 'default-bg3.jpg']
            import random
            image_filename = random.choice(default_images)
        
        new_post = {
            'id': next_post_id,
            'title': form.title.data,
            'content': form.content.data,
            'author': session['user'],
            'date_created': datetime.now().strftime('%Y-%m-%d'),
            'category': form.category.data,
            'image': image_filename
        }
        blog_posts.append(new_post)
        next_post_id += 1
        flash('¡Post creado exitosamente con imagen!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('create_post.html', form=form)

@app.route('/admin/edit/<int:post_id>', methods=['GET', 'POST'])
def edit_post(post_id):
    if 'user' not in session:
        flash('Debes iniciar sesión para editar posts', 'warning')
        return redirect(url_for('login'))
    
    post = next((p for p in blog_posts if p['id'] == post_id), None)
    if not post:
        flash('El post no existe', 'danger')
        return redirect(url_for('dashboard'))
    
    if post['author'] != session['user']:
        flash('No tienes permisos para editar este post', 'danger')
        return redirect(url_for('dashboard'))
    
    form = PostForm()
    if form.validate_on_submit():
        # Procesar nueva imagen si se subió
        if form.image.data:
            image_filename = save_image(form.image.data)
            if image_filename:
                post['image'] = image_filename
        
        post['title'] = form.title.data
        post['content'] = form.content.data
        post['category'] = form.category.data
        flash('¡Post actualizado exitosamente!', 'success')
        return redirect(url_for('dashboard'))
    
    # Llenar el formulario con datos existentes
    elif request.method == 'GET':
        form.title.data = post['title']
        form.content.data = post['content']
        form.category.data = post['category']
    
    return render_template('edit_post.html', form=form, post=post)

@app.route('/admin/delete/<int:post_id>')
def delete_post(post_id):
    if 'user' not in session:
        flash('Debes iniciar sesión para eliminar posts', 'warning')
        return redirect(url_for('login'))
    
    post = next((p for p in blog_posts if p['id'] == post_id), None)
    if not post:
        flash('El post no existe', 'danger')
        return redirect(url_for('dashboard'))
    
    if post['author'] != session['user']:
        flash('No tienes permisos para eliminar este post', 'danger')
        return redirect(url_for('dashboard'))
    
    blog_posts.remove(post)
    flash('¡Post eliminado exitosamente!', 'success')
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True)