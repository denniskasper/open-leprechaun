"""Writes and reads over saved column mappings (ticket 33). Saving is an
upsert by name: one name is always one current declaration, so re-saving a
mapping the Admin refined replaces it rather than growing variants. The
definition is stored whole as JSON — the port owns its vocabulary; whether a
definition is complete is the service's judgement, made before anything
lands here."""

import json

from sqlalchemy import Engine, Row, text


def save(engine: Engine, *, name: str, definition: dict) -> Row:
    """The saved row back in one act, so no caller re-lists to answer it."""
    with engine.begin() as connection:
        return connection.execute(
            text(
                "INSERT INTO column_mapping (name, definition)"
                " VALUES (:name, CAST(:definition AS jsonb))"
                " ON CONFLICT (name) DO UPDATE SET definition = excluded.definition"
                " RETURNING id, name, definition, created_at"
            ),
            {"name": name, "definition": json.dumps(definition)},
        ).one()


def list_mappings(engine: Engine) -> list[Row]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text("SELECT id, name, definition, created_at FROM column_mapping ORDER BY name")
            ).all()
        )


def delete(engine: Engine, mapping_id: int) -> bool:
    """Remove one saved mapping. False when nothing wore the id. Imported
    rows are untouched — their provenance names the Account, not the
    mapping."""
    with engine.begin() as connection:
        removed = connection.execute(
            text("DELETE FROM column_mapping WHERE id = :id"), {"id": mapping_id}
        )
    return removed.rowcount == 1
