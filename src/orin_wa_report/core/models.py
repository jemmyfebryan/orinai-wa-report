from typing import Optional, Literal, Dict

from pydantic import BaseModel, RootModel, Field

class SendMessageRequest(BaseModel):
    to: str       # phone number, e.g. "1234567890@c.us"
    to_fallback: Optional[str] = None
    message: str  # message text

class SendFileRequest(BaseModel):
    to: str
    to_fallback: Optional[str] = None
    file: str # This is the base64 DataURL or Path
    filename: str
    caption: str

class VerifyUserResponseData(BaseModel):
    key: str = Field(
        ...,
        description="Kunci verifikasi WhatsApp"
    )
    bot_number: str = Field(
        ...,
        description="Nomor WhatsApp CS Orin untuk verifikasi"
    )
    wa_url: str = Field(
        ...,
        description="URL yang diberikan ke user untuk verifikasi melalui WhatsApp"
    )

class VerifyUserResponse(BaseModel):
    data: Optional[VerifyUserResponseData] = Field(None, description="Objek data hasil verifikasi user")
    ok: bool = Field(..., description="Status request (true/false)")
    status: str = Field(..., description="Status request (success/error)")
    message: str = Field(..., description="Pesan deskriptif hasil request")

    model_config = {
        "json_schema_extra": {
            "example": {
                "data": {
                    "key": "2K3KSADJ991JA",
                    "bot_number": "62123123123",
                    "wa_url": "https://wa.me/{BOT_PHONE_NUMBER}?text=..."
                },
                "ok": True,
                "status": "success",
                "message": "Successfully generating wa_url"
            }
        }
    }
    
verify_user_response_500 = {
    "model": VerifyUserResponse,
    "description": "Internal Server Error",
    "content": {
        "application/json": {
            "example": {
                "data": None,
                "ok": False,
                "status": "error",
                "message": "Error when verifying user: error_reason",
            }
        }
    }
}

class GetUserVerificationResponseData(BaseModel):
    is_wa_verified: bool = Field(
        ...,
        description="Apakah user terverifikasi wa atau tidak"
    )

class GetUserVerificationResponse(BaseModel):
    data: Optional[GetUserVerificationResponseData] = Field(None, description="Objek data hasil verifikasi user")
    ok: bool = Field(..., description="Status request (true/false)")
    status: str = Field(..., description="Status request (success/error)")
    message: str = Field(..., description="Pesan deskriptif hasil request")

    model_config = {
        "json_schema_extra": {
            "example": {
                "data": {
                    "is_wa_verified": True
                },
                "ok": True,
                "status": "success",
                "message": "Verification fetched successfully"
            }
        }
    }
    
get_user_verification_response_500 = {
    "model": GetUserVerificationResponse,
    "description": "Internal Server Error",
    "content": {
        "application/json": {
            "example": {
                "data": None,
                "ok": False,
                "status": "error",
                "message": "Error when fetch user verification: error_reason",
            }
        }
    }
}

class UnsubscribeUserResponse(BaseModel):
    ok: bool = Field(..., description="Status request (true/false)")
    status: str = Field(..., description="Status request (success/error)")
    message: str = Field(..., description="Pesan deskriptif hasil request")

    model_config = {
        "json_schema_extra": {
            "example": {
                "ok": True,
                "status": "success",
                "message": "Successfully unsubscribe user."
            }
        }
    }
 
unsubscribe_user_response_500 = {
    "model": GetUserVerificationResponse,
    "description": "Internal Server Error",
    "content": {
        "application/json": {
            "example": {
                "ok": False,
                "status": "error",
                "message": "Error when unsubscribe user: error_reason",
            }
        }
    }
}


# Toggle Notifications
class GetToggleNotificationResponseData(BaseModel):
    is_toggle_on: bool = Field(
        ...,
        description="Apakah user menyalakan notifikasi alert atau tidak"
    )

class GetToggleNotificationResponse(BaseModel):
    data: Optional[GetToggleNotificationResponseData] = Field(None, description="Objek data hasil toggle notifikasi user")
    ok: bool = Field(..., description="Status request (true/false)")
    status: str = Field(..., description="Status request (success/error)")
    message: str = Field(..., description="Pesan deskriptif hasil request")

    model_config = {
        "json_schema_extra": {
            "example": {
                "data": {
                    "is_toggle_on": True
                },
                "ok": True,
                "status": "success",
                "message": "Verification fetched successfully"
            }
        }
    }
    
