import json
import os
import re
from typing import Any

from google import genai
from google.genai import errors, types


QUESTION_TYPES = {
    "multiple_choice": "Multiple choice",
    "fill_blanks": "Fill in the blanks",
    "true_false": "True or false",
    "short_answer": "Short answer",
    "long_answer": "Long answer",
    "match_following": "Match the following",
}
LANGUAGES = {"en": "English", "hi": "Hindi", "mr": "Marathi"}
SUBJECTS = {
    "Mathematics",
    "Science",
    "English",
    "Computer Science",
    "Social Studies",
}
DIFFICULTIES = {"Easy", "Medium", "Hard"}
SYSTEM_INSTRUCTION = (
    "You create clear, age-appropriate educational worksheets. Generate distinct, accurate questions "
    "for the requested grade and topic, in the requested language. Distribute the requested question "
    "types across the worksheet. Include concise answer keys and explanations only when requested. "
    "Return data matching the supplied JSON schema. Do not include markdown."
)


class ValidationError(ValueError):
    pass


class ProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


def _text(value: Any, label: str, maximum: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be text.")
    value = value.strip()
    if required and not value:
        raise ValidationError(f"{label} is required.")
    if len(value) > maximum:
        raise ValidationError(f"{label} must be {maximum} characters or fewer.")
    return value


def validate_request(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValidationError("The worksheet request must be a JSON object.")

    subject = _text(data.get("subject"), "Subject", 80)
    if subject == "Other":
        subject = _text(data.get("other_subject"), "Custom subject", 80)
    grade = _text(data.get("grade"), "Class or grade", 40)
    topic = _text(data.get("topic"), "Topic", 160)
    difficulty = data.get("difficulty")
    if difficulty not in DIFFICULTIES:
        raise ValidationError("Choose Easy, Medium, or Hard difficulty.")

    count_value = data.get("question_count")
    if isinstance(count_value, bool):
        raise ValidationError("Question count must be a whole number from 1 to 20.")
    try:
        question_count = int(count_value)
    except (TypeError, ValueError):
        raise ValidationError("Question count must be a whole number from 1 to 20.") from None
    if str(count_value).strip() != str(question_count) or not 1 <= question_count <= 20:
        raise ValidationError("Question count must be a whole number from 1 to 20.")

    question_types = data.get("question_types")
    if not isinstance(question_types, list) or not question_types:
        raise ValidationError("Choose at least one question type.")
    if any(item not in QUESTION_TYPES for item in question_types):
        raise ValidationError("One or more question types are not supported.")
    question_types = list(dict.fromkeys(question_types))

    language = data.get("language")
    if language not in LANGUAGES:
        raise ValidationError("Choose English, Hindi, or Marathi.")

    include_answer_key = data.get("include_answer_key")
    if not isinstance(include_answer_key, bool):
        raise ValidationError("Choose whether to include an answer key.")

    instructions = _text(
        data.get("additional_instructions", ""),
        "Additional instructions",
        800,
        required=False,
    )

    return {
        "subject": subject,
        "grade": grade,
        "topic": topic,
        "difficulty": difficulty,
        "question_count": question_count,
        "question_types": question_types,
        "language": language,
        "include_answer_key": include_answer_key,
        "additional_instructions": instructions,
    }


def generation_context(data: Any) -> dict[str, Any]:
    request_data = validate_request(data)
    prompt = {
        "subject": request_data["subject"],
        "grade": request_data["grade"],
        "topic": request_data["topic"],
        "difficulty": request_data["difficulty"],
        "question_count": request_data["question_count"],
        "question_types": [
            {"id": item, "label": QUESTION_TYPES[item]} for item in request_data["question_types"]
        ],
        "language": LANGUAGES[request_data["language"]],
        "include_answer_key": request_data["include_answer_key"],
        "additional_instructions": request_data["additional_instructions"],
    }
    return {
        "settings": request_data,
        "prompt": json.dumps(prompt, ensure_ascii=False),
        "system_instruction": SYSTEM_INSTRUCTION,
    }


def _parse_json(response_text: str) -> dict[str, Any]:
    if not isinstance(response_text, str) or not response_text.strip():
        raise ProviderError("The AI returned an empty worksheet. Please try again.", 502)

    candidate = response_text.strip()
    candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.IGNORECASE)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
        if not match:
            raise ProviderError("The AI response was not valid worksheet data. Please try again.", 502) from None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            raise ProviderError("The AI response was not valid worksheet data. Please try again.", 502) from None
    if not isinstance(parsed, dict):
        raise ProviderError("The AI response had an unexpected format. Please try again.", 502)
    return parsed


def _normalize_questions(
    values: Any,
    selected_types: list[str],
    expected_count: int,
    include_answer_key: bool,
) -> list[dict[str, Any]]:
    if not isinstance(values, list) or len(values) != expected_count:
        raise ProviderError("The AI returned the wrong number of questions. Please try again.", 502)

    questions = []
    seen = set()
    for index, value in enumerate(values, start=1):
        if not isinstance(value, dict):
            raise ProviderError("The AI returned a malformed question. Please try again.", 502)

        question_type = value.get("type")
        if question_type not in selected_types:
            raise ProviderError("The AI returned an unexpected question type. Please try again.", 502)
        try:
            prompt = _text(value.get("question"), f"Question {index}", 1200)
        except ValidationError as error:
            raise ProviderError(str(error), 502) from None
        normalized = re.sub(r"\W+", "", prompt.casefold())
        if normalized in seen:
            raise ProviderError("The AI returned duplicate questions. Please try again.", 502)
        seen.add(normalized)

        options = value.get("options", [])
        if not isinstance(options, list) or any(not isinstance(item, str) for item in options):
            raise ProviderError("The AI returned malformed answer choices. Please try again.", 502)
        options = [_text(item, "Answer choice", 300) for item in options]
        if question_type == "multiple_choice" and not 2 <= len(options) <= 6:
            raise ProviderError("A multiple-choice question needs 2 to 6 choices. Please try again.", 502)

        pairs = value.get("pairs", [])
        if not isinstance(pairs, list):
            raise ProviderError("The AI returned malformed matching pairs. Please try again.", 502)
        normalized_pairs = []
        for pair in pairs:
            if not isinstance(pair, dict):
                raise ProviderError("The AI returned malformed matching pairs. Please try again.", 502)
            normalized_pairs.append(
                {
                    "left": _text(pair.get("left"), "Matching item", 300),
                    "right": _text(pair.get("right"), "Matching answer", 300),
                }
            )
        if question_type == "match_following" and not 2 <= len(normalized_pairs) <= 8:
            raise ProviderError("A matching question needs 2 to 8 pairs. Please try again.", 502)

        points = value.get("points", 1)
        if isinstance(points, bool) or not isinstance(points, int) or not 1 <= points <= 10:
            raise ProviderError("The AI returned invalid question points. Please try again.", 502)

        answer = value.get("answer", "")
        explanation = value.get("explanation", "")
        if include_answer_key:
            try:
                answer = _text(answer, "Answer", 1200)
                explanation = _text(explanation, "Explanation", 1200, required=False)
            except ValidationError as error:
                raise ProviderError(str(error), 502) from None
        else:
            answer = ""
            explanation = ""

        questions.append(
            {
                "type": question_type,
                "question": prompt,
                "options": options,
                "pairs": normalized_pairs,
                "answer": answer,
                "explanation": explanation,
                "points": points,
            }
        )
    return questions


def validate_worksheet_document(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValidationError("Worksheet data must be a JSON object.")

    title = _text(data.get("title"), "Worksheet title", 140)
    subject = _text(data.get("subject"), "Subject", 80)
    grade = _text(data.get("grade"), "Class or grade", 40)
    topic = _text(data.get("topic"), "Topic", 160)
    difficulty = data.get("difficulty")
    if difficulty not in DIFFICULTIES:
        raise ValidationError("Worksheet difficulty is invalid.")
    language = data.get("language")
    if language not in LANGUAGES:
        raise ValidationError("Worksheet language is invalid.")
    include_answer_key = data.get("include_answer_key")
    if not isinstance(include_answer_key, bool):
        raise ValidationError("Worksheet answer-key setting is invalid.")
    instructions = _text(data.get("instructions", ""), "Worksheet instructions", 600, required=False)
    raw_questions = data.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise ValidationError("The worksheet must contain at least one question.")
    if len(raw_questions) > 20:
        raise ValidationError("The worksheet cannot contain more than 20 questions.")
    questions = _normalize_questions(
        raw_questions,
        list(QUESTION_TYPES),
        len(raw_questions),
        include_answer_key,
    )
    student_name = _text(data.get("student_name", ""), "Student name", 100, required=False)
    return {
        "title": title,
        "subject": subject,
        "grade": grade,
        "topic": topic,
        "difficulty": difficulty,
        "language": language,
        "include_answer_key": include_answer_key,
        "instructions": instructions,
        "student_name": student_name,
        "questions": questions,
    }


def generate_worksheet(data: Any) -> dict[str, Any]:
    context = generation_context(data)
    request_data = context["settings"]
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ProviderError("Gemini is not configured. Add GEMINI_API_KEY to your local .env file.", 503)

    selected_types = request_data["question_types"]
    schema = {
        "type": "OBJECT",
        "properties": {
            "title": {"type": "STRING"},
            "instructions": {"type": "STRING"},
            "questions": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "type": {"type": "STRING"},
                        "question": {"type": "STRING"},
                        "options": {"type": "ARRAY", "items": {"type": "STRING"}},
                        "pairs": {
                            "type": "ARRAY",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "left": {"type": "STRING"},
                                    "right": {"type": "STRING"},
                                },
                                "required": ["left", "right"],
                            },
                        },
                        "answer": {"type": "STRING"},
                        "explanation": {"type": "STRING"},
                        "points": {"type": "INTEGER"},
                    },
                    "required": ["type", "question", "options", "pairs", "answer", "explanation", "points"],
                },
            },
        },
        "required": ["title", "instructions", "questions"],
    }
    model = os.getenv("GEMINI_MODEL", "gemini-flash-latest").strip() or "gemini-flash-latest"

    try:
        with genai.Client(api_key=api_key) as client:
            response = client.models.generate_content(
                model=model,
                contents=context["prompt"],
                config=types.GenerateContentConfig(
                    system_instruction=context["system_instruction"],
                    response_mime_type="application/json",
                    response_json_schema=schema,
                    max_output_tokens=6000,
                ),
            )
    except errors.APIError as error:
        if error.code == 429:
            raise ProviderError("Gemini is temporarily rate-limited. Please wait a moment and try again.", 429) from None
        raise ProviderError("Gemini could not generate this worksheet. Check your API key and try again.", 503) from None
    except Exception:
        raise ProviderError("Could not reach Gemini. Check your internet connection and try again.", 503) from None

    try:
        generated = _parse_json(response.text)
        title = _text(generated.get("title"), "Worksheet title", 140)
        instructions = _text(generated.get("instructions", ""), "Worksheet instructions", 600, required=False)
        questions = _normalize_questions(
            generated.get("questions"),
            request_data["question_types"],
            request_data["question_count"],
            request_data["include_answer_key"],
        )
    except ValidationError as error:
        raise ProviderError(str(error), 502) from None

    return {
        "title": title,
        "instructions": instructions,
        "subject": request_data["subject"],
        "grade": request_data["grade"],
        "topic": request_data["topic"],
        "difficulty": request_data["difficulty"],
        "language": request_data["language"],
        "include_answer_key": request_data["include_answer_key"],
        "questions": questions,
    }