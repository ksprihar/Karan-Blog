from __future__ import annotations
import os
import smtplib
import time
import requests
from datetime import datetime
from functools import wraps
from typing import List
from hashlib import md5

# --- Environment Variables ---
from dotenv import load_dotenv

load_dotenv()  # Loads variables from .env into os.environ

# Flask and Web Extensions
from flask import Flask, render_template, request, redirect, url_for, flash, abort, session
from flask_bootstrap import Bootstrap5
from flask_ckeditor import CKEditor
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# Database
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import String, Integer, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Local Imports
from forms import PostForm, RegisterForm, LoginForm, CommentForm

# --- Configuration ---
MY_EMAIL = os.environ.get('EMAIL')
EMAIL_PASSWORD = os.environ.get('PASSWORD')
TURNSTILE_SECRET_KEY = os.environ.get('TURNSTILE_SECRET_KEY')


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""
    pass


# --- Application Initialization ---
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DB_URI", "sqlite:///posts.db")
app.config['SECRET_KEY'] = os.environ.get('FLASK_KEY')

db = SQLAlchemy(app, model_class=Base)
bootstrap = Bootstrap5(app)
ckeditor = CKEditor(app)
login_manager = LoginManager(app)


# --- Database Models ---

class User(db.Model, UserMixin):
    """Stores user account information and links to their posts and comments."""
    __tablename__ = 'user_table'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(250))
    password: Mapped[str] = mapped_column(String(500), nullable=False)

    # Relationships
    posts: Mapped[List["Post"]] = relationship("Post", back_populates="author")
    comments: Mapped[List["Comment"]] = relationship("Comment", back_populates="user")

    def avatar(self):
        """Generates a Gravatar profile image URL based on the user's email."""
        digest = md5(self.email.lower().encode("utf-8")).hexdigest()
        return f"https://www.gravatar.com/avatar/{digest}?d=identicon&s=128"


class Post(db.Model):
    """Stores individual blog posts."""
    __tablename__ = 'post_table'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    subtitle: Mapped[str] = mapped_column(String(250), nullable=False)
    date: Mapped[str] = mapped_column(String(100), nullable=False)
    body: Mapped[str] = mapped_column(String, nullable=False)
    img_url: Mapped[str] = mapped_column(String(500), nullable=False)

    # Relationships
    author_id: Mapped[int] = mapped_column(Integer, ForeignKey('user_table.id'))
    author: Mapped["User"] = relationship("User", back_populates="posts")
    comments: Mapped[List["Comment"]] = relationship("Comment", back_populates="post")


class Comment(db.Model):
    """Stores comments made on blog posts by users."""
    __tablename__ = 'comment_table'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    comment: Mapped[str] = mapped_column(String(1000), nullable=False)

    # Relationships
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey('user_table.id'))
    user: Mapped["User"] = relationship("User", back_populates="comments")
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey('post_table.id'))
    post: Mapped["Post"] = relationship("Post", back_populates="comments")


# Create tables if they don't exist
with app.app_context():
    db.create_all()


# --- Helper Functions & Decorators ---

@login_manager.user_loader
def load_user(user_id):
    """Required by Flask-Login to load a user object from the session."""
    return db.session.execute(db.select(User).where(User.id == int(user_id))).scalar()


def send_email(name, email, phone, message):
    """Sends a notification email when the contact form is submitted."""
    with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
        smtp.starttls()
        smtp.login(MY_EMAIL, EMAIL_PASSWORD)
        smtp.sendmail(
            from_addr=MY_EMAIL,
            to_addrs=MY_EMAIL,
            msg=f"Subject:New form entry by {name}\n\n"
                f"Name: {name}\nEmail: {email}\nPhone: {phone}\nMessage: {message}"
        )


def email_exists(email):
    """Checks the database to see if an email address is already registered."""
    return email in db.session.execute(db.select(User.email)).scalars().all()


