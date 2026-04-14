"""
Módulo A: Persistencia con SQLite
Gestiona biblioteca, progreso de reproducción y notas con marcas de tiempo.
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "audiobook.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


_DEFAULT_CATEGORIES = ["Libros", "Prédicas", "Música", "Podcasts", "Otros"]


def init_db():
    """Crea las tablas si no existen y aplica migraciones."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS categories (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT    NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS library (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                title         TEXT    NOT NULL,
                path          TEXT    NOT NULL UNIQUE,
                source        TEXT    NOT NULL DEFAULT 'local',
                duration      REAL    NOT NULL DEFAULT 0.0,
                last_position REAL    NOT NULL DEFAULT 0.0,
                thumbnail     TEXT,
                category      TEXT    NOT NULL DEFAULT 'Sin categoría',
                added_at      TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS notes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id     INTEGER NOT NULL REFERENCES library(id) ON DELETE CASCADE,
                position    REAL    NOT NULL,
                content     TEXT    NOT NULL,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_notes_file ON notes(file_id);
        """)
        # Migración: agregar columna category si la BD ya existía sin ella
        cols = [r[1] for r in conn.execute("PRAGMA table_info(library)").fetchall()]
        if "category" not in cols:
            conn.execute("ALTER TABLE library ADD COLUMN category TEXT NOT NULL DEFAULT 'Sin categoría'")
        # Insertar categorías por defecto
        for cat in _DEFAULT_CATEGORIES:
            conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (cat,))


# ─────────────────────────── LIBRARY ────────────────────────────────────────

def add_file(title: str, path: str, source: str = "local",
             duration: float = 0.0, thumbnail: str = None,
             category: str = "Sin categoría") -> int:
    """Agrega un archivo a la biblioteca. Devuelve su id."""
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO library (title, path, source, duration, thumbnail, category)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (title, path, source, duration, thumbnail, category),
        )
        if cur.lastrowid:
            return cur.lastrowid
        # Si ya existía, devuelve el id existente
        row = conn.execute("SELECT id FROM library WHERE path=?", (path,)).fetchone()
        return row["id"]


def get_all_files(category: str = None) -> list[dict]:
    """Devuelve archivos ordenados por fecha. Filtra por categoría si se especifica."""
    with get_connection() as conn:
        if category:
            rows = conn.execute(
                "SELECT * FROM library WHERE category=? ORDER BY added_at DESC",
                (category,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM library ORDER BY added_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_file(file_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM library WHERE id=?", (file_id,)
        ).fetchone()
        return dict(row) if row else None


def delete_file(file_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM library WHERE id=?", (file_id,))


# ─────────────────────────── PROGRESO ───────────────────────────────────────

def save_progress(file_id: int, position: float) -> None:
    """Guarda el milisegundo exacto de progreso (en segundos)."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE library SET last_position=? WHERE id=?",
            (position, file_id),
        )


def get_progress(file_id: int) -> float:
    """Retorna la última posición guardada (segundos). 0.0 si no existe."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT last_position FROM library WHERE id=?", (file_id,)
        ).fetchone()
        return row["last_position"] if row else 0.0


def update_duration(file_id: int, duration: float) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE library SET duration=? WHERE id=?", (duration, file_id)
        )


# ─────────────────────────── NOTAS ──────────────────────────────────────────

def add_note(file_id: int, position: float, content: str) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO notes (file_id, position, content) VALUES (?, ?, ?)",
            (file_id, position, content),
        )
        return cur.lastrowid


def get_notes(file_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM notes WHERE file_id=? ORDER BY position",
            (file_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_note(note_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM notes WHERE id=?", (note_id,))


# ─────────────────────────── CATEGORÍAS ─────────────────────────────────────

def get_categories() -> list[str]:
    """Devuelve todas las categorías ordenadas alfabéticamente."""
    with get_connection() as conn:
        rows = conn.execute("SELECT name FROM categories ORDER BY name").fetchall()
        return [r["name"] for r in rows]


def add_category(name: str) -> None:
    """Agrega una categoría nueva (ignora si ya existe)."""
    with get_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (name,))


def delete_category(name: str) -> None:
    """Elimina una categoría. Los archivos pasan a 'Sin categoría'."""
    with get_connection() as conn:
        conn.execute("UPDATE library SET category='Sin categoría' WHERE category=?", (name,))
        conn.execute("DELETE FROM categories WHERE name=?", (name,))


def update_file_category(file_id: int, category: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE library SET category=? WHERE id=?", (category, file_id))


# ─────────────────────────── INIT ───────────────────────────────────────────
init_db()
