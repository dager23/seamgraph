"""Flask app for testing."""

import os

from flask import Flask, redirect, render_template, url_for

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev")
DATABASE_URL = os.environ["DATABASE_URL"]


@app.route("/")
def index():
    return render_template("index.html", title="Home")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact", methods=["GET", "POST"])
def contact():
    return render_template("contact.html")


@app.route("/go-home")
def go_home():
    return redirect(url_for("index"))
