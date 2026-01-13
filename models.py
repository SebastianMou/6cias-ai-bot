from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from datetime import datetime
from database import Base

class Conversation(Base):
    __tablename__ = "conversations"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(100), index=True, nullable=False)
    user_message = Column(Text, nullable=False)
    bot_response = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    user_ip = Column(String(50), nullable=True)
    user_agent = Column(String(255), nullable=True)

class Candidate(Base):
    __tablename__ = "candidates"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(100), unique=True, index=True)
    name = Column(String(100), nullable=True)
    email = Column(String(100), nullable=True, unique=True)
    phone = Column(String(20), nullable=True)
    position_applied = Column(String(100), nullable=True)
    
    # Interview status
    interview_completed = Column(Boolean, default=False)
    passed_first_interview = Column(Boolean, nullable=True)
    interview_score = Column(Integer, nullable=True)
    
    # NEW FIELDS - Stage information
    incorporation_time = Column(String(100), nullable=True)  # ¿En cuánto tiempo podrías incorporarte?
    education_level = Column(String(100), nullable=True)  # ¿Cuál Grado de Estudios tienes?
    job_interest_reason = Column(Text, nullable=True)  # ¿Qué te pareció más llamativo de la vacante?
    years_experience = Column(String(50), nullable=True)  # ¿Cuánta Experiencia tienes?
    last_job_info = Column(Text, nullable=True)  # ¿Cuando fue tu último trabajo y cuándo duraste?
    can_travel = Column(Boolean, nullable=True)  # ¿Puedes viajar?
    knows_office = Column(Boolean, nullable=True)  # ¿Sabes Paquetería Office?
    salary_agreement = Column(Boolean, nullable=True)  # ¿Estás de acuerdo con el sueldo?
    schedule_availability = Column(Text, nullable=True)  # Disponibilidad de horario
    
    # Filters acceptance
    accepts_polygraph = Column(Boolean, nullable=True)  # Examinación Poligrafía
    accepts_socioeconomic = Column(Boolean, nullable=True)  # Encuesta Socioeconómica
    accepts_drug_test = Column(Boolean, nullable=True)  # Prueba Antidoping
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    notes = Column(Text, nullable=True)

class InterviewQuestion(Base):
    __tablename__ = "interview_questions"
    
    id = Column(Integer, primary_key=True, index=True)
    question = Column(Text, nullable=False)
    category = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True)
    order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class SystemSettings(Base):
    __tablename__ = "system_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    setting_key = Column(String(100), unique=True, index=True, nullable=False)
    setting_value = Column(String(255), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)