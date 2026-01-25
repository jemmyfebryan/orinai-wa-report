from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.orin_wa_report.core.config import get_config_data
from src.orin_wa_report.core.development import (
    create_user
)

router = APIRouter(prefix="", tags=["whatsapp-dev"], include_in_schema=True)

config_data = get_config_data()

# Dummy Development
@router.post(
    path='/dummy/create_user',
    include_in_schema=False,
)
async def create_dummy_user(request: Request):
    try:
        # Not allowed by config
        if not config_data.get("dummy").get("enable_create_user"):
            return JSONResponse(content={
                "status": "not allowed",
                "message": "Creating dummy user is not allowed from the server.",
                "data": None
            }, status_code=405)
        
        # Creating dummy user
        data = await request.json()
        
        verified = data.get("verified", False)
        dummy_devices_count = data.get("devices_count", 3)
        
        result = await create_user.create_dummy_user(
            wa_verified=verified,
            dummy_devices_count=dummy_devices_count
        )
        return JSONResponse(content={
            "status": "success",
            "message": "Dummy user created successfully!",
            "data": result
        }, status_code=200)
    except Exception as e:
        return JSONResponse(content={
            "status": "error",
            "message": f"Error when create dummy user: {str(e)}",
            "data": None
        }, status_code=500)