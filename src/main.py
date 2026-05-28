# src/main.py
import json
import os
import secrets
import calendar
import time
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Request, Form, Depends, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import select, Session
from pydantic import BaseModel

# Import local modules
from src.ml_engine import extract_face_embedding, load_model, recognize_face
from src.liveness import analyze_liveness, choose_liveness_challenge
from src.database import engine, init_db, get_session, enroll_face_embedding
from src.table import User, SystemConfig, Log, FaceData

app = FastAPI(title="Sentinel Framework")
app.add_middleware(SessionMiddleware, secret_key="SUPER_SECRET_KEY")

app.mount("/static", StaticFiles(directory="src/static"), name="static")
templates = Jinja2Templates(directory="src/templates")
DEVELOPER_ACCESS_KEY = os.environ.get("SENTINEL_DEVELOPER_KEY", "dev-access")

# --- In-memory store for background job status ---
# In a production app, use Redis, Celery, or a database for this
jobs: Dict[str, Dict[str, Any]] = {}

# --- Project Directory & Dataset Masterfile Setup ---
# Assumes main.py is in the 'src' folder
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DATASETS_DIR = os.path.join(PROJECT_ROOT, "datasets")
DATASETS_MASTER_FILE = os.path.join(DATASETS_DIR, "datasets.json")

def _init_datasets_masterfile():
    """Ensure the datasets directory and masterfile exist."""
    os.makedirs(DATASETS_DIR, exist_ok=True)
    if not os.path.exists(DATASETS_MASTER_FILE):
        with open(DATASETS_MASTER_FILE, "w") as f:
            json.dump([], f)

def read_datasets_masterfile() -> List[Dict]:
    """Reads the list of registered datasets."""
    with open(DATASETS_MASTER_FILE, "r") as f:
        return json.load(f)

def write_datasets_masterfile(data: List[Dict]):
    """Writes to the list of registered datasets."""
    with open(DATASETS_MASTER_FILE, "w") as f:
        json.dump(data, f, indent=2)


class CnnTrainingRequest(BaseModel):
    model_type: str
    model_architecture: str
    dataset_path: str
    epochs: int
    batch_size: int
    learning_rate: float


# Placeholder for the actual training logic
def background_cnn_training_task(job_id: str, training_params: CnnTrainingRequest):
    """Simulates a background model training job."""
    jobs[job_id]["status"] = "running"
    
    total_epochs = training_params.epochs
    for epoch in range(1, total_epochs + 1):
        # Simulate work
        time.sleep(2)
        
        # Update progress and log
        progress = int((epoch / total_epochs) * 100)
        jobs[job_id]["progress"] = progress
        
        # Simulate log output
        loss = 1.0 / epoch
        accuracy = 1.0 - loss
        log_message = f"Epoch {epoch}/{total_epochs} - loss: {loss:.4f} - accuracy: {accuracy:.4f}\n"
        
        # Append to log
        if "log" not in jobs[job_id]:
            jobs[job_id]["log"] = ""
        jobs[job_id]["log"] += log_message
    
    jobs[job_id]["status"] = "completed"
    jobs[job_id]["progress"] = 100


class DataDiscoveryRequest(BaseModel):
    kaggle_dataset: str
    kaggle_api_key: str
    output_path: str


class DataImportRequest(BaseModel):
    source: str
    kaggle_dataset: str
    kaggle_api_key: str
    output_path: str
    real_folders: str
    spoof_folders: str
    split_ratio: str


# Placeholder for the actual discovery logic
def background_data_discovery_task(job_id: str, discovery_params: DataDiscoveryRequest):
    """Simulates downloading a dataset and discovering its structure."""
    jobs[job_id]["status"] = "running"
    
    # Stage 1: Downloading
    jobs[job_id]["log"] = f"Starting download for {discovery_params.kaggle_dataset}...\n"
    jobs[job_id]["progress"] = 10
    time.sleep(3) # Simulate download
    jobs[job_id]["log"] += "Download complete.\n"
    jobs[job_id]["progress"] = 50

    # Stage 2: Discovering structure
    jobs[job_id]["log"] += "Scanning folder structure...\n"
    time.sleep(2)
    
    # Simulate finding folders
    # In a real implementation, this would os.walk the output_path
    real_folders_found = ["real", "live_photos"]
    spoof_folders_found = ["spoof", "printed_attack", "replay_attack"]
    
    jobs[job_id]["log"] += f"Found 'Real' candidates: {real_folders_found}\\n"
    jobs[job_id]["log"] += f"Found 'Spoof' candidates: {spoof_folders_found}\\n"
    
    jobs[job_id]["status"] = "completed"
    jobs[job_id]["progress"] = 100
    jobs[job_id]["job_type"] = "discovery" # For the frontend to identify
    jobs[job_id]["result"] = {
        "real_folders": real_folders_found,
        "spoof_folders": spoof_folders_found,
    }


class BiometricAuthRequest(BaseModel):
    image_b64: str
    nonce: str
    frames_b64: Optional[List[str]] = None
    challenge: Optional[str] = None