get_toggle_notification_response_500 = {
    "model": GetToggleNotificationResponse,
    "description": "Internal Server Error",
    "content": {
        "application/json": {
            "example": {
                "data": None,
                "ok": False,
                "status": "error",
                "message": "Error when toggle notification: error_reason",
            }
        }
    }
}

class PutToggleNotificationRequest(BaseModel):
    is_toggle_on: bool = Field(..., description="Set toggle notification to On/Off")

class PutToggleNotificationResponseData(BaseModel):
    is_toggle_on: bool = Field(
        ...,
        description="Value notifikasi alert user yang ingin di-update"
    )

class PutToggleNotificationResponse(BaseModel):
    data: Optional[PutToggleNotificationResponseData] = Field(None, description="Objek data hasil toggle notifikasi user")
    ok: bool = Field(..., description="Status request (true/false)")
    status: str = Field(..., description="Status request (success/error)")
    message: str = Field(..., description="Pesan deskriptif hasil request")

    model_config = {
        "json_schema_extra": {
            "example": {
                "data": {
                    "is_toggle_on": True
                },
                "ok": True,
                "status": "success",
                "message": "Verification fetched successfully"
            }
        }
    }
    
put_toggle_notification_response_500 = {
    "model": PutToggleNotificationResponse,
    "description": "Internal Server Error",
    "content": {
        "application/json": {
            "example": {
                "data": None,
                "ok": False,
                "status": "error",
                "message": "Error when toggle notification: error_reason",
            }
        }
    }
}

# User Alert Settings
# class GetUserAlertSettingsResponseData(BaseModel):
#     notif_{setting}: str = Field(
#         ...,
#         description="Apakah alert user untuk {setting} aktif/tidak"
#     )

class GetUserAlertSettingsResponse(BaseModel):
    data: Optional[Dict[str, bool]] = Field(None, description="Objek data hasil alert settings user")
    ok: bool = Field(..., description="Status request (true/false)")
    status: str = Field(..., description="Status request (success/error)")
    message: str = Field(..., description="Pesan deskriptif hasil request")

    model_config = {
        "json_schema_extra": {
            "example": {
                "data": {
                    "notif_speed_alert": True,
                    "notif_geofence_inside": True,
                    "notif_geofence_outside": True,
                    "notif_cut_off": True,
                    "notif_sleep": True,
                    "notif_online": True,
                    "notif_offline": True,
                },
                "ok": True,
                "status": "success",
                "message": "User alert settings fetched successfully"
            }
        }
    }
    
get_user_alert_settings_response_500 = {
    "model": GetUserAlertSettingsResponse,
    "description": "Internal Server Error",
    "content": {
        "application/json": {
            "example": {
                "data": None,
                "ok": False,
                "status": "error",
                "message": "Error when fetch user alert settings: error_reason",
            }
        }
    }
}

class PutUserAlertSettingsRequest(RootModel[Dict[str, bool]]):
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "notif_speed_alert": True,
                    "notif_geofence_inside": False,
                    "notif_geofence_outside": False,
                    "notif_cut_off": True,
                    "notif_sleep": True,
                    "notif_online": True,
                    "notif_offline": True,
                },
            ]
        }
    }

# class PutUserAlertSettingsResponseData(BaseModel):
#     is_toggle_on: bool = Field(
#         ...,
#         description="Value notifikasi alert user yang ingin di-update"
#     )

class PutUserAlertSettingsResponse(BaseModel):
    data: Optional[Dict[str, bool]] = Field(None, description="Objek data hasil update alert settings user")
    ok: bool = Field(..., description="Status request (true/false)")
    status: str = Field(..., description="Status request (success/error)")
    message: str = Field(..., description="Pesan deskriptif hasil request")

    model_config = {
        "json_schema_extra": {
            "example": {
                "data": {
                    "notif_speed_alert": True,
                    "notif_geofence_inside": False,
                    "notif_geofence_outside": False,
                    "notif_cut_off": True,
                    "notif_sleep": True,
                    "notif_online": True,
                    "notif_offline": True,
                },
                "ok": True,
                "status": "success",
                "message": "User alert settings updated successfully"
            }
        }
    }
    
put_user_alert_settings_response_500 = {
    "model": PutUserAlertSettingsResponse,
    "description": "Internal Server Error",
    "content": {
        "application/json": {
            "example": {
                "data": None,
                "ok": False,
                "status": "error",
                "message": "Error when updating user alert settings: error_reason",
            }
        }
    }
}