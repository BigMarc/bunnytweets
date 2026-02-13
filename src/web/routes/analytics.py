"""Analytics dashboard route."""

from flask import Blueprint, render_template

bp = Blueprint("analytics", __name__)


@bp.route("/")
def index():
    return render_template("analytics.html")
