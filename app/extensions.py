import sqlite3

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()


@event.listens_for(Engine, "connect")
def _sqlite_settings(connection, _record):
    """Concurrent requests share one SQLite file: wait instead of failing, allow readers during a write, enforce links between tables."""
    if not isinstance(connection, sqlite3.Connection):
        return
    cursor = connection.cursor()
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")   # stays in-memory for :memory: databases
    cursor.close()
