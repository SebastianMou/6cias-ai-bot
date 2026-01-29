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

class SurveyResponse(Base):
    __tablename__ = "survey_responses"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(100), unique=True, index=True)
    candidate_name = Column(String(100), nullable=True)
    user_ip = Column(String(50), nullable=True)  
    
    # A) Basic info
    date_of_birth = Column(String(20), nullable=True)
    phone_whatsapp = Column(String(20), nullable=True)
    email = Column(String(100), nullable=True)
    
    # B) Address
    full_address = Column(Text, nullable=True)
    share_location = Column(Boolean, nullable=True)
    
    # C) Housing
    housing_type = Column(String(50), nullable=True)  # propia/rentada/prestada
    lives_with = Column(Text, nullable=True)
    dependents_count = Column(Integer, nullable=True)
    has_water = Column(Boolean, nullable=True)
    has_electricity = Column(Boolean, nullable=True)
    has_internet = Column(Boolean, nullable=True)
    has_gas = Column(Boolean, nullable=True)
    
    # D) Section 7.1 - Assets
    real_estate = Column(Text, nullable=True)
    vehicles = Column(Text, nullable=True)
    businesses = Column(Text, nullable=True)
    formal_savings = Column(Text, nullable=True)
    
    # E) Section 7.2 - Debt
    debts = Column(Text, nullable=True)
    credit_bureau = Column(String(50), nullable=True)
    
    # F) Education
    education_level = Column(String(100), nullable=True)
    has_education_proof = Column(Boolean, nullable=True)
    
    # G) Employment
    position_applying = Column(String(100), nullable=True)
    organization = Column(String(100), nullable=True)
    area_division = Column(String(100), nullable=True)
    application_reason = Column(String(100), nullable=True)
    how_found_vacancy = Column(Text, nullable=True)
    current_employment = Column(Text, nullable=True)
    previous_employment = Column(Text, nullable=True)
    
    # H) Section 7.3 - Income
    salary_bonus = Column(String(100), nullable=True)
    family_support = Column(String(100), nullable=True)
    informal_business_income = Column(String(100), nullable=True)
    
    # I) Section 7.4 - Expenses
    expenses_list = Column(Text, nullable=True)  # Which expenses they have
    expenses_amounts = Column(Text, nullable=True)  # Amounts for each
    groceries = Column(String(50), nullable=True)
    alimony = Column(String(50), nullable=True)
    food_out = Column(String(50), nullable=True)
    rent = Column(String(50), nullable=True)
    utilities = Column(String(50), nullable=True)
    internet_cable = Column(String(50), nullable=True)
    transportation = Column(String(50), nullable=True)
    uber_taxi = Column(String(50), nullable=True)
    school_expenses = Column(String(50), nullable=True)
    courses = Column(String(50), nullable=True)
    books_supplies = Column(String(50), nullable=True)
    entertainment = Column(String(50), nullable=True)
    vacations = Column(String(50), nullable=True)
    insurance = Column(String(50), nullable=True)
    taxes = Column(String(50), nullable=True)
    clothing = Column(String(50), nullable=True)
    laundry = Column(String(50), nullable=True)
    internet_expenses = Column(String(50), nullable=True)
    
    # J) Health
    has_medical_condition = Column(Boolean, nullable=True)
    takes_permanent_medication = Column(Boolean, nullable=True)
    
    # K) Section 8.0 - Family contacts
    primary_family_contacts = Column(Text, nullable=True)
    secondary_family_contacts = Column(Text, nullable=True)
    work_references = Column(Text, nullable=True)
    personal_reference = Column(Text, nullable=True)
    
    # L) Section 9.0 - Home access
    home_references = Column(Text, nullable=True)
    crime_in_area = Column(String(50), nullable=True)
    services_quality = Column(String(50), nullable=True)
    security_quality = Column(String(50), nullable=True)
    surveillance_quality = Column(String(50), nullable=True)
    
    # M) Section 9.1 - Property status
    bedrooms = Column(String(20), nullable=True)
    dining_room = Column(String(20), nullable=True)
    living_room = Column(String(20), nullable=True)
    bathrooms = Column(String(20), nullable=True)
    floors = Column(String(20), nullable=True)
    garden = Column(String(20), nullable=True)
    kitchen = Column(String(20), nullable=True)
    air_conditioning = Column(String(20), nullable=True)
    garage = Column(String(20), nullable=True)
    laundry_area = Column(String(20), nullable=True)
    pool = Column(String(20), nullable=True)
    sports_areas = Column(String(20), nullable=True)
    study_office = Column(String(20), nullable=True)
    
    # N) Operators section
    has_federal_license = Column(Boolean, nullable=True)
    federal_license_number = Column(String(100), nullable=True)
    medical_folio = Column(String(100), nullable=True)
    license_validity = Column(String(50), nullable=True)
    license_type = Column(String(50), nullable=True)
    has_state_license = Column(Boolean, nullable=True)
    state_license_info = Column(Text, nullable=True)
    
    # O) Evidence tracking
    evidence_sent = Column(Text, nullable=True)
    
    # Metadata
    survey_completed = Column(Boolean, default=False)
    current_section = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SurveyConversation(Base):
    __tablename__ = "survey_conversations"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(100), index=True, nullable=False)
    user_message = Column(Text, nullable=False)
    bot_response = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)