import uuid
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/demo", tags=["demo"])

# Initialize an in-memory "DB" using pandas
cols = [
    "id", "name", "email", "api_token", "wa_key",
    "wa_notif", "wa_number", "wa_verified", "mimic_user",
]
df = pd.DataFrame(columns=cols)
next_id = 1

# Simple settings store
settings = {
    "enable_agent": False,
    "enable_create_dummy_alert": False,
    "enable_send_alert": False,
}

# Pydantic models
class CreateUser(BaseModel):
    name: str
    email: str | None = None
    verified: bool = False
    wa_number: str | None = None
    mimic_user: str | None = "None"

class ApplySettings(BaseModel):
    enable_agent: bool
    enable_create_dummy_alert: bool
    enable_send_alert: bool

# Helpers
def df_to_list():
    return df.to_dict(orient="records")

# Routes
@router.get("/users")
def get_users():
    return df_to_list()

@router.post("/users")
def create_user(payload: CreateUser):
    global df, next_id
    mu = payload.mimic_user or "None"
    if mu != "None":
        taken = df[df["mimic_user"] == mu]
        if not taken.empty:
            raise HTTPException(status_code=409, detail="mimic_user already taken")

    if payload.verified and not payload.wa_number:
        raise HTTPException(status_code=400, detail="verified users must provide wa_number")

    new = {
        "id": next_id,
        "name": payload.name,
        "email": payload.email or f"{payload.name.lower().replace(' ','.')}@example.com",
        "api_token": str(uuid.uuid4()),
        "wa_key": None,
        "wa_notif": 1 if payload.verified else 0,
        "wa_number": payload.wa_number or "",
        "wa_verified": 1 if payload.verified else 0,
        "mimic_user": mu,
    }
    df = pd.concat([df, pd.DataFrame([new])], ignore_index=True)
    next_id += 1
    return {"ok": True, "user": new}

@router.post("/users/{user_id}/subscribe")
def subscribe_user(user_id: int):
    global df
    idx = df.index[df["id"] == user_id]
    if idx.empty:
        raise HTTPException(status_code=404, detail="user not found")
    idx = idx[0]
    key = str(uuid.uuid4())[:8]
    df.at[idx, "wa_key"] = key
    return {"ok": True, "key": key, "bot_number": "6285850434383"}

@router.post("/users/{user_id}/verify")
def verify_user(user_id: int):
    global df
    idx = df.index[df["id"] == user_id]
    if idx.empty:
        raise HTTPException(status_code=404, detail="user not found")
    idx = idx[0]
    df.at[idx, "wa_verified"] = 1
    df.at[idx, "wa_notif"] = 1
    return {"ok": True}

@router.post("/users/{user_id}/toggle_notif")
def toggle_notif(user_id: int):
    global df
    idx = df.index[df["id"] == user_id]
    if idx.empty:
        raise HTTPException(status_code=404, detail="user not found")
    idx = idx[0]
    current = int(df.at[idx, "wa_notif"]) if pd.notna(df.at[idx, "wa_notif"]) else 0
    df.at[idx, "wa_notif"] = 0 if current == 1 else 1
    return {"ok": True, "wa_notif": int(df.at[idx, "wa_notif"])}

@router.post("/users/{user_id}/unsubscribe")
def unsubscribe_user(user_id: int):
    global df
    idx = df.index[df["id"] == user_id]
    if idx.empty:
        raise HTTPException(status_code=404, detail="user not found")
    idx = idx[0]
    df.at[idx, "wa_notif"] = 0
    df.at[idx, "wa_verified"] = 0
    df.at[idx, "wa_key"] = None
    return {"ok": True}

@router.post("/users/{user_id}/delete")
def delete_user(user_id: int):
    global df
    idx = df.index[df["id"] == user_id]
    if idx.empty:
        raise HTTPException(status_code=404, detail="user not found")
    df = df.drop(idx).reset_index(drop=True)
    return {"ok": True}

@router.get("/settings")
def get_settings():
    return settings

@router.post("/settings")
def apply_settings(payload: ApplySettings):
    settings["enable_agent"] = payload.enable_agent
    settings["enable_create_dummy_alert"] = payload.enable_create_dummy_alert
    settings["enable_send_alert"] = payload.enable_send_alert
    return {"ok": True, "settings": settings}
