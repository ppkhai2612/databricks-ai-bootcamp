"""Schema management and data-access layer for the support-ticket app.

All operational data lives in Lakebase (Databricks-managed Postgres). Every
function here reads from or writes to Lakebase via the helpers in ``lakebase``.
Nothing is hard-coded — the app is fully backed by the database.
"""

import lakebase

# Allowed enum values, shared with the API validation layer.
STATUSES = ("open", "in_progress", "resolved")
PRIORITIES = ("low", "medium", "high", "urgent")
CATEGORIES = ("general", "bug", "feature", "question", "account", "billing")


def ensure_schema() -> None:
    """Create the tickets / ticket_messages tables and indexes if missing.

    Idempotent: safe to call on every app startup.
    """
    with lakebase.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tickets (
                    ticket_id   BIGSERIAL PRIMARY KEY,
                    title       TEXT NOT NULL,
                    status      TEXT NOT NULL DEFAULT 'open'
                                CHECK (status IN ('open','in_progress','resolved')),
                    priority    TEXT NOT NULL DEFAULT 'medium'
                                CHECK (priority IN ('low','medium','high','urgent')),
                    category    TEXT NOT NULL DEFAULT 'general',
                    created_by  TEXT NOT NULL,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS ticket_messages (
                    message_id   BIGSERIAL PRIMARY KEY,
                    ticket_id    BIGINT NOT NULL
                                 REFERENCES tickets(ticket_id) ON DELETE CASCADE,
                    message_text TEXT NOT NULL,
                    author       TEXT NOT NULL,
                    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_ticket "
                "ON ticket_messages(ticket_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)"
            )
            conn.commit()


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def list_tickets(status=None, priority=None, category=None, q=None) -> list[dict]:
    """Return tickets (newest first) with a message count, optionally filtered."""
    clauses = []
    params: list = []
    if status:
        clauses.append("t.status = %s")
        params.append(status)
    if priority:
        clauses.append("t.priority = %s")
        params.append(priority)
    if category:
        clauses.append("t.category = %s")
        params.append(category)
    if q:
        clauses.append("t.title ILIKE %s")
        params.append(f"%{q}%")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT t.ticket_id, t.title, t.status, t.priority, t.category,
               t.created_by, t.created_at,
               COUNT(m.message_id) AS message_count
        FROM tickets t
        LEFT JOIN ticket_messages m ON m.ticket_id = t.ticket_id
        {where}
        GROUP BY t.ticket_id
        ORDER BY t.created_at DESC
    """
    return lakebase.run_query(sql, tuple(params) if params else None)


def get_ticket(ticket_id: int) -> dict | None:
    """Return a single ticket by id, or None."""
    rows = lakebase.run_query(
        """
        SELECT ticket_id, title, status, priority, category, created_by, created_at
        FROM tickets WHERE ticket_id = %s
        """,
        (ticket_id,),
    )
    return rows[0] if rows else None


def list_messages(ticket_id: int) -> list[dict]:
    """Return all messages for a ticket, oldest first (thread order)."""
    return lakebase.run_query(
        """
        SELECT message_id, ticket_id, message_text, author, created_at
        FROM ticket_messages
        WHERE ticket_id = %s
        ORDER BY created_at ASC
        """,
        (ticket_id,),
    )


def stats() -> dict:
    """Return aggregate statistics for the dashboard."""
    totals = lakebase.run_query(
        """
        SELECT
            (SELECT COUNT(*) FROM tickets)          AS total_tickets,
            (SELECT COUNT(*) FROM ticket_messages)  AS total_messages
        """
    )[0]
    by_status = lakebase.run_query(
        "SELECT status, COUNT(*) AS count FROM tickets GROUP BY status"
    )
    by_priority = lakebase.run_query(
        "SELECT priority, COUNT(*) AS count FROM tickets GROUP BY priority"
    )
    return {
        "total_tickets": totals["total_tickets"],
        "total_messages": totals["total_messages"],
        "by_status": {r["status"]: r["count"] for r in by_status},
        "by_priority": {r["priority"]: r["count"] for r in by_priority},
    }


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def create_ticket(title, created_by, priority="medium", category="general") -> dict:
    """Insert a new ticket and return the created row."""
    with lakebase.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tickets (title, status, priority, category, created_by)
                VALUES (%s, 'open', %s, %s, %s)
                RETURNING ticket_id, title, status, priority, category,
                          created_by, created_at
                """,
                (title, priority, category, created_by),
            )
            row = cur.fetchone()
            conn.commit()
            return row


def add_message(ticket_id, message_text, author) -> dict:
    """Insert a message on a ticket and return the created row."""
    with lakebase.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ticket_messages (ticket_id, message_text, author)
                VALUES (%s, %s, %s)
                RETURNING message_id, ticket_id, message_text, author, created_at
                """,
                (ticket_id, message_text, author),
            )
            row = cur.fetchone()
            conn.commit()
            return row


def update_status(ticket_id, status) -> dict | None:
    """Update a ticket's status and return the updated row (or None if absent)."""
    with lakebase.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE tickets SET status = %s
                WHERE ticket_id = %s
                RETURNING ticket_id, title, status, priority, category,
                          created_by, created_at
                """,
                (status, ticket_id),
            )
            row = cur.fetchone()
            conn.commit()
            return row


def delete_ticket(ticket_id) -> int:
    """Delete a ticket (messages cascade). Returns rows deleted (0 or 1)."""
    return lakebase.run_write(
        "DELETE FROM tickets WHERE ticket_id = %s", (ticket_id,)
    )