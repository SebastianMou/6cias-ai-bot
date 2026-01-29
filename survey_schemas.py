from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class SurveyChatRequest(BaseModel):
    message: str
    session_id: str

class SurveyChatResponse(BaseModel):
    response: str
    session_id: str
    progress: Optional[int] = 0  # 0-100 percentage

class SurveyResponseCreate(BaseModel):
    session_id: str
    candidate_name: Optional[str] = None
    
    # A) Basic info
    date_of_birth: Optional[str] = None
    phone_whatsapp: Optional[str] = None
    email: Optional[str] = None
    
    # B) Address
    full_address: Optional[str] = None
    share_location: Optional[bool] = None
    
    # C) Housing
    housing_type: Optional[str] = None  # propia/rentada/prestada
    lives_with: Optional[str] = None
    dependents_count: Optional[int] = None
    has_water: Optional[bool] = None
    has_electricity: Optional[bool] = None
    has_internet: Optional[bool] = None
    has_gas: Optional[bool] = None
    
    # D) Section 7.1 - Assets
    real_estate: Optional[str] = None
    vehicles: Optional[str] = None
    businesses: Optional[str] = None
    formal_savings: Optional[str] = None
    
    # E) Section 7.2 - Debt
    debts: Optional[str] = None
    credit_bureau: Optional[str] = None
    
    # F) Education
    education_level: Optional[str] = None
    has_education_proof: Optional[bool] = None
    
    # G) Employment
    position_applying: Optional[str] = None
    organization: Optional[str] = None
    area_division: Optional[str] = None
    application_reason: Optional[str] = None  # Nuevo ingreso/Reingreso/Promoción
    how_found_vacancy: Optional[str] = None
    current_employment: Optional[str] = None
    previous_employment: Optional[str] = None
    
    # H) Section 7.3 - Income
    salary_bonus: Optional[str] = None
    family_support: Optional[str] = None
    informal_business_income: Optional[str] = None
    
    # I) Section 7.4 - Expenses
    expenses_list: Optional[str] = None  # Which expenses they have
    expenses_amounts: Optional[str] = None  # Amounts for each expense
    groceries: Optional[str] = None
    alimony: Optional[str] = None
    food_out: Optional[str] = None
    rent: Optional[str] = None
    utilities: Optional[str] = None
    internet_cable: Optional[str] = None
    transportation: Optional[str] = None
    uber_taxi: Optional[str] = None
    school_expenses: Optional[str] = None
    courses: Optional[str] = None
    books_supplies: Optional[str] = None
    entertainment: Optional[str] = None
    vacations: Optional[str] = None
    insurance: Optional[str] = None
    taxes: Optional[str] = None
    clothing: Optional[str] = None
    laundry: Optional[str] = None
    internet_expenses: Optional[str] = None
    
    # J) Health
    has_medical_condition: Optional[bool] = None
    takes_permanent_medication: Optional[bool] = None
    
    # K) Section 8.0 - Family contacts
    primary_family_contacts: Optional[str] = None
    secondary_family_contacts: Optional[str] = None
    work_references: Optional[str] = None  # 2 referencias laborales
    personal_reference: Optional[str] = None  # 1 referencia personal
    
    # L) Section 9.0 - Home access
    home_references: Optional[str] = None  # Referencias para ubicar
    crime_in_area: Optional[str] = None  # Nada/Poco/Mucho/Demasiado
    services_quality: Optional[str] = None
    security_quality: Optional[str] = None
    surveillance_quality: Optional[str] = None
    
    # M) Section 9.1 - Property status
    bedrooms: Optional[str] = None
    dining_room: Optional[str] = None
    living_room: Optional[str] = None
    bathrooms: Optional[str] = None
    floors: Optional[str] = None
    garden: Optional[str] = None
    kitchen: Optional[str] = None
    air_conditioning: Optional[str] = None
    garage: Optional[str] = None
    laundry_area: Optional[str] = None
    pool: Optional[str] = None
    sports_areas: Optional[str] = None
    study_office: Optional[str] = None
    
    # N) Operators section
    has_federal_license: Optional[bool] = None
    federal_license_number: Optional[str] = None
    medical_folio: Optional[str] = None
    license_validity: Optional[str] = None
    license_type: Optional[str] = None
    has_state_license: Optional[bool] = None
    state_license_info: Optional[str] = None
    
    # O) Evidence tracking
    evidence_sent: Optional[str] = None  # Track what evidence was sent
    
    # Metadata
    survey_completed: Optional[bool] = False
    current_section: Optional[str] = None

