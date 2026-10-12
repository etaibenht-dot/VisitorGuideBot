"""
admin/main.py -- the staff admin site (FastAPI + Jinja2, server-rendered, Hebrew RTL).

Run from the project root:  uvicorn admin.main:app --port 8000
"""

import os
import secrets
from contextlib import asynccontextmanager
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=HERE / "templates")

@asynccontextmanager
async def lifespan(_app):
    db.init_db()          # make sure the tables exist before the first request
    yield


app = FastAPI(title="VisitorGuideBot admin", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


# --------------------------------------------------------------------------- auth

PUBLIC_PATHS = ("/login", "/static")


class LoginRequired(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not request.url.path.startswith(PUBLIC_PATHS) and not request.session.get("user_id"):
            return RedirectResponse("/login", status_code=303)
        return await call_next(request)


# Order matters: SessionMiddleware is added last so it runs first (outermost).
app.add_middleware(LoginRequired)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET") or secrets.token_hex(32),
    session_cookie="guide_admin",
    max_age=60 * 60 * 12,
)


# --------------------------------------------------------------------------- helpers

def flash(request: Request, message: str) -> None:
    request.session["flash"] = message


def render(request: Request, template: str, **ctx):
    ctx.setdefault("error", None)
    return templates.TemplateResponse(
        request,
        template,
        {
            "flash": request.session.pop("flash", None),
            "user_name": request.session.get("user_name"),
            "path": request.url.path,
            **ctx,
        },
    )


def redirect(url: str):
    return RedirectResponse(url, status_code=303)


async def form_dict(request: Request) -> dict:
    form = await request.form()
    return {k: v for k, v in form.items()}


# --------------------------------------------------------------------------- login

@app.get("/login")
def login_page(request: Request):
    return render(request, "login.html")


@app.post("/login")
async def login(request: Request):
    form = await form_dict(request)
    user = db.authenticate(form.get("username"), form.get("password"))
    if not user:
        return render(request, "login.html", error="שם משתמש או סיסמה שגויים.", username=form.get("username", ""))
    request.session.clear()
    request.session["user_id"] = user["id"]
    request.session["user_name"] = user["full_name"] or user["username"]
    return redirect("/")


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return redirect("/login")


# --------------------------------------------------------------------------- home

@app.get("/")
def home(request: Request):
    return render(
        request, "home.html",
        counts=db.dashboard_counts(),
        latest=db.list_unanswered(status="new", limit=5),
        today=db.todays_upcoming_events(),
    )


# --------------------------------------------------------------------------- places

@app.get("/places")
def places_list(request: Request):
    return render(request, "places_list.html", places=db.list_places())


@app.get("/places/new")
def place_new(request: Request):
    return render(request, "place_form.html", place={"is_active": 1}, gestures=db.list_gestures(), is_new=True)


@app.post("/places/new")
async def place_create(request: Request):
    data = await form_dict(request)
    try:
        db.create_place(data)
    except db.ValidationError as e:
        return render(request, "place_form.html", place=data, gestures=db.list_gestures(), is_new=True, error=str(e))
    flash(request, "נשמר")
    return redirect("/places")


@app.get("/places/{place_id}")
def place_edit(request: Request, place_id: int):
    place = db.get_place(place_id)
    if not place:
        return redirect("/places")
    return render(request, "place_form.html", place=place, gestures=db.list_gestures(), is_new=False)


@app.post("/places/{place_id}")
async def place_update(request: Request, place_id: int):
    data = await form_dict(request)
    try:
        db.update_place(place_id, data)
    except db.ValidationError as e:
        data["id"] = place_id
        return render(request, "place_form.html", place=data, gestures=db.list_gestures(), is_new=False, error=str(e))
    flash(request, "נשמר")
    return redirect("/places")


@app.post("/places/{place_id}/delete")
def place_delete(request: Request, place_id: int):
    try:
        db.delete_place(place_id)
        flash(request, "נמחק")
    except db.ValidationError as e:
        flash(request, str(e))
    return redirect("/places")


# --------------------------------------------------------------------------- knowledge + categories

@app.get("/knowledge")
def knowledge_list(request: Request, category: str = "", q: str = ""):
    return render(
        request, "knowledge_list.html",
        items=db.list_knowledge(category_id=category or None, search=q),
        categories=db.list_categories(), category=category, q=q,
    )


@app.get("/knowledge/new")
def knowledge_new(request: Request, from_unanswered: int = 0):
    item = {"is_active": 1}
    if from_unanswered:
        question = db.get_unanswered(from_unanswered)
        if question:
            item["question"] = question["question_text"]
    return render(
        request, "knowledge_form.html", item=item, categories=db.list_categories(),
        is_new=True, from_unanswered=from_unanswered,
    )


@app.post("/knowledge/new")
async def knowledge_create(request: Request):
    data = await form_dict(request)
    from_unanswered = int(data.get("from_unanswered") or 0)
    try:
        db.create_knowledge(data, user_id=request.session.get("user_id"))
    except db.ValidationError as e:
        return render(
            request, "knowledge_form.html", item=data, categories=db.list_categories(),
            is_new=True, from_unanswered=from_unanswered, error=str(e),
        )
    if from_unanswered:
        db.set_unanswered_status(from_unanswered, "handled")
        flash(request, "נשמר. השאלה סומנה כטופלה.")
        return redirect("/unanswered")
    flash(request, "נשמר")
    return redirect("/knowledge")


@app.get("/knowledge/{item_id}")
def knowledge_edit(request: Request, item_id: int):
    item = db.get_knowledge(item_id)
    if not item:
        return redirect("/knowledge")
    return render(request, "knowledge_form.html", item=item, categories=db.list_categories(),
                  is_new=False, from_unanswered=0)


@app.post("/knowledge/{item_id}")
async def knowledge_update(request: Request, item_id: int):
    data = await form_dict(request)
    try:
        db.update_knowledge(item_id, data, user_id=request.session.get("user_id"))
    except db.ValidationError as e:
        data["id"] = item_id
        return render(request, "knowledge_form.html", item=data, categories=db.list_categories(),
                      is_new=False, from_unanswered=0, error=str(e))
    flash(request, "נשמר")
    return redirect("/knowledge")


@app.post("/knowledge/{item_id}/delete")
def knowledge_delete(request: Request, item_id: int):
    db.delete_knowledge(item_id)
    flash(request, "נמחק")
    return redirect("/knowledge")


@app.post("/categories/new")
async def category_create(request: Request):
    data = await form_dict(request)
    try:
        db.create_category(data.get("name"))
        flash(request, "הקטגוריה נוספה")
    except db.ValidationError as e:
        flash(request, str(e))
    return redirect("/knowledge")


@app.post("/categories/{category_id}/delete")
def category_delete(request: Request, category_id: int):
    try:
        db.delete_category(category_id)
        flash(request, "הקטגוריה נמחקה")
    except db.ValidationError as e:
        flash(request, str(e))
    return redirect("/knowledge")


# --------------------------------------------------------------------------- events

@app.get("/events")
def events_list(request: Request):
    return render(request, "events_list.html", events=db.list_events())


@app.get("/events/new")
def event_new(request: Request):
    return render(request, "event_form.html", event={"is_active": 1}, places=db.list_places(), is_new=True)


@app.post("/events/new")
async def event_create(request: Request):
    data = await form_dict(request)
    try:
        db.create_event(data)
    except db.ValidationError as e:
        return render(request, "event_form.html", event=data, places=db.list_places(), is_new=True, error=str(e))
    flash(request, "נשמר")
    return redirect("/events")


@app.get("/events/{event_id}")
def event_edit(request: Request, event_id: int):
    event = db.get_event(event_id)
    if not event:
        return redirect("/events")
    return render(request, "event_form.html", event=event, places=db.list_places(), is_new=False)


@app.post("/events/{event_id}")
async def event_update(request: Request, event_id: int):
    data = await form_dict(request)
    try:
        db.update_event(event_id, data)
    except db.ValidationError as e:
        data["id"] = event_id
        return render(request, "event_form.html", event=data, places=db.list_places(), is_new=False, error=str(e))
    flash(request, "נשמר")
    return redirect("/events")


@app.post("/events/{event_id}/delete")
def event_delete(request: Request, event_id: int):
    db.delete_event(event_id)
    flash(request, "נמחק")
    return redirect("/events")


# --------------------------------------------------------------------------- unanswered

@app.get("/unanswered")
def unanswered_list(request: Request, show: str = "new"):
    status = None if show == "all" else "new"
    return render(request, "unanswered.html", questions=db.list_unanswered(status=status), show=show)


@app.post("/unanswered/{qid}/handled")
def unanswered_handled(request: Request, qid: int):
    db.set_unanswered_status(qid, "handled")
    flash(request, "סומן כטופל")
    return redirect("/unanswered")


@app.post("/unanswered/{qid}/delete")
def unanswered_delete(request: Request, qid: int):
    db.delete_unanswered(qid)
    flash(request, "נמחק")
    return redirect("/unanswered")


# --------------------------------------------------------------------------- users

@app.get("/users")
def users_list(request: Request):
    return render(request, "users.html", users=db.list_users())


@app.post("/users/new")
async def user_create(request: Request):
    data = await form_dict(request)
    try:
        db.create_user(data.get("username"), data.get("password"), data.get("full_name"))
        flash(request, "המשתמש נוסף")
    except db.ValidationError as e:
        flash(request, str(e))
    return redirect("/users")


@app.post("/users/password")
async def user_password(request: Request):
    data = await form_dict(request)
    if data.get("password") != data.get("password2"):
        flash(request, "הסיסמאות לא זהות.")
        return redirect("/users")
    try:
        db.change_password(request.session["user_id"], data.get("password"))
        flash(request, "הסיסמה עודכנה")
    except db.ValidationError as e:
        flash(request, str(e))
    return redirect("/users")