class BiometricEnrollRequest(BaseModel):
    image_b64: str
    user_id: Optional[int] = None

# --- HELPER: GET CONFIG ---
def get_current_config(session: Session):
    return session.exec(select(SystemConfig)).first()


def record_log(session: Session, user_id: Optional[int], event_type: str, details: str):
    session.add(
        Log(
            user_id=user_id,
            event_type=event_type,
            details=details,
        )
    )
    session.commit()


def format_faceid_error(exc: Exception) -> str:
    message = str(exc).strip()
    lowered = message.lower()

    if "session.exec()" in lowered:
        return "Enrollment failed: database query helper mismatch. Please try again."

    if "model not loaded" in lowered or "face embedding model is unavailable" in lowered:
        return "Enrollment failed: face model is not ready yet. Please try again in a moment."

    if not message:
        return "Enrollment failed: an unexpected error occurred."

    return f"Enrollment failed: {message}"


def issue_biometric_nonce(request: Request):
    nonce = secrets.token_urlsafe(24)
    request.session["biometric_nonce"] = nonce
    return nonce


def consume_biometric_nonce(request: Request, nonce: str):
    stored_nonce = request.session.pop("biometric_nonce", None)
    return bool(stored_nonce and nonce and stored_nonce == nonce)


def consume_liveness_challenge(request: Request):
    return request.session.pop("liveness_challenge", None)


def has_admin_access(request: Request) -> bool:
    return bool(request.session.get("is_admin"))


def has_superuser_access(request: Request) -> bool:
    return bool(request.session.get("is_superuser"))


def has_developer_access(request: Request) -> bool:
    return bool(request.session.get("developer_access"))


def parse_log_timestamp(timestamp_value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(timestamp_value)
    except Exception:
        return None


def build_monthly_attendance_rows(logs: list[Log]):
    daily = {}
    for log in logs:
        timestamp = parse_log_timestamp(log.timestamp)
        if not timestamp:
            continue

        day_key = timestamp.date().isoformat()
        daily.setdefault(day_key, []).append(timestamp)

    rows = []
    for day_key in sorted(daily.keys()):
        punches = sorted(daily[day_key])
        rows.append(
            {
                "date": day_key,
                "punches": len(punches),
                "first_punch": punches[0].strftime("%I:%M %p"),
                "last_punch": punches[-1].strftime("%I:%M %p"),
            }
        )

    return rows

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
    load_model()
    _init_datasets_masterfile()

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    with Session(engine) as session:
        config = get_current_config(session)
        # Default fallback if DB is empty (edge case)
        sys_name = config.system_name if config else "Sentinel Framework"
        mode = config.deployment_mode if config else "gateway"

    # Redirect Kiosk Mode
    if mode == 'kiosk' and not request.session.get("is_admin"):
         return templates.TemplateResponse(
            request=request,
            name="kiosk_login.html",
            context={
                "request": request,
                "system_name": sys_name,
            },
        )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "user_id": request.session.get("user_id"),
            "is_admin": request.session.get("is_admin"),
            "system_name": sys_name,
        },
    )

# --- SETUP ---
@app.get("/setup", response_class=HTMLResponse)
def setup_get(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="setup.html",
        context={"request": request},
    )

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

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "request": request,
            "system_name": sys_name,
        },
    )

@app.post("/login", response_class=HTMLResponse)
def login_process(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    admin_key: Optional[str] = Form(""),
    admin_mode: Optional[str] = Form("0"),
    developer_key: Optional[str] = Form(""),
    session: Session = Depends(get_session),
):
    user = session.exec(select(User).where(User.username == username)).first()
    
    # Config for branding
    config = get_current_config(session)
    sys_name = config.system_name if config else "Sentinel"

    if not user or user.password_hash != password:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "request": request,
                "error": "Invalid credentials",
                "system_name": sys_name,
            },
        )
    
    requested_admin = admin_mode == "1" or bool((admin_key or "").strip())
    provided_admin_key = (admin_key or "").strip()
    admin_key_valid = bool(user.admin_key and provided_admin_key and provided_admin_key == user.admin_key)

    if requested_admin and not user.is_admin and not admin_key_valid:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "request": request,
                "error": "Admin key is required for privileged access.",
                "system_name": sys_name,
            },
        )

    is_privileged = user.is_admin or admin_key_valid

    provided_dev_key = (developer_key or "").strip()
    if provided_dev_key and provided_dev_key == DEVELOPER_ACCESS_KEY:
        request.session["developer_access"] = True
    else:
        request.session["developer_access"] = False

    request.session["user_id"] = user.id
    request.session["is_admin"] = is_privileged
    request.session["is_superuser"] = user.is_admin # Only root has this
    request.session["username"] = user.username
    request.session["full_name"] = user.full_name

    if is_privileged:
        return RedirectResponse(url="/admin", status_code=303)
    
    return RedirectResponse(url="/", status_code=303)


# --- DEVELOPER AREA ---


