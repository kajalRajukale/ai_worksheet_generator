import io
import os
import sqlite3

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge

from pdf_export import PDFError, generate_pdf
from worksheet_generator import (
    ProviderError,
    ValidationError,
    generation_context,
    generate_worksheet,
    validate_worksheet_document,
)
from worksheet_store import create_worksheet, get_worksheet, list_worksheets, update_worksheet


load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
app.config["WORKSHEET_DB_PATH"] = os.getenv(
    "WORKSHEET_DB_PATH",
    os.path.join(app.instance_path, "worksheets.sqlite3"),
)


@app.after_request
def add_response_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.errorhandler(RequestEntityTooLarge)
def request_too_large(_error):
    return jsonify({"error": "The request is too large. Reduce the worksheet details and try again."}), 413


@app.errorhandler(sqlite3.Error)
def worksheet_database_error(_error):
    app.logger.exception("The local worksheet database operation failed.")
    return jsonify({"error": "The local worksheet database is unavailable. Check its file and permissions."}), 503


@app.get("/")
def home():
    return render_template("index.html")


@app.post("/api/generate")
def generate():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send the worksheet details as JSON."}), 400
    try:
        worksheet = generate_worksheet(payload)
        context = generation_context(payload)
    except ValidationError as error:
        return jsonify({"error": str(error)}), 400
    except ProviderError as error:
        return jsonify({"error": str(error)}), error.status_code
    saved = create_worksheet(
        app.config["WORKSHEET_DB_PATH"],
        worksheet,
        context["settings"],
        context["prompt"],
        context["system_instruction"],
    )
    return jsonify({"id": saved["id"], "worksheet": worksheet})


@app.get("/api/worksheets")
def worksheets():
    search = request.args.get("q", "").strip()
    if len(search) > 120:
        return jsonify({"error": "Search text must be 120 characters or fewer."}), 400
    return jsonify(
        {"worksheets": list_worksheets(app.config["WORKSHEET_DB_PATH"], search)}
    )


@app.get("/api/worksheets/<int:worksheet_id>")
def worksheet_detail(worksheet_id):
    saved = get_worksheet(app.config["WORKSHEET_DB_PATH"], worksheet_id)
    if saved is None:
        return jsonify({"error": "Worksheet not found."}), 404
    return jsonify(saved)


@app.put("/api/worksheets/<int:worksheet_id>")
def save_worksheet(worksheet_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send worksheet data as JSON."}), 400
    try:
        worksheet = validate_worksheet_document(payload.get("worksheet"))
    except ValidationError as error:
        return jsonify({"error": str(error)}), 400
    if not update_worksheet(app.config["WORKSHEET_DB_PATH"], worksheet_id, worksheet):
        return jsonify({"error": "Worksheet not found."}), 404
    return jsonify(get_worksheet(app.config["WORKSHEET_DB_PATH"], worksheet_id))


@app.post("/api/pdf")
def download_pdf():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send worksheet data as JSON."}), 400
    include_answer_key = payload.get("include_answer_key")
    if not isinstance(include_answer_key, bool):
        return jsonify({"error": "Choose whether this PDF should include the answer key."}), 400
    try:
        worksheet = validate_worksheet_document(payload.get("worksheet"))
        if include_answer_key and not worksheet["include_answer_key"]:
            raise ValidationError("This worksheet was generated without an answer key.")
        pdf_bytes = generate_pdf(worksheet, include_answer_key=include_answer_key)
    except ValidationError as error:
        return jsonify({"error": str(error)}), 400
    except PDFError as error:
        return jsonify({"error": str(error)}), 503
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name="ai-worksheet.pdf",
        max_age=0,
    )


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").casefold() == "true",
    )