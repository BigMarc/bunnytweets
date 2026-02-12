"""Title generator: manage categories and titles for auto-posting."""

from flask import (
    Blueprint, render_template, request, flash, redirect, url_for,
    current_app, jsonify,
)

bp = Blueprint("generator", __name__)


@bp.route("/")
def index():
    state = current_app.config["APP_STATE"]
    categories = state.db.get_all_categories()

    # Build a list of dicts with category info + title count
    cat_data = []
    for cat in categories:
        titles = state.db.get_titles_by_category(cat.id)
        cat_data.append({
            "id": cat.id,
            "name": cat.name,
            "titles": [{"id": t.id, "text": t.text} for t in titles],
            "count": len(titles),
        })

    return render_template("generator.html", categories=cat_data)


@bp.route("/category/add", methods=["POST"])
def add_category():
    state = current_app.config["APP_STATE"]
    name = request.form.get("name", "").strip()
    if not name:
        flash("Category name is required.", "danger")
        return redirect(url_for("generator.index"))

    existing = state.db.get_category_by_name(name)
    if existing:
        flash(f"Category '{name}' already exists.", "warning")
        return redirect(url_for("generator.index"))

    state.db.add_category(name)
    flash(f"Category '{name}' added!", "success")
    return redirect(url_for("generator.index"))


@bp.route("/category/<int:cat_id>/delete", methods=["POST"])
def delete_category(cat_id):
    state = current_app.config["APP_STATE"]
    cat = state.db.get_category(cat_id)
    if not cat:
        return jsonify({"success": False, "message": "Category not found"})
    if cat.name in ("Global",):
        return jsonify({"success": False, "message": "Cannot delete the Global category"})
    state.db.delete_category(cat_id)
    return jsonify({"success": True, "message": f"Category '{cat.name}' deleted"})


@bp.route("/title/add", methods=["POST"])
def add_title():
    state = current_app.config["APP_STATE"]
    text = request.form.get("text", "").strip()
    category_id = request.form.get("category_id", "")

    if not text:
        flash("Title text is required.", "danger")
        return redirect(url_for("generator.index"))

    if not category_id:
        flash("Please select a category.", "danger")
        return redirect(url_for("generator.index"))

    state.db.add_title(text, int(category_id))
    flash("Title added!", "success")
    return redirect(url_for("generator.index"))


@bp.route("/title/<int:title_id>/delete", methods=["POST"])
def delete_title(title_id):
    state = current_app.config["APP_STATE"]
    ok = state.db.delete_title(title_id)
    if ok:
        return jsonify({"success": True, "message": "Title deleted"})
    return jsonify({"success": False, "message": "Title not found"})


@bp.route("/api/titles", methods=["GET"])
def api_titles():
    """JSON endpoint: all categories with their titles."""
    state = current_app.config["APP_STATE"]
    categories = state.db.get_all_categories()
    result = []
    for cat in categories:
        titles = state.db.get_titles_by_category(cat.id)
        result.append({
            "id": cat.id,
            "name": cat.name,
            "titles": [{"id": t.id, "text": t.text} for t in titles],
        })
    return jsonify(result)
