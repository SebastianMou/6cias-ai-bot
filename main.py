from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqladmin import Admin, ModelView
import google.genai as genai  
from models import SurveyResponse, SurveyConversation 
from survey_schemas import SurveyChatRequest, SurveyChatResponse
import survey_crud
import httpx
from config import settings
from database import engine, get_db, Base
from models import Conversation, Candidate, InterviewQuestion, SystemSettings, SurveyResponse, SurveyConversation
from schemas import (
    ChatRequest, ChatResponse, ChatHistoryResponse,
    ConversationCreate, CandidateCreate
)
import crud
from datetime import datetime
import os
from pathlib import Path
import re
import unicodedata

# Directory where job descriptions are stored
JOBS_DIR = Path("jobs")


# Configuration
MAX_MESSAGES_PER_SESSION = 60

app = FastAPI(title="6Cias Chatbot API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)

# Updated Gemini configuration
client = genai.Client(api_key=settings.gemini_api_key)

async def get_ip_geolocation(ip_address: str):
    """Get geolocation data for an IP address using ip-api.com"""
    if not ip_address or ip_address == 'unknown':
        return None
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f'http://ip-api.com/json/{ip_address}')
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        print(f"Error getting geolocation: {e}")
    
    return None

def load_job_description(job_title: str) -> str:
    """Load job description from file if it exists"""
    import unicodedata
    import re
    
    # Remove accents/diacritics
    normalized = ''.join(
        c for c in unicodedata.normalize('NFD', job_title)
        if unicodedata.category(c) != 'Mn'
    )
    
    # Convert to lowercase, replace spaces/dashes with single underscore, remove multiple underscores
    filename = re.sub(r'[_\-\s]+', '_', normalized.lower()).strip('_') + ".txt"
    filepath = JOBS_DIR / filename
    
    print(f"[FILE SEARCH] Looking for: {filepath}")
    
    if filepath.exists():
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    
    return None

def get_available_jobs() -> list:
    """Get list of available job positions"""
    if not JOBS_DIR.exists():
        return []
    
    jobs = []
    for file in JOBS_DIR.glob("*.txt"):
        # Convert filename back to readable format
        # Replace underscores with spaces and add dashes for 'Cdmx'
        job_name = file.stem.replace("_", " ").title()
        
        # Fix specific formatting: "Cdmx" should have a dash before it
        # This handles patterns like "reclutador cdmx sur" -> "Reclutador - Cdmx Sur"
        if " Cdmx " in job_name or job_name.endswith(" Cdmx"):
            parts = job_name.split(" Cdmx ")
            if len(parts) == 2:
                job_name = f"{parts[0]} - Cdmx {parts[1]}"
            else:
                # Handle "Something Cdmx"
                job_name = job_name.replace(" Cdmx", " - Cdmx")
        
        jobs.append(job_name)
    return jobs

# Build system prompt with available jobs
available_jobs = get_available_jobs()
jobs_list = "\n- ".join(available_jobs) if available_jobs else "No hay vacantes cargadas"

SYSTEM_PROMPT = f"""Eres Petrof, asistente de reclutamiento de 6Cias.

    Vacantes disponibles:
    - {jobs_list}

    IMPORTANTE - Orden de la entrevista:
    1. PRIMERO: Pregunta qué puesto de trabajo están solicitando
    2. DESPUÉS: Solicita nombre completo
    3. DESPUÉS: Solicita email
    4. DESPUÉS: Solicita teléfono
    5. PREGUNTAS ADICIONALES (en orden):
    - ¿En cuánto tiempo podrías incorporarte a laborar?
    - ¿Cuál grado de estudios tienes?
    - ¿Las actividades del puesto son acordes a tu perfil?
    - ¿Qué te pareció más llamativo de la vacante y te interesó?
    - ¿Es lo que estabas buscando?
    - ¿Cuánta experiencia tienes en el puesto?
    - ¿Cuándo fue tu último trabajo y cuánto duraste?
    - ¿Puedes viajar si es necesario para esta vacante u otra?
    - ¿Sabes usar Paquetería Office?
    - ¿Estás de acuerdo con el sueldo?
    - ¿Qué disponibilidad tienes de horario o restricciones?

    6. FILTROS FINALES:
    - ¿Estás de acuerdo con: Examinación de Poligrafía?
    - ¿Estás de acuerdo con: Encuesta Socioeconómica?
    - ¿Estás de acuerdo con: Prueba Antidoping?

    Y si necesitan comprar el servicio transferirlos a wa.me/5215566800185 - +52 (155) 668-00185

    IMPORTANTE sobre investigaciones:
    - Si están de acuerdo: menciona que incluye Investigación de Incidencias, zona adecuada, y salario
    - Informa que si pasan los filtros, irían a entrevistas con el cliente
    - Si pasan con el cliente, se firma el contrato

    Tu rol:
    - Ser profesional, amable y empático
    - Seguir el orden exacto mencionado arriba
    - Hacer preguntas claras y una a la vez
    - Evaluar si el candidato es adecuado para posiciones de confianza

    Cuando el usuario pregunte ESPECÍFICAMENTE sobre detalles de una vacante (salario, horario, responsabilidades), 
    recibirás la descripción completa del puesto en tags <job_description>.
    """

admin = Admin(app, engine)

class ConversationAdmin(ModelView, model=Conversation):
    column_list = [Conversation.id, Conversation.session_id, Conversation.created_at]
    name = "Conversación"
    name_plural = "Conversaciones"

class CandidateAdmin(ModelView, model=Candidate):
    column_list = [Candidate.id, Candidate.name, Candidate.email, Candidate.created_at]
    name = "Candidato"
    name_plural = "Candidatos"

class SurveyResponseAdmin(ModelView, model=SurveyResponse):
    column_list = [SurveyResponse.id, SurveyResponse.candidate_name, SurveyResponse.created_at, SurveyResponse.survey_completed]
    name = "Encuesta Económica"
    name_plural = "Encuestas Económicas"

class SurveyConversationAdmin(ModelView, model=SurveyConversation):
    column_list = [SurveyConversation.id, SurveyConversation.session_id, SurveyConversation.created_at]
    name = "Conversación de Encuesta"
    name_plural = "Conversaciones de Encuestas"

admin.add_view(SurveyConversationAdmin)
admin.add_view(SurveyResponseAdmin)
admin.add_view(CandidateAdmin)
admin.add_view(ConversationAdmin)

@app.get("/")
async def root():
    return FileResponse("index.html")

@app.get("/status")
async def status():
    return {"message": "6Cias Chatbot API", "status": "running"}

@app.get("/dashboard")
async def dashboard():
    return FileResponse("dashboard.html")

@app.get("/candidate.html")
async def candidate_page():
    return FileResponse("candidate.html")