@app.get("/developer", response_class=HTMLResponse)
def developer_panel(request: Request):
    if not has_developer_access(request):
        return RedirectResponse(url="/login", status_code=303)

    with Session(engine) as session:
        config = get_current_config(session)
        current_mode = config.deployment_mode if config else "gateway"
        sys_name = config.system_name if config else "Sentinel"

    return templates.TemplateResponse(
        request=request,
        name="developer_panel.html",
        context={
            "request": request,
            "mode": current_mode,
            "system_name": sys_name,
            "is_superuser": has_superuser_access(request),
        },
    )


@app.get("/developer/cnn-training", response_class=HTMLResponse)
def developer_cnn_training(request: Request):
    if not has_developer_access(request):
        return RedirectResponse(url="/login", status_code=303)

    with Session(engine) as session:
        config = get_current_config(session)
        current_mode = config.deployment_mode if config else "gateway"
        sys_name = config.system_name if config else "Sentinel"

    return templates.TemplateResponse(
        request=request,
        name="developer_cnn_training.html",
        context={
            "request": request,
            "mode": current_mode,
            "system_name": sys_name,
            "is_superuser": has_superuser_access(request),
        },
    )


@app.get("/developer/data-import", response_class=HTMLResponse)
def developer_data_import(request: Request):
    if not has_developer_access(request):
        return RedirectResponse(url="/login", status_code=303)

    with Session(engine) as session:
        config = get_current_config(session)
        current_mode = config.deployment_mode if config else "gateway"
        sys_name = config.system_name if config else "Sentinel"

    return templates.TemplateResponse(
        request=request,
        name="developer_data_import.html",
        context={
            "request": request,
            "mode": current_mode,
            "system_name": sys_name,
            "is_superuser": has_superuser_access(request),
        },
    )


@app.post("/developer/cnn-training/start")
async def developer_start_cnn_training(
    background_tasks: BackgroundTasks,
    training_params: CnnTrainingRequest,
    request: Request,
):
    if not has_developer_access(request):
        raise HTTPException(status_code=403, detail="Developer access required")

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "id": job_id,
        "status": "queued",
        "progress": 0,
        "log": "Job is queued and waiting to start...",
    }
    
    # Add the long-running task to the background
    background_tasks.add_task(background_cnn_training_task, job_id, training_params)
    
    return JSONResponse(status_code=202, content={"job_id": job_id})


@app.get("/developer/jobs/{job_id}/status")
def developer_get_job_status(job_id: str, request: Request):
    if not has_developer_access(request):
        raise HTTPException(status_code=403, detail="Developer access required")

    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    return JSONResponse(content=job)
    

class DataRegistrationRequest(BaseModel):
    name: str
    dataset_type: str
    path: str
    mappings: Dict[str, List[str]]


@app.post("/api/datasets/register")
async def api_register_dataset(request: Request, payload: DataRegistrationRequest):
    if not has_developer_access(request):
        raise HTTPException(status_code=403, detail="Developer access required")
    
    datasets = read_datasets_masterfile()
    
    if any(d["name"] == payload.name for d in datasets):
        raise HTTPException(status_code=400, detail=f"Dataset name '{payload.name}' already exists.")

    new_dataset = {
        "id": str(uuid.uuid4()),
        "name": payload.name,
        "type": payload.dataset_type,
        "path": payload.path,
        "mappings": payload.mappings,
        "registered_at": datetime.now().isoformat()
    }
    
    datasets.append(new_dataset)
    write_datasets_masterfile(datasets)
    
    return JSONResponse(status_code=201, content=new_dataset)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
def user_settings(request: Request):
    if not request.session.get("user_id"):
        return RedirectResponse(url="/login", status_code=303)

    with Session(engine) as session:
        config = get_current_config(session)
        current_mode = config.deployment_mode if config else "gateway"
        sys_name = config.system_name if config else "Sentinel"
        user = session.exec(select(User).where(User.id == request.session.get("user_id"))).first()

    if not user:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    flash = request.session.pop("settings_flash", None)
    error = request.session.pop("settings_error", None)

    return templates.TemplateResponse(
        request=request,
        name="user_settings.html",
        context={
            "request": request,
            "mode": current_mode,
            "system_name": sys_name,
            "user": user,
            "flash": flash,
            "error": error,
        },
    )

