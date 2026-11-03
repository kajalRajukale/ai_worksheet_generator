import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app
from pdf_export import generate_pdf
from worksheet_generator import ProviderError


WINDOWS_FONTS = Path(os.getenv("WINDIR", r"C:\Windows")) / "Fonts"
HAS_DEVANAGARI_FONT = any(
    (WINDOWS_FONTS / filename).is_file()
    for filename in ("Nirmala.ttf", "NirmalaUI.ttf", "mangal.ttf")
)


def sample_worksheet():
    return {
        "title": "Fractions Practice",
        "instructions": "Show your work.",
        "subject": "Mathematics",
        "grade": "Grade 6",
        "topic": "Fractions",
        "difficulty": "Medium",
        "language": "en",
        "include_answer_key": True,
        "student_name": "",
        "questions": [
            {
                "type": "short_answer",
                "question": "What is one half of 8?",
                "options": [],
                "pairs": [],
                "answer": "4",
                "explanation": "8 divided by 2 is 4.",
                "points": 1,
            }
        ],
    }


def sample_generation_request():
    return {
        "subject": "Mathematics",
        "grade": "Grade 6",
        "topic": "Fractions",
        "difficulty": "Medium",
        "question_count": 1,
        "question_types": ["short_answer"],
        "language": "en",
        "include_answer_key": True,
        "additional_instructions": "Use classroom examples.",
    }


class AppRouteTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        app.config["WORKSHEET_DB_PATH"] = str(Path(self.temp_dir.name) / "worksheets.sqlite3")
        self.client = app.test_client()

    def test_homepage_loads(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Worksheet", response.data)

    def test_generate_rejects_non_json(self):
        response = self.client.post("/api/generate", data="not json", content_type="text/plain")
        self.assertEqual(response.status_code, 400)

    def test_generate_returns_provider_error(self):
        with patch("app.generate_worksheet", side_effect=ProviderError("Gemini is not configured.", 503)):
            response = self.client.post("/api/generate", json={"subject": "Science"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("Gemini is not configured", response.get_json()["error"])

    def test_generate_persists_worksheet_settings_and_ai_prompt(self):
        with patch("app.generate_worksheet", return_value=sample_worksheet()):
            response = self.client.post("/api/generate", json=sample_generation_request())

        self.assertEqual(response.status_code, 200)
        worksheet_id = response.get_json()["id"]
        details = self.client.get(f"/api/worksheets/{worksheet_id}").get_json()
        self.assertEqual(details["worksheet"]["title"], "Fractions Practice")
        self.assertEqual(details["generation_settings"]["question_count"], 1)
        self.assertEqual(details["generation_settings"]["topic"], "Fractions")
        self.assertIn("classroom examples", details["prompt"])
        self.assertIn("age-appropriate educational worksheets", details["system_instruction"])
        self.assertEqual(
            self.client.get("/api/worksheets?q=Fractions").get_json()["worksheets"][0]["id"],
            worksheet_id,
        )

    def test_saved_worksheet_edits_persist_without_changing_generation_metadata(self):
        with patch("app.generate_worksheet", return_value=sample_worksheet()):
            generated = self.client.post("/api/generate", json=sample_generation_request()).get_json()
        worksheet_id = generated["id"]
        edited = sample_worksheet()
        edited["title"] = "Fractions review"
        edited["questions"][0]["question"] = "What is half of 10?"
        edited["questions"][0]["answer"] = "5"

        response = self.client.put(
            f"/api/worksheets/{worksheet_id}", json={"worksheet": edited}
        )

        self.assertEqual(response.status_code, 200)
        reloaded = self.client.get(f"/api/worksheets/{worksheet_id}").get_json()
        self.assertEqual(reloaded["worksheet"]["title"], "Fractions review")
        self.assertEqual(reloaded["worksheet"]["questions"][0]["answer"], "5")
        self.assertEqual(reloaded["generation_settings"]["topic"], "Fractions")
        self.assertEqual(json.loads(reloaded["prompt"])["topic"], "Fractions")

    def test_worksheet_edit_rejects_invalid_document(self):
        response = self.client.put(
            "/api/worksheets/1", json={"worksheet": {"title": "Missing fields"}}
        )
        self.assertEqual(response.status_code, 400)

    def test_pdf_endpoint_returns_pdf(self):
        response = self.client.post(
            "/api/pdf",
            json={"worksheet": sample_worksheet(), "include_answer_key": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertTrue(response.data.startswith(b"%PDF"))

    def test_pdf_can_omit_answer_key(self):
        pdf_bytes = generate_pdf(sample_worksheet(), include_answer_key=False)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    @unittest.skipUnless(HAS_DEVANAGARI_FONT, "No supported Windows Devanagari font is installed.")
    def test_pdf_supports_hindi_and_marathi(self):
        with patch.dict(os.environ, {"WORKSHEET_UNICODE_FONT": ""}):
            for language in ("hi", "mr"):
                worksheet = sample_worksheet()
                worksheet["language"] = language
                worksheet["title"] = "भिन्नांचा सराव"
                worksheet["questions"][0]["question"] = "८ चा अर्धा किती?"
                self.assertTrue(generate_pdf(worksheet).startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()