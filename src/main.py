# FastAPI application and routes

from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.middleware.sessions import SessionMiddleware
import secrets
from src.table import User
from src.database import engine, Session


app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="supersecretkey")
security = HTTPBasic()

app.mount("/static", StaticFiles(directory="src/static"), name="static")
templates = Jinja2Templates(directory="src/templates")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    # SSR: If admin logged in, show admin link
    admin_logged = request.session.get("admin_logged", False)
    return templates.TemplateResponse("index.html", {"request": request, "admin_logged": admin_logged})


@app.get("/scan", response_class=HTMLResponse)
def scan(request: Request):
    return templates.TemplateResponse("scan.html", {"request": request})


@app.post("/scan", response_class=HTMLResponse)
def process_scan(request: Request, image_data: str = Form(...)):
    # TODO: Integrate with ml_engine for face recognition
    # For now, redirect to success
    return RedirectResponse(url="/success", status_code=303)


@app.get("/success", response_class=HTMLResponse)
def success(request: Request):
    return templates.TemplateResponse("success.html", {"request": request})


# Universal login SSR
@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@app.post("/login", response_class=HTMLResponse)
def login_post(request: Request, username: str = Form(...), password: str = Form(...), admin_mode: str = Form("0")):
    # DB lookup for both admin and regular users
    with Session(engine) as session:
        user = session.exec(User.select().where(User.username == username)).first()
        if user and user.password_hash == password:
            request.session["user_id"] = user.id
            request.session["is_admin"] = user.is_admin
            # Only allow admin panel if admin_mode=1 and user.is_admin
            if admin_mode == "1" and user.is_admin:
                return RedirectResponse(url="/admin-panel", status_code=303)
            elif admin_mode == "1" and not user.is_admin:
                return templates.TemplateResponse("login.html", {"request": request, "error": "Not authorized as admin."})
            else:
                return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})

@app.get("/admin-panel", response_class=HTMLResponse)
def admin_panel(request: Request):
    if not request.session.get("is_admin", False):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("admin_panel.html", {"request": request})

# Secret key combo route (for demo, use /admin-secret)
@app.get("/admin-secret", response_class=HTMLResponse)
def admin_secret(request: Request):
    # This would be triggered by a key combo in JS on the client
    return RedirectResponse(url="/login", status_code=303)