@app.get("/widget")
async def widget():
    return FileResponse("widget.html")

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, req: Request, db: Session = Depends(get_db)):
    try:
        chat_enabled = crud.get_setting(db, "chat_enabled")
        if chat_enabled == "false":
            return ChatResponse(
                response="Lo sentimos, el sistema de chat está temporalmente desactivado. Por favor, contáctanos directamente al WhatsApp wa.me/5215652301371 para continuar con tu proceso de reclutamiento.",
                session_id=request.session_id
            )

        # Get conversation history FIRST (needed for job detection)
        history = crud.get_conversations_by_session(db, request.session_id)
        
        # Check message limit
        if len(history) >= MAX_MESSAGES_PER_SESSION:
            return ChatResponse(
                response="Lo siento, has alcanzado el límite de 60 mensajes para esta sesión. Por favor, contáctanos directamente al WhatsApp wa.me/5215652301371 para continuar con tu proceso de reclutamiento.",
                session_id=request.session_id
            )
        
        # Check if user mentioned a job position in THIS message OR in conversation history
        user_message_lower = request.message.lower()
        job_context = ""
        detected_job = None

        print(f"\n{'='*60}")
        print(f"[REQUEST] User message: {request.message[:100]}...")
        print(f"[DETECTION] Checking for job mentions...")

        # Define keywords that indicate user wants JOB DETAILS
        detail_keywords = ["salario", "sueldo", "horario", "responsabilidad", "responsabilidades", 
                        "requisito", "requisitos", "prestacion", "prestaciones", 
                        "actividad", "actividades", "qué hace", "funciones", "ubicación",
                        "ubicacion", "vacante", "puesto", "trabajo", "paga", "pagan", 
                        "cuanto", "cuánto", "comision", "comisiones", "commission", 
                        "beneficio", "beneficios", "detalles", "informacion", "información"]

        # Check if user is asking about job details OR mentioning job for first time
        needs_job_info = any(keyword in user_message_lower for keyword in detail_keywords)

        # First, check current message for job mention (with EXACT matching)
        available_jobs = get_available_jobs()
        
        for job in available_jobs:
            # Normalize both for comparison (remove accents, case-insensitive)
            import unicodedata
            job_normalized = ''.join(
                c for c in unicodedata.normalize('NFD', job.lower())
                if unicodedata.category(c) != 'Mn'
            )
            message_normalized = ''.join(
                c for c in unicodedata.normalize('NFD', user_message_lower)
                if unicodedata.category(c) != 'Mn'
            )
            
            if job_normalized in message_normalized:
                detected_job = job
                print(f"[FOUND] Job mentioned in current message: '{job}'")
                break

        # If not found in current message, check conversation history (only if user needs details)
        if not detected_job and needs_job_info and history:
            # Check only last 3 messages, most recent first
            for conv in reversed(history[-3:]):
                conv_text = (conv.user_message + " " + conv.bot_response).lower()
                conv_normalized = ''.join(
                    c for c in unicodedata.normalize('NFD', conv_text)
                    if unicodedata.category(c) != 'Mn'
                )
                
                # Try to find job in this conversation, but prefer exact/longer matches
                best_match = None
                best_match_length = 0
                
                for job in available_jobs:
                    job_normalized = ''.join(
                        c for c in unicodedata.normalize('NFD', job.lower())
                        if unicodedata.category(c) != 'Mn'
                    )
                    
                    if job_normalized in conv_normalized:
                        # Prefer longer job names (more specific)
                        if len(job_normalized) > best_match_length:
                            best_match = job
                            best_match_length = len(job_normalized)
                
                if best_match:
                    detected_job = best_match
                    print(f"[FOUND] Job mentioned in conversation history: '{detected_job}'")
                    
                    if job_normalized in conv_normalized:
                        detected_job = job
                        print(f"[FOUND] Job mentioned in conversation history: '{job}'")
                        break
                if detected_job:
                    break

        # Only load file if: (1) Job just mentioned, OR (2) User asking for details
        should_load_file = detected_job and needs_job_info

        if should_load_file:
            job_desc = load_job_description(detected_job)
            if job_desc:
                job_context = f"\n\n<job_description>\nDetalles del puesto {detected_job}:\n{job_desc}\n</job_description>"
                print(f"[FILE LOADED] ✅ Loaded {detected_job.lower().replace(' ', '_')}.txt ({len(job_desc)} characters)")
                print(f"[TOKENS] Estimated extra tokens: ~{len(job_desc.split())}")
            else:
                print(f"[ERROR] ❌ Job file not found for '{detected_job}'")
        elif detected_job:
            print(f"[SKIPPED] Job '{detected_job}' detected but no details requested - saving tokens ✅")
        else:
            print(f"[NO JOB DETECTED] ❌ No job mentioned yet")

        print(f"{'='*60}\n")

        # Build context with system prompt and history
                
        # Build conversation history
        context = SYSTEM_PROMPT + "\n\nHistorial:\n"
        for conv in history[-5:]:
            context += f"Usuario: {conv.user_message}\nAsistente: {conv.bot_response}\n"
        
        # Add job context if found
        enhanced_message = f"{request.message}{job_context}" if job_context else request.message
        
        full_prompt = context + f"\nUsuario: {enhanced_message}\nAsistente:"
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=full_prompt
        )
        bot_response = response.text
        
        # Save conversation
        conversation_data = ConversationCreate(
            session_id=request.session_id,
            user_message=request.message,
            bot_response=bot_response,
            user_ip=req.client.host if req.client else None,
            user_agent=req.headers.get("user-agent")
        )
        crud.create_conversation(db, conversation_data)
        
        # Get or create candidate
        candidate = crud.get_candidate_by_session(db, request.session_id)
        if not candidate:
            candidate = crud.create_candidate(db, CandidateCreate(session_id=request.session_id))
            # Refresh to get the created candidate
            candidate = crud.get_candidate_by_session(db, request.session_id)

        # ========== EXTRACT ALL INFORMATION ==========
        import re

        user_message_lower = request.message.lower()
        update_data = {}
        
        # Get previous bot message for context
        last_bot = ""
        if history:
            last_bot = history[-1].bot_response.lower()

        # Extract email
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        email_match = re.search(email_pattern, request.message)
        if email_match and (not candidate or not candidate.email):
            update_data['email'] = email_match.group(0)

        # Extract phone
        phone_pattern = r'[\+\(]?[1-9][0-9 .\-\(\)]{8,}[0-9]'
        phone_match = re.search(phone_pattern, request.message)
        if phone_match and (not candidate or not candidate.phone):
            update_data['phone'] = phone_match.group(0).strip()

        # Extract position - prioritize detected_job from earlier
        if detected_job and (not candidate or not candidate.position_applied):
            update_data['position_applied'] = detected_job
            print(f"[SAVED] Position applied: {detected_job}")
        elif not candidate or not candidate.position_applied:
            # Fallback: check keywords manually
            position_keywords = ['auxiliar', 'supervisor', 'recepcionista', 
                    'administrativo', 'contador', 'seguridad', 'chofer', 'limpieza']
            for keyword in position_keywords:
                if keyword in user_message_lower:
                    update_data['position_applied'] = keyword.capitalize()
                    print(f"[SAVED] Position applied (keyword match): {keyword.capitalize()}")
                    break

        # Extract name - check if PREVIOUS bot message asked for name
        if not candidate or not candidate.name:
            bot_asked_for_name = False
            
            if history:
                if 'nombre' in last_bot or 'name' in last_bot:
                    bot_asked_for_name = True
            
            if bot_asked_for_name:
                message_clean = request.message.strip()
                words = message_clean.split()
                
                if 2 <= len(words) <= 6:
                    if '@' not in message_clean and not message_clean.lower().startswith('yes') and not message_clean.lower().startswith('si'):
                        name_words = []
                        for word in words:
                            if word[0].isupper() or word.lower() in ['de', 'la', 'del', 'los', 'las']:
                                name_words.append(word)
                            elif len(name_words) > 0:
                                break
                        
                        if len(name_words) >= 2:
                            update_data['name'] = ' '.join(name_words)

        # ===== EXTRACT ADDITIONAL FIELDS (using last_bot) =====
        
        # Detect incorporation time
        if any(word in last_bot for word in ['cuánto tiempo', 'incorporarte', 'cuando puedes empezar']):
            if not candidate or not candidate.incorporation_time:
                update_data['incorporation_time'] = request.message.strip()
        
        # Detect education level
        if any(word in last_bot for word in ['grado de estudios', 'nivel de estudios', 'escolaridad']):
            if not candidate or not candidate.education_level:
                update_data['education_level'] = request.message.strip()
        
        # Detect job interest reason
        if any(word in last_bot for word in ['llamativo', 'interesó', 'te gustó', 'por qué te interesa']):
            if not candidate or not candidate.job_interest_reason:
                update_data['job_interest_reason'] = request.message.strip()
        
        # Detect years of experience
        if any(word in last_bot for word in ['cuánta experiencia', 'años de experiencia', 'experiencia tienes']):
            if not candidate or not candidate.years_experience:
                update_data['years_experience'] = request.message.strip()
        
        # Detect last job info
        if any(word in last_bot for word in ['último trabajo', 'anterior trabajo', 'cuándo duraste']):
            if not candidate or not candidate.last_job_info:
                update_data['last_job_info'] = request.message.strip()
        
        # Detect travel willingness
        if any(word in last_bot for word in ['puedes viajar', 'disponibilidad para viajar']):
            if not candidate or candidate.can_travel is None:
                if any(word in user_message_lower for word in ['sí', 'si', 'yes', 'claro', 'por supuesto', 'puedo']):
                    update_data['can_travel'] = True
                elif any(word in user_message_lower for word in ['no', 'not', 'tampoco']):
                    update_data['can_travel'] = False
        
        # Detect Office knowledge
        if any(word in last_bot for word in ['office', 'paquetería office', 'sabes office']):
            if not candidate or candidate.knows_office is None:
                if any(word in user_message_lower for word in ['sí', 'si', 'yes', 'claro', 'sé']):
                    update_data['knows_office'] = True
                elif any(word in user_message_lower for word in ['no', 'not', 'poco']):
                    update_data['knows_office'] = False
        
        # Detect salary agreement
        if any(word in last_bot for word in ['de acuerdo con el sueldo', 'salario', 'sueldo te parece']):
            if not candidate or candidate.salary_agreement is None:
                if any(word in user_message_lower for word in ['sí', 'si', 'yes', 'de acuerdo', 'acepto', 'está bien']):
                    update_data['salary_agreement'] = True
                elif any(word in user_message_lower for word in ['no', 'not']):
                    update_data['salary_agreement'] = False
        
        # Detect schedule availability
        if any(word in last_bot for word in ['disponibilidad', 'horario', 'restricciones']):
            if not candidate or not candidate.schedule_availability:
                # Only save if it's different from what we just saved
                if request.message.strip() != update_data.get('education_level'):
                    update_data['schedule_availability'] = request.message.strip()
        
        # Detect polygraph acceptance
        if any(word in last_bot for word in ['poligraf', 'examen de polígrafo']):
            if not candidate or candidate.accepts_polygraph is None:
                if any(word in user_message_lower for word in ['sí', 'si', 'yes', 'acepto', 'de acuerdo']):
                    update_data['accepts_polygraph'] = True
                elif any(word in user_message_lower for word in ['no', 'not']):
                    update_data['accepts_polygraph'] = False
        
        # Detect socioeconomic survey acceptance
        if any(word in last_bot for word in ['socioeconómica', 'socioeconomica', 'encuesta socioeconómica']):
            if not candidate or candidate.accepts_socioeconomic is None:
                if any(word in user_message_lower for word in ['sí', 'si', 'yes', 'acepto', 'de acuerdo']):
                    update_data['accepts_socioeconomic'] = True
                elif any(word in user_message_lower for word in ['no', 'not']):
                    update_data['accepts_socioeconomic'] = False
        
        # Detect drug test acceptance
        if any(word in last_bot for word in ['antidoping', 'anti-doping', 'prueba antidoping']):
            if not candidate or candidate.accepts_drug_test is None:
                if any(word in user_message_lower for word in ['sí', 'si', 'yes', 'acepto', 'de acuerdo']):
                    update_data['accepts_drug_test'] = True
                elif any(word in user_message_lower for word in ['no', 'not']):
                    update_data['accepts_drug_test'] = False
        
        # Build full conversation history to check for missing info
        all_messages = ""
        for conv in history:
            all_messages += f"{conv.user_message} "
        all_messages += request.message
        
        # Re-check for email in full history if not found yet
        if (not candidate or not candidate.email) and not update_data.get('email'):
            email_match = re.search(email_pattern, all_messages)
            if email_match:
                update_data['email'] = email_match.group(0)
        
        # Re-check for phone in full history if not found yet
        if (not candidate or not candidate.phone) and not update_data.get('phone'):
            phone_match = re.search(phone_pattern, all_messages)
            if phone_match:
                update_data['phone'] = phone_match.group(0).strip()
        
        # ===== UPDATE CANDIDATE WITH ALL EXTRACTED DATA =====
        if update_data:
            crud.update_candidate(db, request.session_id, **update_data)
        # ========== END EXTRACTION ==========
        
        # ========== CHECK IF INTERVIEW IS COMPLETE ==========
        end_keywords = ['siguiente fase', 'segunda entrevista', 'se pondrá en contacto', 'contacto contigo', 'próximos pasos', 'siguiente etapa']

        interview_ending = any(keyword in bot_response.lower() for keyword in end_keywords)

        if interview_ending and candidate:
            has_all_info = (candidate.name and candidate.email and candidate.phone and candidate.position_applied)
            
            if has_all_info and not candidate.interview_completed:
                crud.update_candidate(db, request.session_id, interview_completed=True, passed_first_interview=True, interview_score=85)
                
                # Add final WhatsApp message
                final_message = (
                    "\n\nMuy bien, para finalizar y agilizar el proceso, mándame a este WhatsApp "
                    "wa.me/5215652301371 un video de un minuto con tu nombre completo y vacantes "
                    "a las que te postulas respondiendo estas 2 preguntas: "
                    "¿Me explicas brevemente quién eres tú con el por qué aplicas a la vacante? "
                    "Y ¿Te comprometes a llevar a cabo el proceso profesionalmente responsable en "
                    "Reclutamiento y Puesto?"
                )
                bot_response += final_message
        # ========== END INTERVIEW COMPLETION CHECK ==========
        
        return ChatResponse(response=bot_response, session_id=request.session_id)
    
    except Exception as e:
        return ChatResponse(response=f"Error: {str(e)}", session_id=request.session_id)

