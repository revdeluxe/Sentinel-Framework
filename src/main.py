# src/main.py
import json
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import select, Session
from pydantic import BaseModel

# Import local modules
from src.ml_engine import recognize_face
from src.database import engine, init_db, get_session
from src.table import User, SystemConfig, Log

app = FastAPI(title="Sentinel Framework")
app.add_middleware(SessionMiddleware, secret_key="SUPER_SECRET_KEY")

app.mount("/static", StaticFiles(directory="src/static"), name="static")
templates = Jinja2Templates(directory="src/templates")

class BiometricRequest(BaseModel):
    image_b64: str

# --- HELPER: GET CONFIG ---
def get_current_config(session: Session):
    return session.exec(select(SystemConfig)).first()

# --- MIDDLEWARE ---
@app.middleware("http")
async def check_setup_status(request: Request, call_next):
    if request.url.path.startswith("/static") or request.url.path == "/setup":
        return await call_next(request)

    try:
        with Session(engine) as session:
            config = get_current_config(session)
            if not config or not config.is_setup_complete:
                return RedirectResponse(url="/setup", status_code=303)
    except:
        return RedirectResponse(url="/setup", status_code=303)

    return await call_next(request)

# --- ROUTES ---

@app.on_event("startup")
def on_startup():
    init_db()

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    with Session(engine) as session:
        config = get_current_config(session)
        # Default fallback if DB is empty (edge case)
        sys_name = config.system_name if config else "Sentinel Framework"
        mode = config.deployment_mode if config else "gateway"

    # Redirect Kiosk Mode
    if mode == 'kiosk' and not request.session.get("is_admin"):
         return templates.TemplateResponse("kiosk_login.html", {
            "request": request,
            "system_name": sys_name
        })

    return templates.TemplateResponse("index.html", {
        "request": request, 
        "user_id": request.session.get("user_id"), 
        "is_admin": request.session.get("is_admin"),
        "system_name": sys_name
    })

# --- SETUP ---
@app.get("/setup", response_class=HTMLResponse)
def setup_get(request: Request):
    return templates.TemplateResponse("setup.html", {"request": request})

@app.post("/setup")
async def setup_post(request: Request, session: Session = Depends(get_session)):
    form_data = await request.form()
    
    # 1. Admin
    admin_user = form_data.get("admin_username")
    admin_pass = form_data.get("admin_password")
    
    existing_admin = session.exec(select(User).where(User.username == admin_user)).first()
    if not existing_admin:
        new_admin = User(username=admin_user, password_hash=admin_pass, is_admin=True, full_name="Admin")
        session.add(new_admin)
    
    # 2. Config & Naming Logic
    mode = form_data.get("deployment_mode")
    
    # DYNAMIC NAMING BASED ON MODE
    sys_name_map = {
        "gateway": "Sentinel Framework",
        "kiosk": "Sentinel FaceID Systems",
        "attendance": "Sentinel Watchdog"
    }
    chosen_name = sys_name_map.get(mode, "Sentinel Framework")

    config_data = {}
    for key, value in form_data.items():
        if key not in ["admin_username", "admin_password", "deployment_mode"]:
            config_data[key] = value
            
    # 3. Save
    new_config = SystemConfig(
        system_name=chosen_name,
        deployment_mode=mode,
        config_json=json.dumps(config_data),
        is_setup_complete=True
    )
    session.add(new_config)
    session.commit()
    
    return RedirectResponse(url="/login", status_code=303)

# --- LOGIN ---
@app.get("/login", response_class=HTMLResponse)
def login_view(request: Request):
    with Session(engine) as session:
        config = get_current_config(session)
        sys_name = config.system_name if config else "Sentinel"

    return templates.TemplateResponse("login.html", {
        "request": request, 
        "system_name": sys_name
    })

@app.post("/login", response_class=HTMLResponse)
def login_process(request: Request, username: str = Form(...), password: str = Form(...), session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.username == username)).first()
    
    # Config for branding
    config = get_current_config(session)
    sys_name = config.system_name if config else "Sentinel"

    if not user or user.password_hash != password:
        return templates.TemplateResponse("login.html", {
            "request": request, 
            "error": "Invalid credentials", 
            "system_name": sys_name
        })
    
    # --- NEW ADMIN LOGIC ---
    # User is admin IF:
    # 1. They are explicitly marked 'is_admin' (like root)
    # 2. OR they have a valid 'admin_key' string in their profile
    is_privileged = user.is_admin or (user.admin_key is not None and user.admin_key != "")
    
    request.session["user_id"] = user.id
    request.session["is_admin"] = is_privileged
    request.session["is_superuser"] = user.is_admin # Only root has this
    request.session["full_name"] = user.full_name

    if is_privileged:
        return RedirectResponse(url="/admin", status_code=303)
    
    return RedirectResponse(url="/", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)

# --- ADMIN ---
@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    if not request.session.get("is_admin"):
        return RedirectResponse(url="/login")
        
    with Session(engine) as session:
        config = get_current_config(session)
        current_mode = config.deployment_mode if config else "gateway"
        sys_name = config.system_name if config else "Sentinel"

    return templates.TemplateResponse("admin_panel.html", {
        "request": request, 
        "mode": current_mode,
        "system_name": sys_name,
        "user": request.session.get("full_name"),
        "is_superuser": request.session.get("is_superuser") # For hiding the Key Manager
    })

# --- BIOMETRICS ---
@app.get("/scan", response_class=HTMLResponse)
def scan_view(request: Request):
    with Session(engine) as session:
        config = get_current_config(session)
        sys_name = config.system_name if config else "Sentinel"

    return templates.TemplateResponse("scan.html", {
        "request": request,
        "system_name": sys_name
    })

@app.post("/api/biometric-auth")
async def api_biometric_auth(payload: BiometricRequest, request: Request):
    result = recognize_face(payload.image_b64)
    if result["match"]:
        request.session["user_id"] = result["user_id"]
        request.session["full_name"] = result["name"]
        return {"status": "success", "user": result["name"]}
    else:
        return {"status": "unknown"}