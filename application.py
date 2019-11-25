import os
import requests

from flask import Flask, session, render_template, request, redirect, jsonify, url_for, abort
from flask_session import Session
from tempfile import mkdtemp
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from werkzeug.security import check_password_hash, generate_password_hash
from helpers import login_required
from flask_paginate import Pagination, get_page_args

app = Flask(__name__)

# Check for environment variable
if not os.getenv("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL is not set")

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

#Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Set up database
engine = create_engine(os.getenv("DATABASE_URL"))
db = scoped_session(sessionmaker(bind=engine))

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    '''Register user'''
    if request.method == "GET":
        return render_template("register.html")
    else:
        username = request.form.get("username")

        # Make sure username doesn't exist
        if db.execute("SELECT * FROM users WHERE username = :username", {"username": username}).rowcount != 0:
            return render_template("error.html", message="This username already exists")

        # Make sure password and confirmation are matching

        if request.form.get("password") != request.form.get("confirmation"):
            return render_template("error.html", message="Password and confirmation are not matching")

        hash_pass = generate_password_hash(request.form.get("password"), method='pbkdf2:sha256', salt_length=8)

        db.execute("INSERT INTO users (username, hash) VALUES (:username, :hash)",
                {"username": username, "hash": hash_pass})
        db.commit()
        session["user_id"] = db.execute("SELECT id FROM users WHERE username = :username",
                {"username": username}).fetchone()
        return redirect(url_for('search', username = username))

@app.route("/login", methods=["GET", "POST"])
def login():
    '''Log user in'''

    if request.method == "GET":
        return render_template("login.html")

    else:
        # Forget any user login
        session.clear()

        # Check if the field Username was filled
        if not request.form.get("username"):
            return render_template("error.html", message="Please enter username")

        # Check if the field Password was filled
        if not request.form.get("password"):
            return render_template("error.html", message="Please enter password")

        # Get the number of rows from users table containing such username
        username = request.form.get("username")
        check_user = db.execute("SELECT user FROM users WHERE username = :username",
                               {"username": username}).rowcount

        # Check whether username and password are correct
        hashed_pass = db.execute("SELECT hash FROM users WHERE username = :username",
                         {"username": username}).fetchone()
        password = request.form.get("password")
        if check_user != 1 or not check_password_hash(hashed_pass[0], password):
            return render_template("error.html", message="Invalid username and/or password")

        session["user_id"] = db.execute("SELECT id FROM users WHERE username = :username",
                {"username": username}).fetchone()

        return redirect(url_for('search', username = username))


@app.route("/search/<username>", methods=["GET", "POST"])
def search(username):
    """Search for results that match query"""

    if request.method == "GET":
        return render_template("search.html", username = username)
    else:
        searching = request.form.get("searching") + "%"
        return redirect(url_for('search_results', username = username, searching=searching))


@app.route("/search_results/<username>/<searching>", methods=["GET", "POST"])
@app.route("/search_results/<username>", methods=["GET", "POST"])
def search_results(username, searching):
    """Let user input a query and get results"""

    # Get from the database results matching the query
    result = db.execute("SELECT * FROM books WHERE isbn ILIKE :searching OR title ILIKE :searching OR author ILIKE :searching",
                      {"searching": searching}).fetchall()
    # Check if there are any matching results, if not - return error message
    if db.execute("SELECT * FROM books WHERE isbn ILIKE :searching OR title ILIKE :searching OR author ILIKE :searching",
                    {"searching": searching}).rowcount == 0:
        return render_template("error.html", message="Sorry, no such book", username=username)

    # Convert the results into dictionary
    rows = [dict(row) for row in result]

    # Add pagination for more comfortable rendering of the Results
    # From this demo:  https://gist.github.com/mozillazg/69fb40067ae6d80386e10e105e6803c9
    page, per_page, offset = get_page_args(page_parameter='page',
                                      per_page_parameter='per_page')
    total = len(rows)
    pagination_rows = get_rows(rows, offset=offset, per_page=per_page)

    pagination = Pagination(page=page, per_page=per_page, total=total,
                        css_framework='bootstrap4')
    return render_template('search_results.html', username = username,
                       rows=pagination_rows,
                       page=page,
                       per_page=per_page,
                       pagination=pagination,
                       )


