"""
SQLite database for chat history and config.
Zero-config, just a file. No MongoDB needed.
"""

import sqlite3
import json
import uuid
import os
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_DIR = Path(__file__).parent
DB_PATH = DB_DIR / "beyond.db"


def get_db():
    """Get a SQLite connection with row factory."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_db()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT 'New Chat',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                ai_message TEXT DEFAULT '',
                pattern_name TEXT DEFAULT '',
                point_data TEXT DEFAULT '[]',
                python_code TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON chat_messages(session_id, created_at);
        """)
        conn.commit()
        logger.info(f"Database initialized at {DB_PATH}")
    finally:
        conn.close()


# ===== Session Operations =====

def create_session(title="New Chat"):
    """Create a new chat session."""
    conn = get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        session_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO chat_sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, title, now, now)
        )
        conn.commit()
        return {"id": session_id, "title": title, "created_at": now, "updated_at": now}
    finally:
        conn.close()


def list_sessions(limit=50):
    """List all chat sessions, newest first."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM chat_sessions ORDER BY updated_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_session(session_id, title=None):
    """Update session title and timestamp."""
    conn = get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        if title:
            conn.execute(
                "UPDATE chat_sessions SET title=?, updated_at=? WHERE id=?",
                (title, now, session_id)
            )
        else:
            conn.execute(
                "UPDATE chat_sessions SET updated_at=? WHERE id=?",
                (now, session_id)
            )
        conn.commit()
    finally:
        conn.close()


def get_session(session_id):
    """Get a single session."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM chat_sessions WHERE id=?", (session_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_session(session_id):
    """Delete a session and all its messages."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM chat_messages WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM chat_sessions WHERE id=?", (session_id,))
        conn.commit()
    finally:
        conn.close()


# ===== Message Operations =====

def add_message(session_id, role, content, ai_message="", pattern_name="",
                point_data=None, python_code=""):
    """Add a message to a session."""
    conn = get_db()
    try:
        msg_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        point_data_json = json.dumps(point_data or [])
        conn.execute(
            """INSERT INTO chat_messages
               (id, session_id, role, content, ai_message, pattern_name, point_data, python_code, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (msg_id, session_id, role, content, ai_message, pattern_name, point_data_json, python_code, now)
        )
        conn.commit()
        return msg_id
    finally:
        conn.close()


def get_messages(session_id, limit=200):
    """Get all messages for a session, oldest first."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM chat_messages WHERE session_id=? ORDER BY created_at ASC LIMIT ?",
            (session_id, limit)
        ).fetchall()
        messages = []
        for r in rows:
            msg = dict(r)
            # Parse point_data back from JSON string
            try:
                msg['point_data'] = json.loads(msg.get('point_data', '[]'))
            except (json.JSONDecodeError, TypeError):
                msg['point_data'] = []
            messages.append(msg)
        return messages
    finally:
        conn.close()


def get_recent_history(session_id, limit=10):
    """Get recent messages for AI context building."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT role, content, ai_message FROM chat_messages WHERE session_id=? ORDER BY created_at ASC LIMIT ?",
            (session_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