class SurveyResponseUpdate(BaseModel):
    candidate_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    phone_whatsapp: Optional[str] = None
    email: Optional[str] = None
    full_address: Optional[str] = None
    share_location: Optional[bool] = None
    housing_type: Optional[str] = None
    lives_with: Optional[str] = None
    dependents_count: Optional[int] = None
    has_water: Optional[bool] = None
    has_electricity: Optional[bool] = None
    has_internet: Optional[bool] = None
    has_gas: Optional[bool] = None
    real_estate: Optional[str] = None
    vehicles: Optional[str] = None
    businesses: Optional[str] = None
    formal_savings: Optional[str] = None
    debts: Optional[str] = None
    credit_bureau: Optional[str] = None
    education_level: Optional[str] = None
    has_education_proof: Optional[bool] = None
    position_applying: Optional[str] = None
    organization: Optional[str] = None
    area_division: Optional[str] = None
    application_reason: Optional[str] = None
    how_found_vacancy: Optional[str] = None
    current_employment: Optional[str] = None
    previous_employment: Optional[str] = None
    salary_bonus: Optional[str] = None
    family_support: Optional[str] = None
    informal_business_income: Optional[str] = None
    expenses_list: Optional[str] = None
    expenses_amounts: Optional[str] = None
    groceries: Optional[str] = None
    alimony: Optional[str] = None
    food_out: Optional[str] = None
    rent: Optional[str] = None
    utilities: Optional[str] = None
    internet_cable: Optional[str] = None
    transportation: Optional[str] = None
    uber_taxi: Optional[str] = None
    school_expenses: Optional[str] = None
    courses: Optional[str] = None
    books_supplies: Optional[str] = None
    entertainment: Optional[str] = None
    vacations: Optional[str] = None
    insurance: Optional[str] = None
    taxes: Optional[str] = None
    clothing: Optional[str] = None
    laundry: Optional[str] = None
    internet_expenses: Optional[str] = None
    has_medical_condition: Optional[bool] = None
    takes_permanent_medication: Optional[bool] = None
    primary_family_contacts: Optional[str] = None
    secondary_family_contacts: Optional[str] = None
    work_references: Optional[str] = None
    personal_reference: Optional[str] = None
    home_references: Optional[str] = None
    crime_in_area: Optional[str] = None
    services_quality: Optional[str] = None
    security_quality: Optional[str] = None
    surveillance_quality: Optional[str] = None
    bedrooms: Optional[str] = None
    dining_room: Optional[str] = None
    living_room: Optional[str] = None
    bathrooms: Optional[str] = None
    floors: Optional[str] = None
    garden: Optional[str] = None
    kitchen: Optional[str] = None
    air_conditioning: Optional[str] = None
    garage: Optional[str] = None
    laundry_area: Optional[str] = None
    pool: Optional[str] = None
    sports_areas: Optional[str] = None
    study_office: Optional[str] = None
    has_federal_license: Optional[bool] = None
    federal_license_number: Optional[str] = None
    medical_folio: Optional[str] = None
    license_validity: Optional[str] = None
    license_type: Optional[str] = None
    has_state_license: Optional[bool] = None
    state_license_info: Optional[str] = None
    evidence_sent: Optional[str] = None
    survey_completed: Optional[bool] = None
    current_section: Optional[str] = None

class SurveyResponseOut(BaseModel):
    id: int
    session_id: str
    candidate_name: Optional[str]
    email: Optional[str]
    phone_whatsapp: Optional[str]
    survey_completed: bool
    current_section: Optional[str]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True