@app.post("/settings")
async def user_settings_update(request: Request, session: Session = Depends(get_session)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    user = session.exec(select(User).where(User.id == user_id)).first()
    if not user:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    form_data = await request.form()
    full_name = (form_data.get("full_name") or "").strip()
    email = (form_data.get("email") or "").strip()
    current_password = form_data.get("current_password") or ""
    new_password = form_data.get("new_password") or ""
    confirm_password = form_data.get("confirm_password") or ""

    if current_password != user.password_hash:
        request.session["settings_error"] = "Current password is incorrect."
        return RedirectResponse(url="/settings", status_code=303)

    user.full_name = full_name or None
    user.email = email or None

    if new_password:
        if new_password != confirm_password:
            request.session["settings_error"] = "New password and confirmation do not match."
            return RedirectResponse(url="/settings", status_code=303)
        user.password_hash = new_password

    session.add(user)
    session.commit()

    request.session["full_name"] = user.full_name
    request.session["settings_flash"] = "Your profile was updated successfully."
    return RedirectResponse(url="/settings", status_code=303)


@app.get("/about", response_class=HTMLResponse)
def about_page(request: Request):
    if not request.session.get("user_id"):
        return RedirectResponse(url="/login", status_code=303)

    with Session(engine) as session:
        config = get_current_config(session)
        current_mode = config.deployment_mode if config else "gateway"
        sys_name = config.system_name if config else "Sentinel"

    return templates.TemplateResponse(
        request=request,
        name="about.html",
        context={
            "request": request,
            "mode": current_mode,
            "system_name": sys_name,
        },
    )

# --- ADMIN ---
@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    if not request.session.get("is_admin"):
        return RedirectResponse(url="/login")
        
    with Session(engine) as session:
        config = get_current_config(session)
        current_mode = config.deployment_mode if config else "gateway"
        sys_name = config.system_name if config else "Sentinel"
        users = session.exec(select(User)).all()
        face_rows = session.exec(select(FaceData.user_id)).all()
        blocked_events = session.exec(
            select(Log).where(Log.event_type.in_(["FACEID_UNKNOWN", "FACEID_REPLAY_BLOCKED", "FACEID_ADMIN_BLOCKED"]))
        ).all()

    total_users = len(users)
    admin_users = sum(1 for user in users if user.is_admin or (user.admin_key is not None and user.admin_key != ""))
    limited_admins = sum(1 for user in users if not user.is_admin and user.admin_key is not None and user.admin_key != "")
    with_face = len(set(face_rows))
    without_face = max(0, total_users - with_face)
    recent_users = sorted(users, key=lambda u: u.created_at, reverse=True)[:8]
    blocked_attempts = len(blocked_events)

    return templates.TemplateResponse(
        request=request,
        name="admin_panel.html",
        context={
            "request": request,
            "mode": current_mode,
            "system_name": sys_name,
            "user": request.session.get("full_name"),
            "is_superuser": request.session.get("is_superuser"),  # For hiding the Key Manager
            "dashboard": {
                "total_users": total_users,
                "admin_users": admin_users,
                "limited_admins": limited_admins,
                "with_face": with_face,
                "without_face": without_face,
                "blocked_attempts": blocked_attempts,
            },
            "recent_users": recent_users,
            "security_alert": not request.session.get("is_superuser"),
        },
    )


@app.get("/admin/accounts")
def admin_accounts_redirect(request: Request):
    return RedirectResponse(url="/admin/biometrics", status_code=303)


@app.get("/admin/biometrics", response_class=HTMLResponse)
def admin_biometrics(request: Request):
    if not request.session.get("is_admin"):
        return RedirectResponse(url="/login", status_code=303)

    with Session(engine) as session:
        config = get_current_config(session)
        current_mode = config.deployment_mode if config else "gateway"
        sys_name = config.system_name if config else "Sentinel"
        users = session.exec(select(User)).all()
        face_rows = session.exec(select(FaceData.user_id)).all()

    face_user_ids = set(face_rows)
    rows = []
    for user in users:
        rows.append(
            {
                "id": user.id,
                "username": user.username,
                "full_name": user.full_name or "-",
                "is_admin": user.is_admin or (user.admin_key is not None and user.admin_key != ""),
                "face_ready": user.id in face_user_ids,
                "created_at": user.created_at,
            }
        )

    rows.sort(key=lambda item: item["username"].lower())

    return templates.TemplateResponse(
        request=request,
        name="admin_biometrics.html",
        context={
            "request": request,
            "mode": current_mode,
            "system_name": sys_name,
            "users": rows,
            "total_users": len(rows),
            "face_enrolled": len(face_user_ids),
            "face_missing": max(0, len(rows) - len(face_user_ids)),
            "is_superuser": request.session.get("is_superuser"),
        },
    )


@app.get("/admin/stocks", response_class=HTMLResponse)
def admin_stocks(request: Request):
    if not has_superuser_access(request):
        return RedirectResponse(url="/admin", status_code=303)

    with Session(engine) as session:
        config = get_current_config(session)
        current_mode = config.deployment_mode if config else "gateway"
        sys_name = config.system_name if config else "Sentinel"
        users = session.exec(select(User)).all()
        face_rows = session.exec(select(FaceData.user_id)).all()
        attendance_logs = session.exec(select(Log).where(Log.event_type == "FACEID_SUCCESS")).all()

    face_user_ids = set(face_rows)
    current_month = datetime.now().month
    current_year = datetime.now().year
    monthly_logs = []
    for log in attendance_logs:
        timestamp = parse_log_timestamp(log.timestamp)
        if timestamp and timestamp.year == current_year and timestamp.month == current_month:
            monthly_logs.append(log)

    hr_rows = []
    for user in users:
        hr_rows.append(
            {
                "id": user.id,
                "username": user.username,
                "full_name": user.full_name or "-",
                "face_ready": user.id in face_user_ids,
                "created_at": user.created_at,
            }
        )

    hr_rows.sort(key=lambda item: item["username"].lower())

    return templates.TemplateResponse(
        request=request,
        name="admin_stocks.html",
        context={
            "request": request,
            "mode": current_mode,
            "system_name": sys_name,
            "inventory_ready": current_mode == "kiosk",
            "hr_mode": current_mode == "attendance",
            "hr_users": hr_rows,
            "total_users": len(hr_rows),
            "face_enrolled": len(face_user_ids),
            "face_missing": max(0, len(hr_rows) - len(face_user_ids)),
            "monthly_attendance_punches": len(monthly_logs),
            "is_superuser": request.session.get("is_superuser"),
        },
    )


@app.get("/attendance/report", response_class=HTMLResponse)
def attendance_report(
    request: Request,
    user_id: Optional[int] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
):
    if not request.session.get("user_id"):
        return RedirectResponse(url="/login", status_code=303)

    session_user_id = request.session.get("user_id")
    is_admin = bool(request.session.get("is_admin"))
    target_user_id = user_id if user_id is not None else session_user_id

    if target_user_id != session_user_id and not is_admin:
        return RedirectResponse(url="/settings", status_code=303)

    if not is_admin and target_user_id == session_user_id:
        return RedirectResponse(url="/settings", status_code=303)

    today = datetime.now()
    report_year = year or today.year
    report_month = month or today.month

    if not is_admin:
        return RedirectResponse(url="/settings", status_code=303)

    with Session(engine) as db_session:
        config = get_current_config(db_session)
        current_mode = config.deployment_mode if config else "gateway"
        sys_name = config.system_name if config else "Sentinel"
        report_user = db_session.exec(select(User).where(User.id == target_user_id)).first()
        all_users = db_session.exec(select(User)).all() if is_admin else []
        face_rows = db_session.exec(select(FaceData.user_id)).all()
        logs = db_session.exec(
            select(Log).where(Log.user_id == target_user_id, Log.event_type == "FACEID_SUCCESS")
        ).all()

    if not report_user:
        return RedirectResponse(url="/settings", status_code=303)

    month_logs = []
    for log in logs:
        timestamp = parse_log_timestamp(log.timestamp)
        if timestamp and timestamp.year == report_year and timestamp.month == report_month:
            month_logs.append(log)

    month_logs.sort(key=lambda item: item.timestamp)
    attendance_rows = build_monthly_attendance_rows(month_logs)
    month_name = calendar.month_name[report_month]

    return templates.TemplateResponse(
        request=request,
        name="attendance_report.html",
        context={
            "request": request,
            "mode": current_mode,
            "system_name": sys_name,
            "report_user": report_user,
            "attendance_rows": attendance_rows,
            "total_punches": len(month_logs),
            "work_days": len(attendance_rows),
            "report_year": report_year,
            "report_month": report_month,
            "month_name": month_name,
            "is_admin": is_admin,
            "users": all_users,
            "face_user_ids": set(face_rows),
        },
    )


@app.get("/admin/keys", response_class=HTMLResponse)
def admin_keys(request: Request):
    if not has_superuser_access(request):
        return RedirectResponse(url="/admin", status_code=303)

    with Session(engine) as session:
        config = get_current_config(session)
        current_mode = config.deployment_mode if config else "gateway"
        sys_name = config.system_name if config else "Sentinel"
        users = session.exec(select(User)).all()

    rows = []
    for user in users:
        rows.append(
            {
                "id": user.id,
                "username": user.username,
                "full_name": user.full_name or "-",
                "is_admin": user.is_admin,
                "admin_key": user.admin_key or "",
                "created_at": user.created_at,
            }
        )

    rows.sort(key=lambda item: item["username"].lower())

    flash = request.session.pop("admin_users_flash", None)
    error = request.session.pop("admin_users_error", None)

    return templates.TemplateResponse(
        request=request,
        name="admin_keys.html",
        context={
            "request": request,
            "mode": current_mode,
            "system_name": sys_name,
            "users": rows,
            "total_keys": sum(1 for row in rows if row["admin_key"]),
            "is_superuser": True,
            "flash": flash,
            "error": error,
        },
    )


@app.get("/admin/faceid-debug", response_class=HTMLResponse)
def admin_faceid_debug(request: Request):
    if not has_superuser_access(request):
        return RedirectResponse(url="/admin", status_code=303)

    with Session(engine) as session:
        config = get_current_config(session)
        current_mode = config.deployment_mode if config else "gateway"
        sys_name = config.system_name if config else "Sentinel"
        config_data = json.loads(config.config_json) if config and config.config_json else {}
        users = session.exec(select(User)).all()
        face_rows = session.exec(select(FaceData.user_id)).all()
        face_logs = session.exec(select(Log).where(Log.event_type.like("FACEID%"))).all()

    face_user_ids = set(face_rows)
    user_rows = []
    for user in users:
        user_rows.append(
            {
                "id": user.id,
                "username": user.username,
                "full_name": user.full_name or "-",
                "face_ready": user.id in face_user_ids,
            }
        )

    face_logs.sort(key=lambda item: item.timestamp, reverse=True)

    return templates.TemplateResponse(
        request=request,
        name="admin_faceid_debug.html",
        context={
            "request": request,
            "mode": current_mode,
            "system_name": sys_name,
            "config_data": config_data,
            "users": user_rows,
            "face_logs": face_logs[:100],
            "total_logs": len(face_logs),
            "is_superuser": True,
        },
    )


@app.post("/admin/keys/{user_id}/update")
def admin_keys_update(
    request: Request,
    user_id: int,
    admin_key: Optional[str] = Form(""),
    session: Session = Depends(get_session),
):
    if not has_superuser_access(request):
        return RedirectResponse(url="/admin", status_code=303)

    user = session.exec(select(User).where(User.id == user_id)).first()
    if not user:
        request.session["admin_users_error"] = "User not found."
        return RedirectResponse(url="/admin/keys", status_code=303)

    user.admin_key = (admin_key or "").strip() or None
    session.add(user)
    session.commit()

    request.session["admin_users_flash"] = f"Admin key updated for {user.username}."
    return RedirectResponse(url="/admin/keys", status_code=303)


@app.post("/admin/keys/{user_id}/clear")
def admin_keys_clear(request: Request, user_id: int, session: Session = Depends(get_session)):
    if not has_superuser_access(request):
        return RedirectResponse(url="/admin", status_code=303)

    user = session.exec(select(User).where(User.id == user_id)).first()
    if not user:
        request.session["admin_users_error"] = "User not found."
        return RedirectResponse(url="/admin/keys", status_code=303)

    user.admin_key = None
    session.add(user)
    session.commit()

    request.session["admin_users_flash"] = f"Admin key cleared for {user.username}."
    return RedirectResponse(url="/admin/keys", status_code=303)


@app.get("/admin/settings", response_class=HTMLResponse)
def admin_settings(request: Request):
    if not has_superuser_access(request):
        return RedirectResponse(url="/login", status_code=303)

    with Session(engine) as session:
        config = get_current_config(session)
        current_mode = config.deployment_mode if config else "gateway"
        sys_name = config.system_name if config else "Sentinel"
        config_data = json.loads(config.config_json) if config and config.config_json else {}

    flash = request.session.pop("admin_settings_flash", None)
    error = request.session.pop("admin_settings_error", None)

    return templates.TemplateResponse(
        request=request,
        name="admin_settings.html",
        context={
            "request": request,
            "mode": current_mode,
            "system_name": sys_name,
            "config_data": config_data,
            "flash": flash,
            "error": error,
            "is_superuser": request.session.get("is_superuser"),
        },
    )


@app.post("/admin/settings")
async def admin_settings_update(request: Request, session: Session = Depends(get_session)):
    if not has_superuser_access(request):
        return RedirectResponse(url="/login", status_code=303)

    form_data = await request.form()
    system_name = (form_data.get("system_name") or "").strip() or "Sentinel Framework"
    deployment_mode = form_data.get("deployment_mode") or "gateway"
    face_threshold = (form_data.get("face_match_threshold") or "").strip()
    face_interval = (form_data.get("face_capture_interval") or "").strip()

    config = get_current_config(session)
    existing_config = json.loads(config.config_json) if config and config.config_json else {}

    existing_config.update(
        {
            "face_match_threshold": face_threshold or existing_config.get("face_match_threshold", "0.95"),
            "face_capture_interval": face_interval or existing_config.get("face_capture_interval", "1500"),
        }
    )

    if config:
        config.system_name = system_name
        config.deployment_mode = deployment_mode
        config.config_json = json.dumps(existing_config)
        session.add(config)
    else:
        config = SystemConfig(
            system_name=system_name,
            deployment_mode=deployment_mode,
            config_json=json.dumps(existing_config),
            is_setup_complete=True,
        )
        session.add(config)

    session.commit()

    request.session["admin_settings_flash"] = "Sentinel settings updated successfully."
    return RedirectResponse(url="/admin/settings", status_code=303)


@app.get("/admin/audit", response_class=HTMLResponse)
def admin_audit(request: Request):
    if not has_superuser_access(request):
        return RedirectResponse(url="/login", status_code=303)

    with Session(engine) as session:
        config = get_current_config(session)
        current_mode = config.deployment_mode if config else "gateway"
        sys_name = config.system_name if config else "Sentinel"
        logs = session.exec(select(Log)).all()

    logs.sort(key=lambda item: item.timestamp, reverse=True)

    return templates.TemplateResponse(
        request=request,
        name="admin_audit.html",
        context={
            "request": request,
            "mode": current_mode,
            "system_name": sys_name,
            "logs": logs,
            "total_logs": len(logs),
            "latest_log": logs[0] if logs else None,
            "is_superuser": request.session.get("is_superuser"),
        },
    )
@app.get("/admin/sync")
def admin_sync_placeholder(request: Request):
    if not request.session.get("is_admin"):
        return RedirectResponse(url="/login", status_code=303)

    request.session["admin_users_flash"] = "Sync placeholder executed. Connect your gateway backend here."
    return RedirectResponse(url="/admin/users", status_code=303)


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request):
    if not request.session.get("is_admin"):
        return RedirectResponse(url="/login", status_code=303)

    with Session(engine) as session:
        config = get_current_config(session)
        current_mode = config.deployment_mode if config else "gateway"
        sys_name = config.system_name if config else "Sentinel"
        users = session.exec(select(User)).all()
        face_rows = session.exec(select(FaceData.user_id)).all()

    face_user_ids = set(face_rows)
    rows = []
    for user in users:
        rows.append(
            {
                "id": user.id,
                "username": user.username,
                "full_name": user.full_name or "-",
                "is_admin": user.is_admin or (user.admin_key is not None and user.admin_key != ""),
                "face_ready": user.id in face_user_ids,
                "created_at": user.created_at,
            }
        )

    rows.sort(key=lambda item: item["username"].lower())

    flash = request.session.pop("admin_users_flash", None)
    error = request.session.pop("admin_users_error", None)
    return templates.TemplateResponse(
        request=request,
        name="admin_users.html",
        context={
            "request": request,
            "mode": current_mode,
            "system_name": sys_name,
            "users": rows,
            "flash": flash,
            "error": error,
            "is_superuser": request.session.get("is_superuser"),
            "current_user_id": request.session.get("user_id"),
        },
    )


