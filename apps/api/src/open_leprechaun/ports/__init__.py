"""The ports: every outside source of data sits behind a small interface with
a fake (ADR-0008). A port absorbs its provider's quirks and emits canonical
records; it never touches the database, converts to EUR, or computes tax —
those belong to the repositories and services that consume it.
"""