@app.get("/settings/chat-enabled")
async def get_chat_status(db: Session = Depends(get_db)):
    """Get chatbot enabled status"""
    status = crud.get_setting(db, "chat_enabled")
    return {"chat_enabled": status != "false"}  # Default to true if not set

@app.post("/settings/chat-enabled")
async def toggle_chat_status(request: dict, db: Session = Depends(get_db)):
    """Toggle chatbot enabled status"""
    enabled = request.get("enabled", True)
    crud.set_setting(db, "chat_enabled", "true" if enabled else "false")
    return {"chat_enabled": enabled, "message": f"Chat {'activado' if enabled else 'desactivado'}"}

@app.post("/survey/{session_id}/audit")
async def audit_survey_conversation(session_id: str, db: Session = Depends(get_db)):
    """Analyze conversation and auto-populate survey fields using AI"""
    try:
        survey = survey_crud.get_survey_by_session(db, session_id)
        if not survey:
            raise HTTPException(status_code=404, detail="Survey not found")
        
        # Get all conversations
        conversations = survey_crud.get_survey_conversations(db, session_id)
        
        if not conversations:
            raise HTTPException(status_code=400, detail="No conversation found to analyze")
        
        # Build conversation text
        conversation_text = ""
        for conv in conversations:
            conversation_text += f"Usuario: {conv.user_message}\n"
            conversation_text += f"Bot: {conv.bot_response}\n\n"
        
        # Create extraction prompt
        extraction_prompt = f"""Analiza la siguiente conversación de una encuesta socioeconómica y extrae TODOS los datos mencionados.

            CONVERSACIÓN:
            {conversation_text}

            INSTRUCCIONES:
            - Extrae SOLO información explícitamente mencionada
            - Si un dato no fue mencionado, devuelve null
            - Para campos booleanos: usa true/false/null
            - Para texto: usa el texto exacto mencionado
            - Para números: usa el número mencionado

            Responde ÚNICAMENTE con un objeto JSON válido con estos campos (sin markdown, sin explicaciones):

            {{
                "candidate_name": "nombre completo o null",
                "date_of_birth": "fecha en formato DD/MM/AAAA o null",
                "phone_whatsapp": "teléfono o null",
                "email": "email o null",
                "full_address": "dirección completa o null",
                "share_location": true/false/null,
                "housing_type": "propia/rentada/prestada o null",
                "lives_with": "con quien vive o null",
                "dependents_count": número o null,
                "real_estate": "bienes inmuebles o null",
                "vehicles": "vehículos o null",
                "businesses": "negocios o null",
                "formal_savings": "ahorros o null",
                "debts": "deudas o null",
                "credit_bureau": "información buró o null",
                "education_level": "nivel educativo o null",
                "has_education_proof": true/false/null,
                "position_applying": "puesto o null",
                "organization": "organización o null",
                "area_division": "área o null",
                "application_reason": "razón o null",
                "how_found_vacancy": "cómo se enteró o null",
                "current_employment": "empleo actual o null",
                "previous_employment": "empleos anteriores o null",
                "salary_bonus": "sueldo o null",
                "family_support": "apoyo familiar o null",
                "informal_business_income": "ingresos informales o null",
                "expenses_list": "lista de gastos o null",
                "expenses_amounts": "montos de gastos o null",
                "has_medical_condition": true/false/null,
                "takes_permanent_medication": true/false/null,
                "primary_family_contacts": "contactos familia primaria o null",
                "secondary_family_contacts": "contactos familia secundaria o null",
                "work_references": "referencias laborales o null",
                "personal_reference": "referencia personal o null",
                "home_references": "referencias domicilio o null",
                "crime_in_area": "Nada/Poco/Mucho/Demasiado o null",
                "services_quality": "Nada/Poco/Mucho/Demasiado o null",
                "security_quality": "Nada/Poco/Mucho/Demasiado o null",
                "surveillance_quality": "Nada/Poco/Mucho/Demasiado o null",
                "bedrooms": "número o respuesta o null",
                "dining_room": "respuesta o null",
                "living_room": "respuesta o null",
                "bathrooms": "número o respuesta o null",
                "floors": "número o null",
                "garden": "respuesta o null",
                "kitchen": "respuesta o null",
                "air_conditioning": "respuesta o null",
                "garage": "respuesta o null",
                "laundry_area": "respuesta o null",
                "pool": "respuesta o null",
                "sports_areas": "respuesta o null",
                "study_office": "respuesta o null",
                "has_federal_license": true/false/null,
                "federal_license_number": "número o null",
                "medical_folio": "folio o null",
                "license_validity": "vigencia o null",
                "license_type": "tipo o null",
                "evidence_sent": "evidencias enviadas o null"
            }}"""

        # Call Gemini API
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[{"role": "user", "parts": [{"text": extraction_prompt}]}],
            config={
                "temperature": 0.1,
                "max_output_tokens": 2000
            }
        )
        
        # Parse JSON response
        import json
        import re
        
        response_text = response.text.strip()
        
        # Remove markdown code blocks if present
        response_text = re.sub(r'^```json\s*', '', response_text)
        response_text = re.sub(r'^```\s*', '', response_text)
        response_text = re.sub(r'\s*```$', '', response_text)
        
        extracted_data = json.loads(response_text)
        
        # Update survey with extracted data (only non-null values)
        update_data = {k: v for k, v in extracted_data.items() if v is not None}
        
        if update_data:
            survey_crud.update_survey_field(db, session_id, **update_data)
        
        return {
            "message": "Audit completed successfully",
            "fields_updated": len(update_data),
            "extracted_data": update_data
        }
        
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Error parsing AI response: {str(e)}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error during audit: {str(e)}")

