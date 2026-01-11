from sqlalchemy.orm import Session
from models import Conversation, Candidate, InterviewQuestion
from schemas import ConversationCreate, CandidateCreate
from typing import List, Optional

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