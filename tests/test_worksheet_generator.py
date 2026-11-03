import json
import os
import unittest
from unittest.mock import patch

from worksheet_generator import (
    ProviderError,
    ValidationError,
    _normalize_questions,
    _parse_json,
    generation_context,
    generate_worksheet,
    validate_request,
)


def valid_request(**overrides):
    data = {
        "subject": "Mathematics",
        "grade": "Grade 6",
        "topic": "Fractions",
        "difficulty": "Medium",
        "question_count": 2,
        "question_types": ["short_answer"],
        "language": "en",
        "include_answer_key": True,
        "additional_instructions": "",
    }
    data.update(overrides)
    return data


class RequestValidationTests(unittest.TestCase):
    def test_normalizes_question_count(self):
        validated = validate_request(valid_request(question_count="3"))
        self.assertEqual(validated["question_count"], 3)

    def test_rejects_question_count_above_limit(self):
        with self.assertRaises(ValidationError):
            validate_request(valid_request(question_count=21))

    def test_rejects_empty_question_types(self):
        with self.assertRaises(ValidationError):
            validate_request(valid_request(question_types=[]))

    def test_requires_custom_subject(self):
        with self.assertRaises(ValidationError):
            validate_request(valid_request(subject="Other", other_subject=""))

    def test_rejects_long_instructions(self):
        with self.assertRaises(ValidationError):
            validate_request(valid_request(additional_instructions="x" * 801))

    def test_generation_context_keeps_normalized_settings_and_ai_prompt(self):
        context = generation_context(valid_request())
        self.assertEqual(context["settings"]["question_count"], 2)
        self.assertEqual(json.loads(context["prompt"])["topic"], "Fractions")
        self.assertEqual(json.loads(context["prompt"])["question_types"][0]["id"], "short_answer")
        self.assertIn("age-appropriate educational worksheets", context["system_instruction"])


class AIResponseTests(unittest.TestCase):
    def test_parses_json_fence(self):
        self.assertEqual(_parse_json('```json\n{"title":"A"}\n```'), {"title": "A"})

    def test_rejects_malformed_json(self):
        with self.assertRaises(ProviderError):
            _parse_json("not JSON")

    def test_rejects_duplicate_questions(self):
        question = {
            "type": "short_answer",
            "question": "Name a fraction.",
            "options": [],
            "pairs": [],
            "answer": "One half",
            "explanation": "",
            "points": 1,
        }
        with self.assertRaises(ProviderError):
            _normalize_questions([question, {**question, "question": "Name a fraction!"}], ["short_answer"], 2, True)

    def test_missing_api_key_is_not_demo_generation(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            with self.assertRaisesRegex(ProviderError, "GEMINI_API_KEY"):
                generate_worksheet(valid_request())


if __name__ == "__main__":
    unittest.main()