# ========== SURVEY ROUTES ==========
@app.get("/survey")
async def survey_page():
    return FileResponse("economic_survey.html")

@app.get("/survey-dashboard")
async def survey_dashboard():
    return FileResponse("survey_dashboard.html")

@app.get("/survey-detail")
async def survey_detail():
    return FileResponse("survey_detail.html")

@app.get("/survey/all")
async def get_all_surveys(db: Session = Depends(get_db)):
    """Get all survey responses with statistics"""
    from datetime import datetime
    
    surveys = db.query(SurveyResponse).order_by(SurveyResponse.created_at.desc()).all()
    
    today = datetime.utcnow().date()
    today_count = len([s for s in surveys if s.created_at.date() == today])
    completed_count = len([s for s in surveys if s.survey_completed])
    in_progress_count = len([s for s in surveys if s.current_section and not s.survey_completed])
    
    return {
        "total": len(surveys),
        "completed": completed_count,
        "in_progress": in_progress_count,
        "today": today_count,
        "surveys": [
            {
                "session_id": s.session_id,
                "candidate_name": s.candidate_name,
                "current_section": s.current_section,
                "survey_completed": s.survey_completed,
                "created_at": s.created_at.isoformat(),
                "updated_at": s.updated_at.isoformat(),
                "date_of_birth": s.date_of_birth,
                "phone_whatsapp": s.phone_whatsapp,
                "email": s.email,
                "full_address": s.full_address,
                "housing_type": s.housing_type,
                "lives_with": s.lives_with,
                "real_estate": s.real_estate,
                "vehicles": s.vehicles,
                "businesses": s.businesses,
                "formal_savings": s.formal_savings,
                "debts": s.debts,
                "credit_bureau": s.credit_bureau,
                "education_level": s.education_level,
                "position_applying": s.position_applying,
                "organization": s.organization,
                "current_employment": s.current_employment,
                "salary_bonus": s.salary_bonus,
                "expenses_list": s.expenses_list,
                "expenses_amounts": s.expenses_amounts,
                "has_medical_condition": s.has_medical_condition,
                "primary_family_contacts": s.primary_family_contacts,
                "work_references": s.work_references,
                "personal_reference": s.personal_reference,
                "home_references": s.home_references,
                "crime_in_area": s.crime_in_area,
                "bedrooms": s.bedrooms,
                "has_federal_license": s.has_federal_license,
                "evidence_sent": s.evidence_sent,
            }
            for s in surveys
        ]
    }

@app.get("/survey/{session_id}")
async def get_survey_by_id(session_id: str, db: Session = Depends(get_db)):
    """Get a specific survey response"""
    survey = survey_crud.get_survey_by_session(db, session_id)
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")
    
    # Get geolocation data
    geo_data = await get_ip_geolocation(survey.user_ip) if survey.user_ip else None
    
    # Return ALL fields
    return {
        "session_id": survey.session_id,
        "candidate_name": survey.candidate_name,
        "user_ip": survey.user_ip,
        "geo_country": geo_data.get('country') if geo_data else None,
        "geo_region": geo_data.get('regionName') if geo_data else None,
        "geo_city": geo_data.get('city') if geo_data else None,
        "geo_lat": geo_data.get('lat') if geo_data else None,
        "geo_lon": geo_data.get('lon') if geo_data else None,
        "survey_completed": survey.survey_completed,
        "current_section": survey.current_section,
        "created_at": survey.created_at.isoformat(),
        "updated_at": survey.updated_at.isoformat(),
        
        # A) Basic info
        "date_of_birth": survey.date_of_birth,
        "phone_whatsapp": survey.phone_whatsapp,
        "email": survey.email,
        
        # B) Address
        "full_address": survey.full_address,
        "share_location": survey.share_location,
        
        # C) Housing
        "housing_type": survey.housing_type,
        "lives_with": survey.lives_with,
        "dependents_count": survey.dependents_count,
        "has_water": survey.has_water,
        "has_electricity": survey.has_electricity,
        "has_internet": survey.has_internet,
        "has_gas": survey.has_gas,
        
        # D) Assets 7.1
        "real_estate": survey.real_estate,
        "vehicles": survey.vehicles,
        "businesses": survey.businesses,
        "formal_savings": survey.formal_savings,
        
        # E) Debt 7.2
        "debts": survey.debts,
        "credit_bureau": survey.credit_bureau,
        
        # F) Education
        "education_level": survey.education_level,
        "has_education_proof": survey.has_education_proof,
        
        # G) Employment
        "position_applying": survey.position_applying,
        "organization": survey.organization,
        "area_division": survey.area_division,
        "application_reason": survey.application_reason,
        "how_found_vacancy": survey.how_found_vacancy,
        "current_employment": survey.current_employment,
        "previous_employment": survey.previous_employment,
        
        # H) Income 7.3
        "salary_bonus": survey.salary_bonus,
        "family_support": survey.family_support,
        "informal_business_income": survey.informal_business_income,
        
        # I) Expenses 7.4
        "expenses_list": survey.expenses_list,
        "expenses_amounts": survey.expenses_amounts,
        "groceries": survey.groceries,
        "alimony": survey.alimony,
        "food_out": survey.food_out,
        "rent": survey.rent,
        "utilities": survey.utilities,
        "internet_cable": survey.internet_cable,
        "transportation": survey.transportation,
        "uber_taxi": survey.uber_taxi,
        "school_expenses": survey.school_expenses,
        "courses": survey.courses,
        "books_supplies": survey.books_supplies,
        "entertainment": survey.entertainment,
        "vacations": survey.vacations,
        "insurance": survey.insurance,
        "taxes": survey.taxes,
        "clothing": survey.clothing,
        "laundry": survey.laundry,
        "internet_expenses": survey.internet_expenses,
        
        # J) Health
        "has_medical_condition": survey.has_medical_condition,
        "takes_permanent_medication": survey.takes_permanent_medication,
        
        # K) Family contacts 8.0
        "primary_family_contacts": survey.primary_family_contacts,
        "secondary_family_contacts": survey.secondary_family_contacts,
        "work_references": survey.work_references,
        "personal_reference": survey.personal_reference,
        
        # L) Home access 9.0
        "home_references": survey.home_references,
        "crime_in_area": survey.crime_in_area,
        "services_quality": survey.services_quality,
        "security_quality": survey.security_quality,
        "surveillance_quality": survey.surveillance_quality,
        
        # M) Property status 9.1
        "bedrooms": survey.bedrooms,
        "dining_room": survey.dining_room,
        "living_room": survey.living_room,
        "bathrooms": survey.bathrooms,
        "floors": survey.floors,
        "garden": survey.garden,
        "kitchen": survey.kitchen,
        "air_conditioning": survey.air_conditioning,
        "garage": survey.garage,
        "laundry_area": survey.laundry_area,
        "pool": survey.pool,
        "sports_areas": survey.sports_areas,
        "study_office": survey.study_office,
        
        # N) Operators
        "has_federal_license": survey.has_federal_license,
        "federal_license_number": survey.federal_license_number,
        "medical_folio": survey.medical_folio,
        "license_validity": survey.license_validity,
        "license_type": survey.license_type,
        "has_state_license": survey.has_state_license,
        "state_license_info": survey.state_license_info,
        
        # O) Evidence
        "evidence_sent": survey.evidence_sent,
    }

