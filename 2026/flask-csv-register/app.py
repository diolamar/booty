import csv
from datetime import datetime
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, url_for

app = Flask(__name__)
app.config["SECRET_KEY"] = "sample_csv_secret_key"

BASE_DIR = Path(__file__).resolve().parent
CSV_FILE = BASE_DIR / "registrations.csv"


def ensure_csv_file():
    if not CSV_FILE.exists():
        with CSV_FILE.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["full_name", "email", "phone", "registered_at"])


def save_registration(full_name, email, phone):
    ensure_csv_file()
    with CSV_FILE.open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow([full_name, email, phone, datetime.now().isoformat(timespec="seconds")])


@app.route("/", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()

        if not full_name or not email or not phone:
            flash("Please fill in all fields.", "danger")
            return render_template("register.html")

        save_registration(full_name, email, phone)
        flash("Registration saved to CSV successfully.", "success")
        return redirect(url_for("register"))

    return render_template("register.html")


@app.route("/registrations")
def registrations():
    ensure_csv_file()
    with CSV_FILE.open("r", newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        rows = list(reader)
    return render_template("registrations.html", rows=rows)


if __name__ == "__main__":
    ensure_csv_file()
    app.run(debug=True)
