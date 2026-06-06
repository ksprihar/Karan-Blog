from __future__ import annotations
from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import String, Integer, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from flask_bootstrap import Bootstrap5
from flask_ckeditor import CKEditor
from datetime import datetime
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from typing import List
from hashlib import md5
import smtplib
import os
from dotenv import load_dotenv

from forms import *

load_dotenv()
my_email = os.environ.get('EMAIL')
password = os.environ.get('PASSWORD')

class Base(DeclarativeBase):
    pass

def send_email(name, email, phone, message):
    with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
        smtp.starttls()
        smtp.login(my_email, password)
        smtp.sendmail(
            from_addr=my_email,
            to_addrs=my_email,
            msg=f"Subject:New form entry by {name}\n\n"
                f"Name: {name}\nEmail: {email}\nPhone: {phone}\nMessage: {message}"
        )

def email_exists(email):
    return email in db.session.execute(db.select(User.email)).scalars().all()

def admin_only(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if current_user.is_authenticated and current_user.id == 1:
            return func(*args, **kwargs)
        else:
            abort(403)
    return wrapper


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DB_URI", "sqlite:///posts.db")
app.config['SECRET_KEY'] = os.environ.get('FLASK_KEY')
db = SQLAlchemy(app, model_class=Base)
bootstrap = Bootstrap5(app)
ckeditor = CKEditor(app)
login_manager = LoginManager(app)

class User(db.Model, UserMixin):
    __tablename__ = 'user_table'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(250))
    password: Mapped[str] = mapped_column(String(100), nullable=False)
    posts: Mapped[List["Post"]] = relationship("Post", back_populates="author")
    comments: Mapped[List["Comment"]] = relationship("Comment", back_populates="user")

    def avatar(self):
        digest = md5(self.email.lower().encode("utf-8")).hexdigest()
        return f"https://www.gravatar.com/avatar/{digest}?d=identicon&s=128"

class Post(db.Model):
    __tablename__ = 'post_table'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    date: Mapped[str] = mapped_column(String(100), nullable=False)
    body: Mapped[str] = mapped_column(String, nullable=False)
    author: Mapped["User"] = relationship("User", back_populates="posts")
    img_url: Mapped[str] = mapped_column(String(500), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(250), nullable=False)
    author_id: Mapped[int] = mapped_column(Integer, ForeignKey('user_table.id'))
    comments: Mapped[List["Comment"]] = relationship("Comment", back_populates="post")

class Comment(db.Model):
    __tablename__ = 'comment_table'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    comment: Mapped[str] = mapped_column(String(1000), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey('user_table.id'))
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey('post_table.id'))
    user: Mapped["User"] = relationship("User", back_populates="comments")
    post: Mapped["Post"] = relationship("Post", back_populates="comments")


with app.app_context():
    db.create_all()

@login_manager.user_loader
def load_user(user_id):
    return db.session.execute(db.select(User).where(User.id == int(user_id))).scalar()


@app.route('/')
def home():
    posts = Post.query.all()
    return render_template('index.html', posts=posts)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact', methods=['POST', 'GET'])
def contact():
    if request.method == 'POST':
        if not current_user.is_authenticated:
            flash("You need to be logged in to contact me.")
            return redirect(url_for('login'))
        else:
            name = request.form['name']
            email = request.form['email']
            message = request.form['message']
            phone = request.form['phone']
            heading = f"{name.split()[0].title()}, your message has been submitted."
            send_email(name, email, phone, message)
            return render_template('contact.html', heading=heading)
    elif request.method == 'GET':
        heading = "Contact Me"
        return render_template('contact.html', heading=heading)

@app.route('/post/<int:post_id>', methods=['POST', 'GET'])
def post(post_id):
    post = db.get_or_404(Post, post_id)
    form = CommentForm()
    if form.validate_on_submit():
        if not current_user.is_authenticated:
            flash("You need to be logged in to post comments.")
            return redirect(url_for('login'))
        else:
            new_comment = Comment(
                comment=form.comment.data,
                post_id=post_id,
                user=current_user,
            )
            db.session.add(new_comment)
            db.session.commit()
            return redirect(url_for('post', post_id=post_id))
    return render_template('post.html', post=post, form=form)

@app.route('/new-post', methods=['POST', 'GET'])
@admin_only
def new_post():
    form = PostForm()
    if form.validate_on_submit():
        new_post = Post(
            title=form.title.data,
            body=form.body.data,
            author=current_user,
            img_url=form.img_url.data,
            subtitle=form.subtitle.data,
            date=datetime.now().strftime('%B %d, %Y'),
        )
        db.session.add(new_post)
        db.session.commit()
        return redirect(url_for('home'))
    heading = "New Post"
    return render_template('make_post.html', form=form, heading=heading)

@app.route('/edit-post/<int:post_id>', methods=['POST', 'GET'])
@admin_only
def edit_post(post_id):
    post = db.get_or_404(Post, post_id)
    form = PostForm(
        title=post.title,
        subtitle=post.subtitle,
        img_url=post.img_url,
        body=post.body,
    )
    if form.validate_on_submit():
        post.title = form.title.data
        post.subtitle = form.subtitle.data
        post.img_url = form.img_url.data
        post.body = form.body.data
        db.session.commit()
        return redirect(url_for('post', post_id=post_id))
    heading = "Edit Post"
    return render_template('make_post.html', form=form, heading=heading)

@app.route('/delete-post/<int:post_id>')
@admin_only
def delete_post(post_id):
    post = db.get_or_404(Post, post_id)
    db.session.delete(post)
    db.session.commit()
    return redirect(url_for('home'))

@app.route('/register', methods=['POST', 'GET'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        if not email_exists(form.email.data):
            hashed_password = generate_password_hash(
                password=form.password.data,
                method='pbkdf2:sha256:1000000',
                salt_length=16,
            )
            new_user = User(
                name=form.name.data,
                email=form.email.data,
                password=hashed_password,
            )
            db.session.add(new_user)
            db.session.commit()
            login_user(new_user)
            return redirect(url_for('home'))
        else:
            flash("Email already registered. Login instead.")
            return redirect(url_for('login'))

    return render_template('register.html', form=form)

@app.route('/login', methods=['POST', 'GET'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        if email_exists(form.email.data):
            user = db.session.execute(db.select(User).where(User.email == form.email.data)).scalar()
            if check_password_hash(user.password, form.password.data):
                login_user(user)
                return redirect(url_for('home'))
            else:
                flash("Incorrect password.")
                return redirect(url_for('login'))
        else:
            flash("Email doesn't exist.")
            return redirect(url_for('login'))
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))



if __name__ == '__main__':
    app.run(debug=False)