@app.get("/survey/{session_id}/conversation")
async def get_survey_conversation(session_id: str, db: Session = Depends(get_db)):
    """Get conversation for a survey"""
    conversations = survey_crud.get_survey_conversations(db, session_id)
    return {
        "conversations": [
            {
                "user_message": c.user_message,
                "bot_response": c.bot_response,
                "created_at": c.created_at.isoformat()
            }
            for c in conversations
        ]
    }

@app.post("/survey/chat")
async def survey_chat(request: dict, db: Session = Depends(get_db)):
    """Handle survey chat messages"""
    try:
        chat_setting = db.query(SystemSettings).filter(
            SystemSettings.setting_key == "survey_chat_enabled"
        ).first()

        if chat_setting and chat_setting.setting_value == "false":
            return {
                "response": "Lo siento, el chat de encuestas está temporalmente desactivado. Por favor, intenta más tarde.",
                "session_id": request.get("session_id", ""),
                "progress": 0
            }

        session_id = request.get("session_id")
        message = request.get("message")
        ip_address = request.get("ip_address")
        
        if not session_id or not message:
            raise HTTPException(status_code=400, detail="Missing session_id or message")
        
        # Get or create survey response
        survey = survey_crud.get_survey_by_session(db, session_id)
        if not survey:
            survey = survey_crud.create_survey_response(db, session_id)

        # Save IP address (on first interaction or update if changed) 
        if ip_address and not survey.user_ip:
            survey_crud.update_survey_field(db, session_id, user_ip=ip_address)
        
        # Get conversation history
        history = survey_crud.get_survey_conversations(db, session_id)
        
        # Build conversation context for Gemini
        conversation_history = []
        for conv in history:
            conversation_history.append({
                "role": "user",
                "parts": [{"text": conv.user_message}]
            })
            conversation_history.append({
                "role": "model",
                "parts": [{"text": conv.bot_response}]
            })
        
        # System prompt for economic survey
        system_prompt = f"""Eres un asistente de verificación socioeconómica para 6Cias. Tu objetivo es recopilar información y evidencias de forma clara, ordenada y respetuosa, para completar la certificación de ingreso a un puesto de confianza.

            REGLAS GENERALES:
            - Haz preguntas una por una y espera respuesta antes de seguir
            - Si la persona contesta incompleto, pide precisión sin regañar
            - Mantén tono profesional, directo y amable
            - Para verificación domiciliaria: pide ubicación en tiempo real solo si la persona acepta y/o pide evidencia fotográfica
            - Al final, resume lo recabado y lista lo pendiente

            ORDEN DE LA ENCUESTA (SEGUIR ESTRICTAMENTE):

            A) ARRANQUE Y VERIFICACIÓN BÁSICA:
            1. Nombre completo (tal cual en identificación obligatorio)
            2. Fecha de nacimiento (DD/MM/AAAA, obligatorio)
            3. Teléfono con WhatsApp
            4. Correo personal (obligatorio)

            B) DOMICILIO Y UBICACIÓN (CON CONSENTIMIENTO):
            5. Domicilio completo (calle, número, colonia, CP, alcaldía/municipio, estado)
            6. ¿Puedes compartir tu ubicación en tiempo real por WhatsApp para la verificación domiciliaria? (Sí/No)
               - Si "Sí": "Compártela por 10–15 min, por favor."
               - Si "No": "Sin problema. Para validar, te pediré fotos y comprobante de domicilio."

            C) VIVIENDA (SOCIOECONÓMICO):
            7. ¿La vivienda es propia, rentada o prestada?
            8. ¿Con quién vives actualmente? (parentesco y edades aproximadas)
            9. ¿Cuántas personas dependen económicamente de ti?
            10. Servicios: ¿Cuentas con agua, luz, internet, gas? (Sí/No por cada uno)

            D) SECCIÓN 7.1 - BIENES PATRIMONIALES:
            11. Bienes inmuebles (propiedades/terrenos): Pedir descripción y valor. Si no tiene, aceptar "no tengo"
            12. Vehículos: Pedir marca, submarca, modelo y valor. Si no tiene, aceptar "no tengo"
            13. Negocios: Pedir tipo de negocio, ingresos mensuales. Si no tiene, aceptar "no tengo"
            14. Ahorros formales: Pedir tipo y cantidad. Si no tiene, aceptar "no tengo"

            E) SECCIÓN 7.2 - SITUACIÓN DE DEUDA:
            15. ¿Tienes adeudos a tu nombre? Pedir detalles (tarjeta, adeudo, pago mensual)
            16. ¿Alguna vez estuviste en Buró de Crédito? (Sí/No/Otros)

            F) ESCOLARIDAD:
            17. Último grado de estudios: (Primaria/Secundaria/Prepa/Técnico/Licenciatura/Otro)
            18. ¿Cuenta con comprobante (constancia/título/cédula)? (Sí/No)

            G) EMPLEO Y TRAYECTORIA:
            19. Puesto que buscas / posible puesto a certificar
            20. Organización / empresa
            21. Área, sucursal o división
            22. Motivo: (Nuevo ingreso / Reingreso / Promoción / Otro)
            23. ¿Cómo te enteraste de la vacante por primera vez?
            24. Empleo actual: empresa, puesto, antigüedad, horario y sueldo aproximado (rango)
            25. Empleos anteriores (últimos 2): empresa, puesto, tiempo y motivo de salida

            H) SECCIÓN 7.3 - INGRESOS (PEDIR CANTIDADES):
            26. Sueldo y bono mensual (rango aproximado)
            27. Apoyo familiar o de pareja (cantidad aproximada)
            28. Ingreso por negocios informales (cantidad aproximada)

            I) SECCIÓN 7.4 - EGRESOS:
            29. "¿En qué gastas tu dinero mensualmente? Dime solo los que SÍ aplican de esta lista:
                Despensa, Pensión Alimenticia, Alimentos fuera, Renta, Luz/Agua/Gas, Internet/Cable/Teléfono, 
                Gasolina/Pasajes, Uber/Taxi, Uniformes/Colegiaturas, Cursos/Talleres, Libros/Útiles, 
                Entretenimiento, Vacaciones, Seguros, Impuestos, Ropa, Lavandería, Gastos en Internet"

            30. "Perfecto. Ahora, para cada gasto que mencionaste, dame la cantidad aproximada mensual."

            J) SALUD Y HÁBITOS (SOLO GENERAL):
            31. ¿Tienes alguna condición médica que afecte el trabajo o manejo? (Sí/No)
            32. ¿Tomas medicamentos de forma permanente? (Sí/No) (sin detallar de más)

            K) SECCIÓN 8.0 - CONTACTOS FAMILIARES:
            33. Referencias familia primaria (padres, hermanos, primos, tíos)
                Formato: apellidos, nombres | parentesco | ocupación | número | ubicación
            34. Referencias familia secundaria (pareja, hijos)
                Formato: apellidos, nombres | parentesco | ocupación | número | ubicación
            35. 2 referencias laborales: nombre, empresa, puesto, teléfono
            36. 1 referencia personal: nombre, relación, teléfono

            L) SECCIÓN 9.0 - ACCESO Y CARACTERÍSTICAS DOMICILIARIAS:
            37. Referencias para ubicar domicilio (ej: a un costado del OXXO, entre calles X y Y)
            38. Calificar (Nada/Poco/Mucho/Demasiado):
                - ¿Te has enterado de delincuencia en la zona?
                - ¿Los servicios son buenos en la zona?
                - ¿La seguridad es buena en la zona?
                - ¿La vigilancia es buena en la zona?

            M) SECCIÓN 9.1 - ESTADO DEL INMUEBLE (responder No tengo/Sí/1/2/3/4):
            39. Recámaras, Comedor, Sala, Baños, Pisos
            40. Jardín, Cocina, Clima, Cochera
            41. Área de lavado, Alberca, Áreas deportivas, Estudio/Oficina

            N) BLOQUE ESPECIAL PARA OPERADORES (SOLO SI APLICA):
            42. ¿Tienes Licencia Federal? (Sí/No)
                Si "Sí":
                - ¿Cuál es tu número de Licencia?
                - A continuación escribe el número del Médico/folio del dictamen médico
                - Vigencia (mes/año)
                - Tipo/categoría
                Si "No": ¿Tienes licencia estatal? ¿Número y vigencia?

            O) EVIDENCIAS (LO QUE DEBE PEDIR SÍ O SÍ):
            Indica que pueden enviarlo por WhatsApp o correo:
            - WhatsApp: wa.me/5215613771144
            - Correo: solucion@6cias.com

            Documentos necesarios:
            1. Comprobante de domicilio (preferencia recibo CFE) foto o PDF
            2. Cartas de recomendación laborales (fotos claras o PDF; si las tienes)
            3. 5 fotos de interiores (sala, comedor, cocina, patio/área común; toma amplia)
            4. 5 fotos del exterior/calle principal (frente, ambos lados, referencia visible)
            5. Foto de la fachada y otra foto donde salgas tú frente a la fachada (rostro visible)
            6. Facebook (verificación social):
               - "¿Puedes mandar una captura de tu perfil de Facebook?"
               - "¿Puedes agregarnos o dar like? www.facebook.com/6cias"

            P) CIERRE (CHECKLIST + PENDIENTES):
            "Gracias. Con lo que me diste, ya tengo: [lista corta de lo recibido]."
            "Me falta recibir: [pendientes]."
            "¿Confirmas que la información es verdadera y autorizas su verificación para el proceso de certificación?" (Sí/No)

            CANALES DE ENVÍO DE EVIDENCIAS:
            - WhatsApp: wa.me/5215613771144
            - Correo: solucion@6cias.com
            - Facebook: www.facebook.com/6cias

            INSTRUCCIONES FINALES:
            - Hacer UNA pregunta a la vez
            - Ser amable y profesional
            - Si la respuesta es confusa, pedir clarificación
            - Avanzar sección por sección en orden
            - Al terminar, agradecer y confirmar que la encuesta está completa

            Estado actual: Sección {survey.current_section or 'Inicio'}"""
        
        # Add current message to history
        conversation_history.append({
            "role": "user",
            "parts": [{"text": message}]
        })
        
        # Call Gemini API
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=conversation_history,
            config={
                "system_instruction": system_prompt,
                "temperature": 0.7,
                "max_output_tokens": 500
            }
        )
        
        bot_response = response.text
        
        # Save conversation
        survey_crud.create_survey_conversation(
            db, session_id, message, bot_response
        )
        
        # Extract data from user message and update survey
        user_msg_lower = message.lower()
        
        # Detect name in first message
        if not survey.candidate_name and len(history) == 0:
            survey_crud.update_survey_field(db, session_id, candidate_name=message.strip())
        
        # Calculate progress
        sections_completed = 0
        if survey.candidate_name: sections_completed += 1
        if survey.real_estate or survey.vehicles or survey.businesses or survey.formal_savings:
            sections_completed += 1
        if survey.debts or survey.credit_bureau: sections_completed += 1
        if survey.salary_bonus: sections_completed += 1
        if survey.groceries: sections_completed += 1
        if survey.primary_family_contacts: sections_completed += 1
        if survey.home_references: sections_completed += 1
        if survey.bedrooms: sections_completed += 1
        
        progress = int((sections_completed / 8) * 100)
        
        return {
            "response": bot_response,
            "session_id": session_id,
            "progress": progress
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "response": "Lo siento, hubo un error procesando tu respuesta. Por favor, intenta nuevamente.",
            "session_id": request.get("session_id", ""),
            "progress": 0
        }

