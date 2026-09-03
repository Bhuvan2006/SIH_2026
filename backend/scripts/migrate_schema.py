"""
Idempotent SQLite schema migration.

    python scripts/migrate_schema.py

SQLAlchemy's create_all() creates missing TABLES but never alters existing
ones, so any column added to a model after the database was first created is
invisible to SQLite and every query on that table fails with
"no such column". This walks the models, compares them against the live
schema, and issues the missing ALTER TABLE ADD COLUMN statements.

Deliberately additive only: it never drops or retypes a column, so running it
cannot lose data. Safe to run repeatedly — existing columns are skipped.

A real deployment should use Alembic; this exists so a prototype database
doesn't have to be deleted every time a field is added.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app.db.database import Base, engine  # noqa: E402
import app.models.models  # noqa: E402,F401  (registers the models)

# SQLite accepts a small set of type names; map SQLAlchemy types onto them.
TYPE_MAP = {
    "VARCHAR": "VARCHAR",
    "TEXT": "TEXT",
    "INTEGER": "INTEGER",
    "FLOAT": "FLOAT",
    "BOOLEAN": "BOOLEAN",
    "DATETIME": "DATETIME",
}


def sqlite_type(column) -> str:
    try:
        compiled = column.type.compile(dialect=engine.dialect).upper()
    except Exception:  # noqa: BLE001
        return "VARCHAR"
    for key in TYPE_MAP:
        if key in compiled:
            return TYPE_MAP[key]
    return "VARCHAR"


def default_clause(column) -> str:
    """
    Only literal defaults can go in ADD COLUMN. Python-side defaults (uuid
    factories, datetime.utcnow) are applied by the ORM on insert, so existing
    rows just get NULL, which is correct for a backfilled column.
    """
    d = column.default
    if d is None or getattr(d, "is_callable", False):
        return ""
    arg = getattr(d, "arg", None)
    if isinstance(arg, bool):
        return f" DEFAULT {1 if arg else 0}"
    if isinstance(arg, (int, float)):
        return f" DEFAULT {arg}"
    if isinstance(arg, str):
        escaped = arg.replace("'", "''")
        return f" DEFAULT '{escaped}'"
    return ""


def main() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    # Create any genuinely new tables first.
    Base.metadata.create_all(bind=engine)
    new_tables = set(inspect(engine).get_table_names()) - existing_tables
    for t in sorted(new_tables):
        print(f"created table: {t}")

    added = 0
    with engine.begin() as conn:
        for table_name, table in Base.metadata.tables.items():
            if table_name in new_tables:
                continue
            live_cols = {c["name"] for c in inspect(engine).get_columns(table_name)}
            for column in table.columns:
                if column.name in live_cols:
                    continue
                ddl = (
                    f'ALTER TABLE "{table_name}" '
                    f'ADD COLUMN "{column.name}" {sqlite_type(column)}{default_clause(column)}'
                )
                conn.execute(text(ddl))
                print(f"  + {table_name}.{column.name}")
                added += 1

    if added == 0 and not new_tables:
        print("schema already up to date")
    else:
        print(f"\nmigration complete: {len(new_tables)} table(s), {added} column(s) added")


if __name__ == "__main__":
    main()
