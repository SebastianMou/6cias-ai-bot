from sqlalchemy.orm import Session
from models import SurveyResponse, SurveyConversation
from typing import Optional

def create_survey_response(db: Session, session_id: str):
    """Create a new survey response record"""
    db_survey = SurveyResponse(session_id=session_id, current_section="7.0")
    db.add(db_survey)
    db.commit()
    db.refresh(db_survey)
    return db_survey

def get_survey_by_session(db: Session, session_id: str):
    """Get survey response by session ID"""
    return db.query(SurveyResponse).filter(SurveyResponse.session_id == session_id).first()

def update_survey_field(db: Session, session_id: str, **kwargs):
    """Update survey response fields"""
    survey = get_survey_by_session(db, session_id)
    if not survey:
        survey = create_survey_response(db, session_id)
    
    for key, value in kwargs.items():
        if hasattr(survey, key):
            setattr(survey, key, value)
    
    db.commit()
    db.refresh(survey)
    return survey

def create_survey_conversation(db: Session, session_id: str, user_message: str, bot_response: str):
    """Save a conversation turn"""
    conversation = SurveyConversation(
        session_id=session_id,
        user_message=user_message,
        bot_response=bot_response
    )
    db.add(conversation)
    db.commit()
    return conversation

def get_survey_conversations(db: Session, session_id: str):
    """Get all conversations for a session"""
    return db.query(SurveyConversation).filter(
        SurveyConversation.session_id == session_id
    ).order_by(SurveyConversation.created_at).all()