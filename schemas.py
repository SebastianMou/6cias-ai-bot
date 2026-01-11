from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional

class ChatRequest(BaseModel):
    message: str
    session_id: str

class ChatResponse(BaseModel):
    response: str
    session_id: str

class ConversationBase(BaseModel):
    session_id: str
    user_message: str
    bot_response: str

class ConversationCreate(ConversationBase):
    user_ip: Optional[str] = None
    user_agent: Optional[str] = None

class CandidateBase(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    position_applied: Optional[str] = None

class CandidateCreate(CandidateBase):
    session_id: str

class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: list[dict]
    candidate_info: Optional[dict] = None