@app.post("/admin/users/create")
def admin_users_create(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(""),
    is_admin: Optional[str] = Form(None),
    admin_key: Optional[str] = Form(""),
    session: Session = Depends(get_session),
):
    if not request.session.get("is_admin"):
        return RedirectResponse(url="/login", status_code=303)

    username_clean = username.strip()
    if not username_clean or not password:
        request.session["admin_users_error"] = "Username and password are required."
        return RedirectResponse(url="/admin/users", status_code=303)

    existing = session.exec(select(User).where(User.username == username_clean)).first()
    if existing:
        request.session["admin_users_error"] = f"Username '{username_clean}' already exists."
        return RedirectResponse(url="/admin/users", status_code=303)

    user = User(
        username=username_clean,
        password_hash=password,
        full_name=full_name.strip() or None,
        is_admin=is_admin is not None,
        admin_key=(admin_key or "").strip() or None,
    )
    session.add(user)
    session.commit()

    request.session["admin_users_flash"] = f"User '{username_clean}' created successfully."
    return RedirectResponse(url="/admin/users", status_code=303)


@app.post("/admin/users/{user_id}/delete")
def admin_users_delete(request: Request, user_id: int, session: Session = Depends(get_session)):
    if not has_superuser_access(request):
        return RedirectResponse(url="/login", status_code=303)

    if request.session.get("user_id") == user_id:
        request.session["admin_users_error"] = "You cannot delete your own active account."
        return RedirectResponse(url="/admin/users", status_code=303)

    user = session.exec(select(User).where(User.id == user_id)).first()
    if not user:
        request.session["admin_users_error"] = "User not found."
        return RedirectResponse(url="/admin/users", status_code=303)

    session.delete(user)
    session.commit()

    request.session["admin_users_flash"] = f"User '{user.username}' deleted."
    return RedirectResponse(url="/admin/users", status_code=303)