@app.delete("/survey/{session_id}")
async def delete_survey(session_id: str, db: Session = Depends(get_db)):
    """Delete a survey and its conversation"""
    survey = survey_crud.get_survey_by_session(db, session_id)
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")
    
    # Delete conversations
    db.query(SurveyConversation).filter(SurveyConversation.session_id == session_id).delete()
    # Delete survey
    db.delete(survey)
    db.commit()
    
    return {"message": "Survey deleted successfully"}

@app.put("/survey/{session_id}")
async def update_survey(session_id: str, data: dict, db: Session = Depends(get_db)):
    """Update survey fields"""
    survey = survey_crud.update_survey_field(db, session_id, **data)
    return {"message": "Survey updated successfully"}

@app.get("/candidate/{session_id}")
async def get_candidate(session_id: str, db: Session = Depends(get_db)):
    """Get a single candidate by session_id"""
    candidate = crud.get_candidate_by_session(db, session_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    
    return {
        "id": candidate.id,
        "session_id": candidate.session_id,
        "name": candidate.name,
        "email": candidate.email,
        "phone": candidate.phone,
        "position_applied": candidate.position_applied,
        "interview_completed": candidate.interview_completed,
        "passed_first_interview": candidate.passed_first_interview,
        "interview_score": candidate.interview_score,
        "incorporation_time": candidate.incorporation_time,
        "education_level": candidate.education_level,
        "job_interest_reason": candidate.job_interest_reason,
        "years_experience": candidate.years_experience,
        "last_job_info": candidate.last_job_info,
        "can_travel": candidate.can_travel,
        "knows_office": candidate.knows_office,
        "salary_agreement": candidate.salary_agreement,
        "schedule_availability": candidate.schedule_availability,
        "accepts_polygraph": candidate.accepts_polygraph,
        "accepts_socioeconomic": candidate.accepts_socioeconomic,
        "accepts_drug_test": candidate.accepts_drug_test,
        "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
        "updated_at": candidate.updated_at.isoformat() if candidate.updated_at else None
    }

@app.put("/candidate/{session_id}")
async def update_candidate_endpoint(session_id: str, data: dict, db: Session = Depends(get_db)):
    """Update a candidate"""
    candidate = crud.get_candidate_by_session(db, session_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    
    # Update all provided fields
    update_data = {}
    
    # Basic fields
    if "name" in data:
        update_data["name"] = data["name"]
    if "email" in data:
        update_data["email"] = data["email"]
    if "phone" in data:
        update_data["phone"] = data["phone"]
    if "position_applied" in data:
        update_data["position_applied"] = data["position_applied"]
    
    # Interview status
    if "interview_score" in data:
        update_data["interview_score"] = data["interview_score"]
    if "interview_completed" in data:
        update_data["interview_completed"] = data["interview_completed"]
    if "passed_first_interview" in data:
        update_data["passed_first_interview"] = data["passed_first_interview"]
    
    # Additional info
    if "incorporation_time" in data:
        update_data["incorporation_time"] = data["incorporation_time"]
    if "education_level" in data:
        update_data["education_level"] = data["education_level"]
    if "years_experience" in data:
        update_data["years_experience"] = data["years_experience"]
    if "schedule_availability" in data:
        update_data["schedule_availability"] = data["schedule_availability"]
    if "job_interest_reason" in data:
        update_data["job_interest_reason"] = data["job_interest_reason"]
    if "last_job_info" in data:
        update_data["last_job_info"] = data["last_job_info"]
    
    # Skills & abilities
    if "can_travel" in data:
        update_data["can_travel"] = data["can_travel"]
    if "knows_office" in data:
        update_data["knows_office"] = data["knows_office"]
    if "salary_agreement" in data:
        update_data["salary_agreement"] = data["salary_agreement"]
    
    # Filters
    if "accepts_polygraph" in data:
        update_data["accepts_polygraph"] = data["accepts_polygraph"]
    if "accepts_socioeconomic" in data:
        update_data["accepts_socioeconomic"] = data["accepts_socioeconomic"]
    if "accepts_drug_test" in data:
        update_data["accepts_drug_test"] = data["accepts_drug_test"]
    
    updated_candidate = crud.update_candidate(db, session_id, **update_data)
    return {"message": "Candidate updated successfully", "candidate_id": updated_candidate.id}

@app.delete("/candidate/{session_id}")
async def delete_candidate_endpoint(session_id: str, db: Session = Depends(get_db)):
    """Delete a candidate and their conversations"""
    success = crud.delete_candidate(db, session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Candidate not found")
    
    return {"message": "Candidate deleted successfully"}

@app.get("/history/{session_id}", response_model=ChatHistoryResponse)
async def get_history(session_id: str, db: Session = Depends(get_db)):
    conversations = crud.get_conversations_by_session(db, session_id)
    messages = [{
        "user": conv.user_message,
        "bot": conv.bot_response,
        "timestamp": conv.created_at.isoformat()
    } for conv in conversations]
    
    candidate = crud.get_candidate_by_session(db, session_id)
    candidate_info = None
    if candidate:
        candidate_info = {
            "name": candidate.name,
            "email": candidate.email,
            "phone": candidate.phone,
            "position": candidate.position_applied,
            "interview_completed": candidate.interview_completed,
            "passed": candidate.passed_first_interview,
            "score": candidate.interview_score,
            "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
            "updated_at": candidate.updated_at.isoformat() if candidate.updated_at else None,
            # New fields
            "incorporation_time": candidate.incorporation_time,
            "education_level": candidate.education_level,
            "job_interest_reason": candidate.job_interest_reason,
            "years_experience": candidate.years_experience,
            "last_job_info": candidate.last_job_info,
            "can_travel": candidate.can_travel,
            "knows_office": candidate.knows_office,
            "salary_agreement": candidate.salary_agreement,
            "schedule_availability": candidate.schedule_availability,
            "accepts_polygraph": candidate.accepts_polygraph,
            "accepts_socioeconomic": candidate.accepts_socioeconomic,
            "accepts_drug_test": candidate.accepts_drug_test
        }
    
    return ChatHistoryResponse(session_id=session_id, messages=messages, candidate_info=candidate_info)

@app.get("/candidates")
async def get_all_candidates(db: Session = Depends(get_db)):
    """Get all candidates"""
    candidates = db.query(Candidate).order_by(Candidate.created_at.desc()).all()
    return [{
        "id": c.id,
        "session_id": c.session_id,
        "name": c.name,
        "email": c.email,
        "phone": c.phone,
        "position_applied": c.position_applied,
        "interview_completed": c.interview_completed,
        "passed_first_interview": c.passed_first_interview,
        "interview_score": c.interview_score,
        "created_at": c.created_at.isoformat() if c.created_at else None
    } for c in candidates]

@app.post("/jobs/create")
async def create_job(request: dict):
    """Create a new job description file"""
    try:
        job_title = request.get("job_title", "").strip()
        job_description = request.get("job_description", "").strip()
        
        if not job_title or not job_description:
            raise HTTPException(status_code=400, detail="Job title and description are required")
        
        # Ensure jobs directory exists
        JOBS_DIR.mkdir(exist_ok=True)
        
        # Normalize filename
        filename = job_title.lower().replace(" ", "_").replace("ó", "o").replace("á", "a").replace("é", "e").replace("í", "i").replace("ú", "u").replace("ñ", "n") + ".txt"
        filepath = JOBS_DIR / filename
        
        # Check if file already exists
        if filepath.exists():
            raise HTTPException(status_code=400, detail="A job with this title already exists")
        
        # Create the file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(job_description)
        
        # Refresh available jobs list
        global available_jobs, jobs_list, SYSTEM_PROMPT
        available_jobs = get_available_jobs()
        jobs_list = "\n- ".join(available_jobs) if available_jobs else "No hay vacantes cargadas"
        SYSTEM_PROMPT = f"""Eres Petrof, asistente de reclutamiento de 6Cias.

            Vacantes disponibles:
            - {jobs_list}

            IMPORTANTE - Orden de la entrevista:
            1. PRIMERO: Pregunta qué puesto de trabajo están solicitando
            2. DESPUÉS: Solicita nombre completo
            3. DESPUÉS: Solicita email
            4. DESPUÉS: Solicita teléfono
            5. PREGUNTAS ADICIONALES (en orden):
            - ¿En cuánto tiempo podrías incorporarte a laborar?
            - ¿Cuál grado de estudios tienes?
            - ¿Las actividades del puesto son acordes a tu perfil?
            - ¿Qué te pareció más llamativo de la vacante y te interesó?
            - ¿Es lo que estabas buscando?
            - ¿Cuánta experiencia tienes en el puesto?
            - ¿Cuándo fue tu último trabajo y cuánto duraste?
            - ¿Puedes viajar si es necesario para esta vacante u otra?
            - ¿Sabes usar Paquetería Office?
            - ¿Estás de acuerdo con el sueldo?
            - ¿Qué disponibilidad tienes de horario o restricciones?

            6. FILTROS FINALES:
            - ¿Estás de acuerdo con: Examinación de Poligrafía?
            - ¿Estás de acuerdo con: Encuesta Socioeconómica?
            - ¿Estás de acuerdo con: Prueba Antidoping?

            Y si necesitan comprar el servicio transferirlos a wa.me/5215566800185 - +52 (155) 668-00185

            IMPORTANTE sobre investigaciones:
            - Si están de acuerdo: menciona que incluye Investigación de Incidencias, zona adecuada, y salario
            - Informa que si pasan los filtros, irían a entrevistas con el cliente
            - Si pasan con el cliente, se firma el contrato

            Tu rol:
            - Ser profesional, amable y empático
            - Seguir el orden exacto mencionado arriba
            - Hacer preguntas claras y una a la vez
            - Evaluar si el candidato es adecuado para posiciones de confianza

            Cuando el usuario pregunte ESPECÍFICAMENTE sobre detalles de una vacante (salario, horario, responsabilidades), 
            recibirás la descripción completa del puesto en tags <job_description>.
            """
        
        return {"message": "Job created successfully", "filename": filename, "job_title": job_title}
    
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/jobs/list")
async def list_jobs():
    """Get list of all available jobs with their descriptions"""
    try:
        jobs = []
        if JOBS_DIR.exists():
            for file in JOBS_DIR.glob("*.txt"):
                with open(file, 'r', encoding='utf-8') as f:
                    content = f.read()
                jobs.append({
                    "filename": file.name,
                    "title": file.stem.replace("_", " ").title(),
                    "description": content[:200] + "..." if len(content) > 200 else content
                })
        return {"jobs": jobs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/jobs/{filename}")
async def delete_job(filename: str):
    """Delete a job description file"""
    try:
        filepath = JOBS_DIR / filename
        
        if not filepath.exists():
            raise HTTPException(status_code=404, detail="Job file not found")
        
        filepath.unlink()
        
        # Refresh available jobs list
        global available_jobs, jobs_list, SYSTEM_PROMPT
        available_jobs = get_available_jobs()
        jobs_list = "\n- ".join(available_jobs) if available_jobs else "No hay vacantes cargadas"
        SYSTEM_PROMPT = f"""Eres Petrof, asistente de reclutamiento de 6Cias.

            Vacantes disponibles:
            - {jobs_list}

            IMPORTANTE - Orden de la entrevista:
            1. PRIMERO: Pregunta qué puesto de trabajo están solicitando
            2. DESPUÉS: Solicita nombre completo
            3. DESPUÉS: Solicita email
            4. DESPUÉS: Solicita teléfono
            5. PREGUNTAS ADICIONALES (en orden):
            - ¿En cuánto tiempo podrías incorporarte a laborar?
            - ¿Cuál grado de estudios tienes?
            - ¿Las actividades del puesto son acordes a tu perfil?
            - ¿Qué te pareció más llamativo de la vacante y te interesó?
            - ¿Es lo que estabas buscando?
            - ¿Cuánta experiencia tienes en el puesto?
            - ¿Cuándo fue tu último trabajo y cuánto duraste?
            - ¿Puedes viajar si es necesario para esta vacante u otra?
            - ¿Sabes usar Paquetería Office?
            - ¿Estás de acuerdo con el sueldo?
            - ¿Qué disponibilidad tienes de horario o restricciones?

            6. FILTROS FINALES:
            - ¿Estás de acuerdo con: Examinación de Poligrafía?
            - ¿Estás de acuerdo con: Encuesta Socioeconómica?
            - ¿Estás de acuerdo con: Prueba Antidoping?

            Y si necesitan comprar el servicio transferirlos a wa.me/5215566800185 - +52 (155) 668-00185

            IMPORTANTE sobre investigaciones:
            - Si están de acuerdo: menciona que incluye Investigación de Incidencias, zona adecuada, y salario
            - Informa que si pasan los filtros, irían a entrevistas con el cliente
            - Si pasan con el cliente, se firma el contrato

            Tu rol:
            - Ser profesional, amable y empático
            - Seguir el orden exacto mencionado arriba
            - Hacer preguntas claras y una a la vez
            - Evaluar si el candidato es adecuado para posiciones de confianza

            Cuando el usuario pregunte ESPECÍFICAMENTE sobre detalles de una vacante (salario, horario, responsabilidades), 
            recibirás la descripción completa del puesto en tags <job_description>.
            """
        
        return {"message": "Job deleted successfully", "filename": filename}
    
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/jobs/{filename}")
async def get_job(filename: str):
    """Get a specific job description file content"""
    try:
        filepath = JOBS_DIR / filename
        
        if not filepath.exists():
            raise HTTPException(status_code=404, detail="Job file not found")
        
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return {
            "filename": filename,
            "title": filename.replace('.txt', '').replace('_', ' ').title(),
            "description": content
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/jobs/{filename}")
async def update_job(filename: str, request: dict):
    """Update a job description file"""
    try:
        filepath = JOBS_DIR / filename
        
        if not filepath.exists():
            raise HTTPException(status_code=404, detail="Job file not found")
        
        new_description = request.get("job_description", "").strip()
        
        if not new_description:
            raise HTTPException(status_code=400, detail="Job description is required")
        
        # Update the file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_description)
        
        return {"message": "Job updated successfully", "filename": filename}
    
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/candidate/{session_id}/audit")
async def audit_candidate(session_id: str, db: Session = Depends(get_db)):
    """Use AI to audit and correct candidate data from conversation history"""
    try:
        # Get candidate and conversation history
        candidate = crud.get_candidate_by_session(db, session_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="Candidate not found")
        
        conversations = crud.get_conversations_by_session(db, session_id)
        if not conversations:
            raise HTTPException(status_code=400, detail="No conversation history found")
        
        # Build conversation transcript
        transcript = "\n\n".join([
            f"Usuario: {conv.user_message}\nPetrof: {conv.bot_response}"
            for conv in conversations
        ])
        
        # Create AI prompt for data extraction
        audit_prompt = f"""Analiza la siguiente conversación de reclutamiento y extrae EXACTAMENTE la información del candidato.

                CONVERSACIÓN:
                {transcript}

                INSTRUCCIONES:
                Extrae los siguientes datos del candidato de la conversación. Si un dato NO está presente, devuelve null.
                Responde SOLO con un objeto JSON válido, sin texto adicional.

                FORMATO DE RESPUESTA (JSON):
                {{
                    "name": "nombre completo del candidato o null",
                    "email": "email del candidato o null",
                    "phone": "teléfono del candidato o null",
                    "position_applied": "puesto al que aplicó o null",
                    "incorporation_time": "tiempo de incorporación mencionado o null",
                    "education_level": "nivel de estudios o null",
                    "job_interest_reason": "razón de interés en la vacante o null",
                    "years_experience": "años de experiencia o null",
                    "last_job_info": "información del último trabajo o null",
                    "can_travel": true/false/null,
                    "knows_office": true/false/null,
                    "salary_agreement": true/false/null,
                    "schedule_availability": "disponibilidad de horario o null",
                    "accepts_polygraph": true/false/null,
                    "accepts_socioeconomic": true/false/null,
                    "accepts_drug_test": true/false/null
                }}

                REGLAS IMPORTANTES:
                - Para campos booleanos: usa true si la respuesta es afirmativa (sí, claro, por supuesto, etc.), false si es negativa (no), null si no se mencionó
                - Para campos de texto: extrae la respuesta exacta del usuario
                - NO inventes información
                - Si hay dudas, usa null
                """

        # Call Gemini API for audit
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=audit_prompt
        )
        
        # Parse AI response
        import json
        import re
        
        response_text = response.text.strip()
        
        # Remove markdown code blocks if present
        response_text = re.sub(r'```json\s*|\s*```', '', response_text)
        
        try:
            extracted_data = json.loads(response_text)
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail="Error parsing AI response")
        
        # Update candidate with extracted data
        update_fields = {}
        
        # Only update fields that are not null
        for field, value in extracted_data.items():
            if value is not None:
                update_fields[field] = value
        
        if update_fields:
            updated_candidate = crud.update_candidate(db, session_id, **update_fields)
            
            return {
                "message": "Candidate data audited and updated successfully",
                "updated_fields": list(update_fields.keys()),
                "data": extracted_data
            }
        else:
            return {
                "message": "No data extracted from conversation",
                "data": extracted_data
            }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error during audit: {str(e)}")


@app.get("/api/settings/survey_chat_enabled")
async def get_survey_chat_status(db: Session = Depends(get_db)):
    """Get survey chat enabled status"""
    try:
        setting = db.query(SystemSettings).filter(
            SystemSettings.setting_key == "survey_chat_enabled"
        ).first()
        
        if not setting:
            # Create default setting
            setting = SystemSettings(
                setting_key="survey_chat_enabled",
                setting_value="true"
            )
            db.add(setting)
            db.commit()
            db.refresh(setting)  # Add this line
        
        return {"value": setting.setting_value}
    except Exception as e:
        import traceback
        traceback.print_exc()
        # Return default value if there's an error
        return {"value": "true"}

@app.post("/api/settings/survey_chat_enabled")
async def update_survey_chat_status(request: dict, db: Session = Depends(get_db)):
    """Update survey chat enabled status"""
    try:
        value = request.get("value", "false")
        
        setting = db.query(SystemSettings).filter(
            SystemSettings.setting_key == "survey_chat_enabled"
        ).first()
        
        if setting:
            setting.setting_value = value
            setting.updated_at = datetime.utcnow()
        else:
            setting = SystemSettings(
                setting_key="survey_chat_enabled",
                setting_value=value
            )
            db.add(setting)
        
        db.commit()
        db.refresh(setting)  # Add this line
        
        return {"message": "Survey chat status updated", "value": value}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


