from typing import Optional

from pydantic import BaseModel

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
    