# --- BIOMETRICS ---
@app.get("/scan", response_class=HTMLResponse)
def scan_view(request: Request):
    with Session(engine) as session:
        config = get_current_config(session)
        current_mode = config.deployment_mode if config else "gateway"
        sys_name = config.system_name if config else "Sentinel"
        config_data = json.loads(config.config_json) if config and config.config_json else {}
        face_capture_interval = int(config_data.get("face_capture_interval", 1500))

    return templates.TemplateResponse(
        request=request,
        name="scan.html",
        context={
            "request": request,
            "mode": current_mode,
            "system_name": sys_name,
            "face_capture_interval": face_capture_interval,
        },
    )

@app.get("/api/biometric-challenge")
def api_biometric_challenge(request: Request):
    nonce = issue_biometric_nonce(request)
    challenge_payload = choose_liveness_challenge()
    request.session["liveness_challenge"] = challenge_payload["challenge"]
    return {"nonce": nonce, **challenge_payload}


@app.post("/api/biometric-enroll")
async def api_biometric_enroll(
    payload: BiometricEnrollRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    session_user_id = request.session.get("user_id")
    if not session_user_id:
        raise HTTPException(status_code=401, detail="Login required")

    target_user_id = payload.user_id or session_user_id
    if target_user_id != session_user_id and not request.session.get("is_admin"):
        raise HTTPException(status_code=403, detail="Not allowed to enroll for another user")

    try:
        embedding = extract_face_embedding(payload.image_b64)
        face_data = enroll_face_embedding(session, target_user_id, embedding)
        session.commit()
    except Exception as exc:
        session.rollback()
        record_log(session, session_user_id, "FACEID_ENROLL_ERROR", str(exc))
        raise HTTPException(status_code=400, detail=format_faceid_error(exc))

    record_log(
        session,
        target_user_id,
        "FACEID_ENROLL_SUCCESS",
        f"Face enrolled for user_id={target_user_id} using face_data_id={face_data.id}",
    )
    return {"status": "success", "face_data_id": face_data.id, "user_id": target_user_id}


@app.post("/api/biometric-auth")
async def api_biometric_auth(
    payload: BiometricAuthRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    if not consume_biometric_nonce(request, payload.nonce):
        record_log(session, request.session.get("user_id"), "FACEID_REPLAY_BLOCKED", "Invalid or expired biometric nonce")
        raise HTTPException(status_code=401, detail="Invalid or expired biometric challenge")

    challenge = payload.challenge or consume_liveness_challenge(request)
    frames_b64 = payload.frames_b64 or [payload.image_b64]
    liveness_result = analyze_liveness(frames_b64, challenge)
    if not liveness_result["passed"]:
        reason_text = "; ".join(liveness_result["reasons"]) if liveness_result["reasons"] else "liveness confidence is too low"
        record_log(
            session,
            request.session.get("user_id"),
            "FACEID_LIVENESS_BLOCKED",
            f"Liveness blocked ({liveness_result['model_source']}): {reason_text}",
        )
        return {
            "status": "liveness_failed",
            "message": "Liveness check failed. Please blink or move naturally and try again.",
            "detail": reason_text,
        }

    result = recognize_face(payload.image_b64)
    if result["match"]:
        matched_user = session.exec(select(User).where(User.id == result["user_id"])).first()
        if not matched_user:
            record_log(session, request.session.get("user_id"), "FACEID_UNKNOWN", "Matched face did not map to a known user")
            return {"status": "unknown"}

        is_privileged_user = matched_user.is_admin or bool(matched_user.admin_key)
        if is_privileged_user:
            request.session["user_id"] = matched_user.id
            request.session["username"] = matched_user.username
            request.session["full_name"] = matched_user.full_name or matched_user.username
            request.session["is_admin"] = False
            request.session["is_superuser"] = False
            record_log(
                session,
                matched_user.id,
                "FACEID_ADMIN_BLOCKED",
                f"FaceID login blocked for privileged account {matched_user.username}; admin key login required",
            )
            return {"status": "admin_required", "message": "Privileged accounts must sign in with password and admin key."}

        request.session["user_id"] = matched_user.id
        request.session["username"] = matched_user.username
        request.session["full_name"] = matched_user.full_name or matched_user.username
        request.session["is_admin"] = False
        request.session["is_superuser"] = False
        record_log(
            session,
            matched_user.id,
            "FACEID_SUCCESS",
            f"FaceID matched {matched_user.full_name or matched_user.username} with confidence {result.get('confidence', 0):.2f}",
        )
        return {"status": "success", "user": matched_user.full_name or matched_user.username}

    record_log(
        session,
        request.session.get("user_id"),
        "FACEID_UNKNOWN",
        result.get("error", "FaceID frame did not match any enrolled user"),
    )
    return {"status": "unknown"}

@app.get("/api/fs/ls")
async def api_list_directory(request: Request, path: str = "."):
    if not has_developer_access(request):
        raise HTTPException(status_code=403, detail="Developer access required")

    try:
        safe_root = os.path.realpath(PROJECT_ROOT)
        requested_path = os.path.realpath(os.path.join(safe_root, path))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path format.")

    if not requested_path.startswith(safe_root):
        raise HTTPException(status_code=403, detail="Access denied: Path is outside the project directory.")

    if not os.path.isdir(requested_path):
        raise HTTPException(status_code=404, detail="Directory not found.")

    try:
        items = os.listdir(requested_path)
        dirs, files = [], []
        for item in items:
            if os.path.isdir(os.path.join(requested_path, item)):
                dirs.append(item)
            else:
                files.append(item)
        
        parent = None
        if requested_path != safe_root:
            parent_path = os.path.dirname(requested_path)
            parent = os.path.relpath(parent_path, safe_root)

        return JSONResponse({
            "path": os.path.relpath(requested_path, safe_root),
            "parent": parent,
            "dirs": sorted(dirs),
            "files": sorted(files),
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read directory: {e}")


@app.get("/api/fs/scan")
async def api_scan_directory_for_subdirs(request: Request, path: str):
    """Scans a given directory path and returns a list of its sub-directories."""
    if not has_developer_access(request):
        raise HTTPException(status_code=403, detail="Developer access required")

    try:
        safe_root = os.path.realpath(PROJECT_ROOT)
        target_path = os.path.realpath(os.path.join(safe_root, path))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path format.")

    if not target_path.startswith(safe_root):
         raise HTTPException(status_code=403, detail="Access denied: Path is outside the project directory.")
    
    if not os.path.isdir(target_path):
        return JSONResponse({"path": path, "sub_dirs": [], "error": "Path is not a valid directory."})

    try:
        sub_dirs = [d for d in os.listdir(target_path) if os.path.isdir(os.path.join(target_path, d))]
        return JSONResponse({"path": path, "sub_dirs": sorted(sub_dirs)})
    except Exception as e:
        return JSONResponse({"path": path, "sub_dirs": [], "error": f"Failed to scan directory: {e}"})


@app.get("/api/datasets/list")
async def api_list_datasets(request: Request):
    if not has_developer_access(request):
        raise HTTPException(status_code=403, detail="Developer access required")
    return JSONResponse(read_datasets_masterfile())