@app.route("/book_page/<username>/<book_isbn>", methods=["GET", "POST"])
def book_page(username, book_isbn):
    """Display the details of the book and users' reviews"""

    # Get from the database details of chosen books
    book_details = db.execute("SELECT * FROM books WHERE isbn = :book_isbn",
                      {"book_isbn": book_isbn}).fetchone()
    if not book_details:
        return render_template("error.html", message="Sorry, error. Try one more time.")

    res = requests.get("https://www.goodreads.com/book/review_counts.json", params={"key": "ZCJ8HzIYKbDhCMhNts2RQ", "isbns": book_isbn})
    data = res.json()
    gd_rate = data['books'][0]
    # Get from the database book reviews from site users
    reviews = db.execute("SELECT username, review, rating FROM reviews WHERE isbn = :book_isbn",
                      {"book_isbn": book_isbn}).fetchall()
    # Convert them into dictionary
    rend_reviews = [dict(rend_review) for rend_review in reviews]

    rev_form = db.execute("SELECT * FROM reviews WHERE isbn = :book_isbn and username = :username",
                 {"book_isbn": book_isbn, "username": username}).rowcount

    # Add pagination for more comfortable rendering of book reviews
    # From this demo:  https://gist.github.com/mozillazg/69fb40067ae6d80386e10e105e6803c9
    page, per_page, offset = get_page_args(page_parameter='page',
                                         per_page_parameter='per_page')
    total = len(rend_reviews)
    pagination_reviews = get_rows(reviews, offset=offset, per_page=per_page)

    pagination = Pagination(page=page, per_page=per_page, total=total,
                        css_framework='bootstrap3')

    if request.method == "POST":
        new_review = request.form.get("review")
        new_rating = request.form.get("rating")
        db.execute("INSERT INTO reviews (isbn, username, review, rating) VALUES (:isbn, :username, :review, :rating)",
                {"isbn": book_isbn, "username": username, "review": new_review, "rating": new_rating})
        db.commit()
        return redirect(url_for('book_page', username = username, book_isbn=book_isbn))

    return render_template("book_page.html", username = username, book_details = book_details, gd_rate = gd_rate,
                           rev_form = rev_form,
                           rend_reviews = pagination_reviews,
                           book_isbn = book_isbn,
                           page=page,
                           per_page=per_page,
                           pagination=pagination,
                           )

@app.route("/logout")
def logout():
    '''Log user out'''

    # Forget any user login
    session.clear()
    return redirect("/")

def get_rows(rows, offset=0, per_page=10):
    return rows[offset: offset + per_page]

@app.route("/api/<isbn>")
def api(isbn):

    # Make sure isbn exists
    if isbn is None:
        return jsonify({"error": "No isbn"}), 404

    # Get book details
    details = db.execute("SELECT books.title, books.author,books.year, books.isbn, COUNT(reviews.rating), AVG(reviews.rating) FROM books JOIN reviews ON books.isbn = reviews.isbn WHERE books.isbn = :isbn GROUP BY books.title, books.author, books.year, books.isbn",
                         {"isbn": isbn}).fetchone()
    if not details:
        return jsonify({"error": "Not found"}), 404

    if details[4] == 0:
        review_count = 0
        average_score = 0
    else:
        review_count = details[4]
        average_score = float(details[5])

    rend_details = {
        "title": details[0],
        "author": details[1],
        "year": details[2],
        "isbn": details[3],
        "review_count": review_count,
        "average_score": average_score
    }

    return jsonify(rend_details)
