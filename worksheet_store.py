import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


@contextmanager
def _connect(database_path: str) -> Iterator[sqlite3.Connection]:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS worksheets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                subject TEXT NOT NULL,
                grade TEXT NOT NULL,
                topic TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                worksheet_json TEXT NOT NULL,
                settings_json TEXT NOT NULL,
                prompt TEXT NOT NULL,
                system_instruction TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "worksheet": json.loads(row["worksheet_json"]),
        "generation_settings": json.loads(row["settings_json"]),
        "prompt": row["prompt"],
        "system_instruction": row["system_instruction"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_worksheet(
    database_path: str,
    worksheet: dict[str, Any],
    settings: dict[str, Any],
    prompt: str,
    system_instruction: str,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO worksheets (
                title, subject, grade, topic, difficulty, worksheet_json,
                settings_json, prompt, system_instruction, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                worksheet["title"],
                worksheet["subject"],
                worksheet["grade"],
                worksheet["topic"],
                worksheet["difficulty"],
                json.dumps(worksheet, ensure_ascii=False),
                json.dumps(settings, ensure_ascii=False),
                prompt,
                system_instruction,
                now,
                now,
            ),
        )
        row = connection.execute(
            "SELECT * FROM worksheets WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return _record(row)


def list_worksheets(database_path: str, search: str = "") -> list[dict[str, Any]]:
    with _connect(database_path) as connection:
        if search:
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            rows = connection.execute(
                """
                SELECT id, title, subject, grade, topic, difficulty, created_at, updated_at
                FROM worksheets
                WHERE title LIKE ? ESCAPE '\\' COLLATE NOCASE
                   OR subject LIKE ? ESCAPE '\\' COLLATE NOCASE
                   OR grade LIKE ? ESCAPE '\\' COLLATE NOCASE
                   OR topic LIKE ? ESCAPE '\\' COLLATE NOCASE
                ORDER BY updated_at DESC, id DESC
                """,
                (pattern, pattern, pattern, pattern),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT id, title, subject, grade, topic, difficulty, created_at, updated_at
                FROM worksheets
                ORDER BY updated_at DESC, id DESC
                """
            ).fetchall()
    return [dict(row) for row in rows]


def get_worksheet(database_path: str, worksheet_id: int) -> dict[str, Any] | None:
    with _connect(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM worksheets WHERE id = ?", (worksheet_id,)
        ).fetchone()
    return _record(row) if row else None


def update_worksheet(
    database_path: str, worksheet_id: int, worksheet: dict[str, Any]
) -> bool:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect(database_path) as connection:
        cursor = connection.execute(
            """
            UPDATE worksheets
            SET title = ?, subject = ?, grade = ?, topic = ?, difficulty = ?,
                worksheet_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                worksheet["title"],
                worksheet["subject"],
                worksheet["grade"],
                worksheet["topic"],
                worksheet["difficulty"],
                json.dumps(worksheet, ensure_ascii=False),
                now,
                worksheet_id,
            ),
        )
    return cursor.rowcount == 1
