from sqlalchemy.orm import Session
from models import Conversation, Candidate, InterviewQuestion, SystemSettings
from schemas import ConversationCreate, CandidateCreate
from typing import List, Optional
from datetime import datetime

def create_conversation(db: Session, conversation: ConversationCreate) -> Conversation:
    db_conversation = Conversation(**conversation.dict())
    db.add(db_conversation)
    db.commit()
    db.refresh(db_conversation)
    return db_conversation

def get_conversations_by_session(db: Session, session_id: str) -> List[Conversation]:
    return db.query(Conversation).filter(
        Conversation.session_id == session_id
    ).order_by(Conversation.created_at).all()

def create_candidate(db: Session, candidate: CandidateCreate) -> Candidate:
    db_candidate = Candidate(**candidate.dict())
    db.add(db_candidate)
    db.commit()
    db.refresh(db_candidate)
    return db_candidate

def get_candidate_by_session(db: Session, session_id: str) -> Optional[Candidate]:
    return db.query(Candidate).filter(Candidate.session_id == session_id).first()

def get_candidate_by_email(db: Session, email: str) -> Optional[Candidate]:
    return db.query(Candidate).filter(Candidate.email == email).first()

def update_candidate(db: Session, session_id: str, **kwargs) -> Optional[Candidate]:
    candidate = get_candidate_by_session(db, session_id)
    if candidate:
        for key, value in kwargs.items():
            setattr(candidate, key, value)
        db.commit()
        db.refresh(candidate)
    return candidate

def delete_candidate(db: Session, session_id: str) -> bool:
    """Delete a candidate and their conversations by session_id"""
    candidate = get_candidate_by_session(db, session_id)
    if candidate:
        # Delete associated conversations first
        db.query(Conversation).filter(Conversation.session_id == session_id).delete()
        # Delete candidate
        db.delete(candidate)
        db.commit()
        return True
    return False

def get_setting(db: Session, key: str) -> Optional[str]:
    """Get a system setting by key"""
    setting = db.query(SystemSettings).filter(SystemSettings.setting_key == key).first()
    return setting.setting_value if setting else None

def set_setting(db: Session, key: str, value: str):
    """Set a system setting"""
    setting = db.query(SystemSettings).filter(SystemSettings.setting_key == key).first()
    if setting:
        setting.setting_value = value
        setting.updated_at = datetime.utcnow()
    else:
        setting = SystemSettings(setting_key=key, setting_value=value)
        db.add(setting)
    db.commit()
    return setting