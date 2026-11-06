from datetime import datetime
from flask import Flask, jsonify, request, render_template

from main import (
    convert_time,
    convert_to_12_hour,
    ensure_city_database,
    get_city_by_id,
    get_random_cities,
    search_cities,
    validate_local_time,
)


app = Flask(__name__)

# Load the worldwide city catalogue once when the application starts.
CITY_DATABASE_ERROR = None
try:
    ensure_city_database()
except Exception:
    app.logger.exception("The GeoNames city catalogue could not be initialized.")
    CITY_DATABASE_ERROR = (
        "The worldwide city catalogue could not be loaded. "
        "Check your internet connection and restart the application."
    )


def render_converter(**context):
    """Render the page with consistent defaults and any submitted form values."""
    page_context = {
        "error": None,
        "database_error": CITY_DATABASE_ERROR,
        "old_city": None,
        "new_city": None,
        "time_value": "12:30",
        "date_value": "",
    }
    page_context.update(context)
    return render_template("index.html", **page_context)


@app.get("/api/cities")
def city_search_api():
    """Return four random suggestions or search results for a typed query."""
    if CITY_DATABASE_ERROR:
        return jsonify({"error": CITY_DATABASE_ERROR}), 503

    query = request.args.get("q", "").strip()

    try:
        if not query:
            return jsonify(get_random_cities(limit=4))

        if len(query) < 2:
            return jsonify([])

        return jsonify(search_cities(query, limit=50))
    except Exception:
        app.logger.exception("City search failed.")
        return jsonify({"error": "City search is temporarily unavailable."}), 500


@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "GET":
        return render_converter()

    # Resolve the submitted GeoNames IDs to trusted city records.
    old_city = get_city_by_id(request.form.get("old"))
    new_city = get_city_by_id(request.form.get("new"))

    time_input = request.form.get("currtime", "")
    date_input = request.form.get("selected_date", "")

    def show_error(message):
        return render_converter(
            error=message,
            old_city=old_city,
            new_city=new_city,
            time_value=time_input or "12:30",
            date_value=date_input,
        )

    if not old_city or not new_city:
        return show_error("Please select a valid city for both timezones.")

    if not time_input:
        return show_error("Please enter a time.")

    try:
        hours, minutes = map(int, time_input.split(":"))
        if not (0 <= hours <= 23 and 0 <= minutes <= 59):
            raise ValueError
    except (ValueError, AttributeError):
        return show_error("Invalid time. Please enter a valid 24-hour time.")

    try:
        selected_date = datetime.strptime(date_input, "%Y-%m-%d").date()
        if not (1900 <= selected_date.year <= 2100):
            return show_error("Please select a date between 1900 and 2100.")
    except (ValueError, TypeError):
        return show_error("Invalid date.")

    is_valid, error_message = validate_local_time(
        selected_date,
        hours,
        minutes,
        old_city["timezone"],
    )

    if not is_valid:
        return show_error(error_message)

    converted_date, converted_hour, converted_minute = convert_time(
        hours,
        minutes,
        old_city["timezone"],
        new_city["timezone"],
        selected_date,
    )

    return render_converter(
        oldtime=convert_to_12_hour(hours, minutes),
        newtime=convert_to_12_hour(converted_hour, converted_minute),
        TZA=old_city["label"],
        TZB=new_city["label"],
        date0=selected_date.strftime("%B %d, %Y"),
        date1=converted_date.strftime("%B %d, %Y"),
        old_city=old_city,
        new_city=new_city,
        time_value=time_input,
        date_value=date_input,
    )


if __name__ == "__main__":
    app.run(debug=True)