def admin_only(func):
    """Custom decorator to restrict route access to the admin (User ID 1)."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        if current_user.is_authenticated and current_user.id == 1:
            return func(*args, **kwargs)
        else:
            abort(403)  # Forbidden

    return wrapper


# --- Routes ---

@app.route('/')
def home():
    """Displays all blog posts on the home page."""
    # Updated to SQLAlchemy 2.0 syntax
    posts = db.session.scalars(db.select(Post)).all()
    return render_template('index.html', posts=posts)


@app.route('/about')
def about():
    """Displays the about page."""
    return render_template('about.html')


@app.route('/contact', methods=['POST', 'GET'])
def contact():
    """Handles the contact form rendering and submission."""
    if request.method == 'POST':
        # Require users to be logged in to send a message
        if not current_user.is_authenticated:
            flash("You need to be logged in to contact me.")
            return redirect(url_for('login'))

        # Bot-checks
        # 1. Time based Validation
        start_time = session.get('contact_form_start_time', 0)
        time_taken = time.time() - start_time

        if time_taken < 3.0:
            flash("Form submitted too quickly. Please take your time.")
            return redirect(url_for('contact'))

        # Bot-checks
        # 2. Cloudflare Turnstile
        # Get the hidden token Cloudflare injects into your form
        turnstile_token = request.form.get('cf-turnstile-response')

        # Verify that token with Cloudflare's API
        verify_url = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
        cf_data = {
            'secret': TURNSTILE_SECRET_KEY,
            'response': turnstile_token,
            'remoteip': request.remote_addr
        }
        cf_response = requests.post(verify_url, data=cf_data).json()

        if not cf_response['success']:
            flash("Bot validation failed. Please try again.")
            return redirect(url_for('contact'))

        # Process the form data
        name = request.form['name']
        email = request.form['email']
        message = request.form['message']
        phone = request.form['phone']

        send_email(name, email, phone, message)

        heading = f"{name.split()[0].title()}, your message has been submitted."
        return render_template('contact.html', heading=heading)

    # Render default GET request
    # Record the exact timestamp the page was loaded into the user's secure session
    session['contact_form_start_time'] = time.time()

    # Load Turnstile site key to pass to the webpage
    site_key = os.environ.get('TURNSTILE_SITE_KEY')
    return render_template('contact.html', heading="Contact Me", site_key=site_key)


@app.route('/post/<int:post_id>', methods=['POST', 'GET'])
def post(post_id):
    """Displays a single blog post and handles new comments."""
    post_item = db.get_or_404(Post, post_id)
    form = CommentForm()

    if form.validate_on_submit():
        if not current_user.is_authenticated:
            flash("You need to be logged in to post comments.")
            return redirect(url_for('login'))

        new_comment = Comment(
            comment=form.comment.data,
            post_id=post_id,
            user=current_user,
        )
        db.session.add(new_comment)
        db.session.commit()
        return redirect(url_for('post', post_id=post_id))

    return render_template('post.html', post=post_item, form=form)


@app.route('/new-post', methods=['POST', 'GET'])
@admin_only
def new_post():
    """Allows the admin to create a new blog post."""
    form = PostForm()
    if form.validate_on_submit():
        new_post_item = Post(
            title=form.title.data,
            body=form.body.data,
            author=current_user,
            img_url=form.img_url.data,
            subtitle=form.subtitle.data,
            date=datetime.now().strftime('%B %d, %Y'),
        )
        db.session.add(new_post_item)
        db.session.commit()
        return redirect(url_for('home'))

    heading = "New Post"
    return render_template('make_post.html', form=form, heading=heading)


@app.route('/edit-post/<int:post_id>', methods=['POST', 'GET'])
@admin_only
def edit_post(post_id):
    """Allows the admin to edit an existing blog post."""
    post_item = db.get_or_404(Post, post_id)
    form = PostForm(
        title=post_item.title,
        subtitle=post_item.subtitle,
        img_url=post_item.img_url,
        body=post_item.body,
    )

    if form.validate_on_submit():
        post_item.title = form.title.data
        post_item.subtitle = form.subtitle.data
        post_item.img_url = form.img_url.data
        post_item.body = form.body.data
        db.session.commit()
        return redirect(url_for('post', post_id=post_id))

    heading = "Edit Post"
    return render_template('make_post.html', form=form, heading=heading)


@app.route('/delete-post/<int:post_id>')
@admin_only
def delete_post(post_id):
    """Allows the admin to delete a blog post."""
    post_item = db.get_or_404(Post, post_id)
    db.session.delete(post_item)
    db.session.commit()
    return redirect(url_for('home'))


# --- User Authentication Routes ---

@app.route('/register', methods=['POST', 'GET'])
def register():
    """Handles new user registration."""
    form = RegisterForm()
    if form.validate_on_submit():
        if not email_exists(form.email.data):
            hashed_password = generate_password_hash(
                password=form.password.data,
                method='pbkdf2:sha256:1000000',  # Secure hashing algorithm
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
    """Handles existing user login."""
    form = LoginForm()
    if form.validate_on_submit():
        if email_exists(form.email.data):
            user = db.session.execute(db.select(User).where(User.email == form.email.data)).scalar()
            # Verify the hashed password matches the input
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
    """Logs out the current user."""
    logout_user()
    return redirect(url_for('home'))


if __name__ == '__main__':
    app.run(debug=False)