"""FastAPI backend for the Lakebase-powered support-ticket app.

The web layer is FastAPI; all data lives in Lakebase via ``db.py``. The logged-in
Databricks user (injected by Databricks Apps as the ``X-Forwarded-Email`` header)
is used as ``created_by`` / message ``author``.
"""

import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from databricks.sdk import WorkspaceClient
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, field_validator

import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("support-app")

templates = Jinja2Templates(directory="templates")

_w = None


def _client() -> WorkspaceClient:
    """Lazily construct the WorkspaceClient (avoids needing creds at import)."""
    global _w
    if _w is None:
        _w = WorkspaceClient()
    return _w


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure the schema exists before serving traffic. If Lakebase is
    # unreachable at boot we log and continue so /healthz still works.
    try:
        db.ensure_schema()
        logger.info("Lakebase schema ensured.")
    except Exception:
        logger.exception("Could not ensure schema at startup.")
    yield


app = FastAPI(title="Lakebase Support Tickets", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def current_user(request: Request) -> str:
    """Resolve the logged-in user's email.

    Databricks Apps inject ``X-Forwarded-Email`` on every request. Locally we
    fall back to the SDK's current-user lookup, then to a dev placeholder.
    """
    header_email = request.headers.get("x-forwarded-email")
    if header_email:
        return header_email
    try:
        return _client().current_user.me().user_name
    except Exception:
        return os.environ.get("DEV_USER_EMAIL", "local-dev@example.com")


# ---------------------------------------------------------------------------
# Request models (validation + helpful errors)
# ---------------------------------------------------------------------------

class TicketCreate(BaseModel):
    title: str
    priority: str = "medium"
    category: str = "general"

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Title must not be empty.")
        if len(v) > 200:
            raise ValueError("Title must be 200 characters or fewer.")
        return v

    @field_validator("priority")
    @classmethod
    def _priority_valid(cls, v: str) -> str:
        if v not in db.PRIORITIES:
            raise ValueError(f"Priority must be one of {', '.join(db.PRIORITIES)}.")
        return v

    @field_validator("category")
    @classmethod
    def _category_valid(cls, v: str) -> str:
        if v not in db.CATEGORIES:
            raise ValueError(f"Category must be one of {', '.join(db.CATEGORIES)}.")
        return v


class MessageCreate(BaseModel):
    message_text: str

    @field_validator("message_text")
    @classmethod
    def _text_not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Message text must not be empty.")
        return v


class StatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _status_valid(cls, v: str) -> str:
        if v not in db.STATUSES:
            raise ValueError(f"Status must be one of {', '.join(db.STATUSES)}.")
        return v


# ---------------------------------------------------------------------------
# Error handling — always return JSON so the frontend never chokes on HTML
# ---------------------------------------------------------------------------

@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exc_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"error": str(exc)})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/me")
def me(request: Request):
    return {"email": current_user(request)}


@app.get("/api/stats")
def get_stats():
    return db.stats()


@app.get("/api/tickets")
def get_tickets(status: str = None, priority: str = None,
                category: str = None, q: str = None):
    return db.list_tickets(status=status, priority=priority, category=category, q=q)


@app.get("/api/tickets/{ticket_id}")
def get_one_ticket(ticket_id: int):
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found.")
    ticket["messages"] = db.list_messages(ticket_id)
    return ticket


@app.get("/api/tickets/{ticket_id}/messages")
def get_messages(ticket_id: int):
    if not db.get_ticket(ticket_id):
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found.")
    return db.list_messages(ticket_id)


@app.post("/api/tickets", status_code=201)
def post_ticket(payload: TicketCreate, request: Request):
    return db.create_ticket(
        title=payload.title,
        created_by=current_user(request),
        priority=payload.priority,
        category=payload.category,
    )


@app.post("/api/tickets/{ticket_id}/messages", status_code=201)
def post_message(ticket_id: int, payload: MessageCreate, request: Request):
    if not db.get_ticket(ticket_id):
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found.")
    return db.add_message(
        ticket_id=ticket_id,
        message_text=payload.message_text,
        author=current_user(request),
    )


@app.patch("/api/tickets/{ticket_id}/status")
def patch_status(ticket_id: int, payload: StatusUpdate):
    updated = db.update_status(ticket_id, payload.status)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found.")
    return updated


@app.delete("/api/tickets/{ticket_id}")
def remove_ticket(ticket_id: int):
    deleted = db.delete_ticket(ticket_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found.")
    return {"deleted": ticket_id}


if __name__ == "__main__":
    host = os.getenv("APP_HOST", "0.0.0.0")
    port = int(os.getenv("APP_PORT", "8000"))
    uvicorn.run("app:app", host=host, port=port, reload=bool(os.getenv("DEV_RELOAD")))