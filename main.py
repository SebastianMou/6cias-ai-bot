from fastapi import FastAPI, Depends, Request, HTTPException, File, UploadFile, Form
from typing import List
import shutil
import uuid
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
from models import Conversation, Candidate, InterviewQuestion, SystemSettings, SurveyResponse, SurveyConversation, ConnectionLog
from schemas import (
    ChatRequest, ChatResponse, ChatHistoryResponse,
    ConversationCreate, CandidateCreate
)
from models import ConnectionLog
import crud
from datetime import datetime
import os
from pathlib import Path
import re
import unicodedata

SURVEY_FILES_DIR = Path("survey_files")
SURVEY_FILES_DIR.mkdir(exist_ok=True)

# Directory where job descriptions are stored
JOBS_DIR = Path("jobs")


# Configuration
MAX_MESSAGES_PER_SESSION = 60

app = FastAPI(title="6Cias Chatbot API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Run migrations on startup
@app.on_event("startup")
async def startup_event():
    print("🔄 Recreating database tables...")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables recreated!")
client = genai.Client(api_key=settings.gemini_api_key)

async def get_ip_geolocation(ip_address: str):
    """Get comprehensive geolocation data for an IP address"""
    if not ip_address or ip_address == 'unknown':
        return None
    
    try:
        async with httpx.AsyncClient() as client:
            # Use ip-api.com with all available fields
            # Free tier: 45 requests per minute
            response = await client.get(
                f'http://ip-api.com/json/{ip_address}',
                params={
                    'fields': 'status,message,country,countryCode,region,regionName,city,zip,lat,lon,timezone,isp,org,as,proxy,mobile,query'
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('status') == 'success':
                    # Format the geolocation data
                    geo_data = {
                        'ip': data.get('query'),
                        'city': data.get('city'),
                        'region': data.get('regionName'),
                        'region_code': data.get('region'),
                        'country': data.get('country'),
                        'country_code': data.get('countryCode'),
                        'postal_code': data.get('zip'),
                        'latitude': data.get('lat'),
                        'longitude': data.get('lon'),
                        'timezone': data.get('timezone'),
                        'isp': data.get('isp'),
                        'organization': data.get('org'),
                        'asn': data.get('as'),
                        'is_proxy': data.get('proxy', False),
                        'is_mobile': data.get('mobile', False)
                    }
                    
                    print(f"📍 [IP GEO] {ip_address} → {geo_data['city']}, {geo_data['region']}, {geo_data['country']}")
                    return geo_data
                else:
                    print(f"❌ Geolocation API error: {data.get('message')}")
                    return None
                    
    except Exception as e:
        print(f"❌ Error getting geolocation: {e}")
    
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
    Note: si el candidato menciona un trabajo que no figura en la lista, se limita a la entrevista, obviamente, surgen preguntas como "¿Qué te pareció más llamativo de la vacante y te interesó?" (porque no hay listado para ese puesto)

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

class ConnectionLogAdmin(ModelView, model=ConnectionLog):
    column_list = [ConnectionLog.id, ConnectionLog.session_id, ConnectionLog.connection_quality, ConnectionLog.event_type, ConnectionLog.created_at]
    name = "Log de Conexión"
    name_plural = "Logs de Conexión"

admin.add_view(SurveyConversationAdmin)
admin.add_view(SurveyResponseAdmin)
admin.add_view(CandidateAdmin)
admin.add_view(ConversationAdmin)
admin.add_view(ConnectionLogAdmin)  

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
        # Create extraction prompt - SIMPLIFIED to only extract mentioned fields
        extraction_prompt = f"""Analiza la siguiente conversación de una encuesta socioeconómica y extrae TODOS los datos mencionados.

            CONVERSACIÓN:
            {conversation_text}

            INSTRUCCIONES IMPORTANTES:
            - Extrae SOLO información explícitamente mencionada en la conversación
            - Si un dato no fue mencionado, NO lo incluyas en el JSON
            - Para campos booleanos: usa true o false (sin comillas)
            - Para texto: usa comillas dobles
            - Para números: sin comillas
            - Asegúrate de cerrar correctamente el JSON con llaves

            Responde con un objeto JSON válido que contenga ÚNICAMENTE los campos mencionados en la conversación.
            Campos disponibles: candidate_name, company_name, date_of_birth, phone_whatsapp, email, full_address, share_location, curp, nss_imss, rfc_tax_id, utility_provider, utility_contract_number, utility_account_holder, housing_type, lives_with, dependents_count, has_water, has_electricity, has_internet, has_gas, real_estate, vehicles, businesses, formal_savings, debts, credit_bureau, education_level, has_education_proof, position_applying, organization, area_division, application_reason, how_found_vacancy, current_employment, previous_employment, salary_bonus, family_support, informal_business_income, expenses_list, expenses_amounts, groceries, alimony, food_out, rent, utilities, internet_cable, transportation, uber_taxi, school_expenses, courses, books_supplies, entertainment, vacations, insurance, taxes, clothing, laundry, internet_expenses, has_medical_condition, takes_permanent_medication, primary_family_contacts, secondary_family_contacts, work_references, personal_reference, work_reference_1_name, work_reference_1_phone, work_reference_1_relationship, work_reference_2_name, work_reference_2_phone, work_reference_2_relationship, emergency_contact_name, emergency_contact_phone, emergency_contact_relationship, partner_name, partner_phone, partner_occupation, partner_relationship_quality, children_names, children_count, home_references, crime_in_area, services_quality, security_quality, surveillance_quality, bedrooms, dining_room, living_room, bathrooms, floors, garden, kitchen, air_conditioning, garage, laundry_area, pool, sports_areas, study_office, has_federal_license, federal_license_number, medical_folio, license_validity, license_type, has_state_license, state_license_info, state_license_number, state_license_validity, facebook_profile_url, home_photos_submitted, street_photos_submitted, recommendation_letters_submitted, has_legal_issues, legal_issues_description, evidence_sent

            Ejemplo de respuesta correcta:
            {{"candidate_name": "Juan Pérez", "phone_whatsapp": "5551234567", "email": "juan@example.com"}}
            
            Responde SOLO con el JSON, sin markdown ni explicaciones:"""
        
        print("[AUDIT] Calling Gemini API...")

        # Call Gemini API
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[{"role": "user", "parts": [{"text": extraction_prompt}]}],
                config={
                    "temperature": 0.1,
                    "max_output_tokens": 4096  # CHANGED from 2000 to 4096
                }
            )
            print("[AUDIT] Gemini API response received successfully")
        except Exception as api_error:
            print(f"[AUDIT ERROR] Gemini API Error: {str(api_error)}")
            raise HTTPException(status_code=500, detail=f"Gemini API Error: {str(api_error)}")
        
        # Parse JSON response
        import json
        import re
        
        response_text = response.text.strip()
        print(f"[AUDIT] Raw response length: {len(response_text)} chars")
        
        # Remove markdown code blocks if present
        response_text = re.sub(r'^```json\s*', '', response_text)
        response_text = re.sub(r'^```\s*', '', response_text)
        response_text = re.sub(r'\s*```$', '', response_text)
        response_text = response_text.strip()

        print(f"[AUDIT] Cleaned response length: {len(response_text)} chars")
        print(f"[AUDIT] About to parse JSON...")
        
        try:
            extracted_data = json.loads(response_text)
            print(f"[AUDIT] Successfully parsed JSON with {len(extracted_data)} fields")
            print(f"[AUDIT] Fields: {list(extracted_data.keys())[:10]}...")  # Print first 10 keys
        except json.JSONDecodeError as json_err:
            print(f"[AUDIT ERROR] JSON parsing failed: {str(json_err)}")
            print(f"[AUDIT ERROR] Full response text:\n{response_text}")
            raise HTTPException(status_code=500, detail=f"Error parsing AI response: {str(json_err)}")
        
        # Update survey with extracted data (only non-null values)
        update_data = {k: v for k, v in extracted_data.items() if v is not None}
        
        print(f"[AUDIT] Preparing to update {len(update_data)} fields")
        print(f"[AUDIT] Fields to update: {list(update_data.keys())[:10]}...")
        
        if update_data:
            try:
                survey_crud.update_survey_field(db, session_id, **update_data)
                print(f"[AUDIT] Successfully updated database")
            except Exception as db_error:
                print(f"[AUDIT ERROR] Database update failed: {str(db_error)}")
                import traceback
                traceback.print_exc()
                raise HTTPException(status_code=500, detail=f"Database update error: {str(db_error)}")
        
        print("[AUDIT] Audit completed successfully!")
        
        return {
            "message": "Audit completed successfully",
            "fields_updated": len(update_data),
            "extracted_data": update_data
        }
        
    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        print(f"[AUDIT ERROR] Unexpected error: {str(e)}")
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
    """Get all surveys with statistics"""
    try:
        from models import ConnectionLog
        
        surveys = db.query(SurveyResponse).order_by(SurveyResponse.created_at.desc()).all()
        
        total = len(surveys)
        completed = sum(1 for s in surveys if s.survey_completed)
        in_progress = sum(1 for s in surveys if s.current_section and not s.survey_completed)
        
        # Today's surveys
        today = datetime.utcnow().date()
        today_count = sum(1 for s in surveys if s.created_at.date() == today)
        
        # Format surveys with connection data
        formatted_surveys = []
        for survey in surveys:
            try:
                # Get connection stats for this survey
                connection_logs = db.query(ConnectionLog).filter(
                    ConnectionLog.session_id == survey.session_id
                ).order_by(ConnectionLog.created_at.desc()).all()
                
                # Calculate connection stats
                total_logs = len(connection_logs)
                offline_count = sum(1 for log in connection_logs if log.event_type == 'offline')
                poor_quality_count = sum(1 for log in connection_logs if log.connection_quality in ['muy baja', 'baja'])
                
                # Get latest connection status
                latest_connection = connection_logs[0] if connection_logs else None
                
                connection_stats = {
                    "total_checks": total_logs,
                    "offline_events": offline_count,
                    "poor_quality_count": poor_quality_count,
                    "latest_quality": latest_connection.connection_quality if latest_connection else "desconocida",
                    "latest_speed": latest_connection.connection_speed if latest_connection else "N/A",
                    "has_issues": offline_count > 0 or poor_quality_count > 2
                }
            except Exception as e:
                print(f"Error getting connection stats for {survey.session_id}: {e}")
                connection_stats = {
                    "total_checks": 0,
                    "offline_events": 0,
                    "poor_quality_count": 0,
                    "latest_quality": "desconocida",
                    "latest_speed": "N/A",
                    "has_issues": False
                }
            
            formatted_surveys.append({
                "session_id": survey.session_id,
                "candidate_name": survey.candidate_name,
                "company_name": survey.company_name,
                "current_section": survey.current_section,
                "survey_completed": survey.survey_completed,
                "created_at": survey.created_at.isoformat() if survey.created_at else None,
                "updated_at": survey.updated_at.isoformat() if survey.updated_at else None,
                "date_of_birth": survey.date_of_birth,
                "phone_whatsapp": survey.phone_whatsapp,
                "email": survey.email,
                "full_address": survey.full_address,
                "housing_type": survey.housing_type,
                "lives_with": survey.lives_with,
                "real_estate": survey.real_estate,
                "vehicles": survey.vehicles,
                "businesses": survey.businesses,
                "formal_savings": survey.formal_savings,
                "debts": survey.debts,
                "credit_bureau": survey.credit_bureau,
                "education_level": survey.education_level,
                "position_applying": survey.position_applying,
                "organization": survey.organization,
                "current_employment": survey.current_employment,
                "salary_bonus": survey.salary_bonus,
                "expenses_list": survey.expenses_list,
                "expenses_amounts": survey.expenses_amounts,
                "has_medical_condition": survey.has_medical_condition,
                "primary_family_contacts": survey.primary_family_contacts,
                "work_references": survey.work_references,
                "personal_reference": survey.personal_reference,
                "home_references": survey.home_references,
                "crime_in_area": survey.crime_in_area,
                "bedrooms": survey.bedrooms,
                "has_federal_license": survey.has_federal_license,
                "evidence_sent": survey.evidence_sent,
                
                # ADD CONNECTION DATA HERE
                "connection_stats": connection_stats
            })
        
        return {
            "total": total,
            "completed": completed,
            "in_progress": in_progress,
            "today": today_count,
            "surveys": formatted_surveys
        }
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/survey/{session_id}")
async def get_survey_by_id(session_id: str, db: Session = Depends(get_db)):
    """Get a specific survey response"""
    survey = survey_crud.get_survey_by_session(db, session_id)
    if not survey:
            # Return empty survey structure instead of 404
            return {
                "session_id": session_id,
                "candidate_name": None,
                "survey_completed": False,
                "current_section": None,
                "created_at": None,
                "updated_at": None
            }
    
    # Return ALL fields (use saved IP geolocation data from database)
    return {
        "session_id": survey.session_id,
        "candidate_name": survey.candidate_name,
        "company_name": survey.company_name,
        "user_ip": survey.user_ip,
        
        # IP Geolocation fields (from database)
        "ip_city": survey.ip_city,
        "ip_region": survey.ip_region,
        "ip_country": survey.ip_country,
        "ip_postal_code": survey.ip_postal_code,
        "ip_latitude": survey.ip_latitude,
        "ip_longitude": survey.ip_longitude,
        "ip_timezone": survey.ip_timezone,
        "ip_isp": survey.ip_isp,
        "ip_organization": survey.ip_organization,
        "ip_asn": survey.ip_asn,
        "ip_is_proxy": survey.ip_is_proxy,
        "ip_is_mobile": survey.ip_is_mobile,

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

        # Browser Fingerprinting
        "browser_user_agent": survey.browser_user_agent,
        "browser_name": survey.browser_name,
        "browser_version": survey.browser_version,
        "browser_os": survey.browser_os,
        "browser_platform": survey.browser_platform,
        "browser_language": survey.browser_language,
        "browser_languages": survey.browser_languages,
        "browser_timezone": survey.browser_timezone,
        "browser_timezone_offset": survey.browser_timezone_offset,
        "screen_width": survey.screen_width,
        "screen_height": survey.screen_height,
        "screen_avail_width": survey.screen_avail_width,
        "screen_avail_height": survey.screen_avail_height,
        "screen_color_depth": survey.screen_color_depth,
        "screen_pixel_depth": survey.screen_pixel_depth,
        "device_pixel_ratio": survey.device_pixel_ratio,
        "cpu_cores": survey.cpu_cores,
        "device_memory": survey.device_memory,
        "max_touch_points": survey.max_touch_points,
        "has_touch_support": survey.has_touch_support,
        "connection_type": survey.connection_type,
        "connection_downlink": survey.connection_downlink,
        "connection_rtt": survey.connection_rtt,
        "connection_effective_type": survey.connection_effective_type,
        "canvas_fingerprint": survey.canvas_fingerprint,
        "webgl_vendor": survey.webgl_vendor,
        "webgl_renderer": survey.webgl_renderer,
        "do_not_track": survey.do_not_track,
        "cookies_enabled": survey.cookies_enabled,
        "local_storage_enabled": survey.local_storage_enabled,
        "session_storage_enabled": survey.session_storage_enabled,
        "indexed_db_enabled": survey.indexed_db_enabled,
        "permissions_notifications": survey.permissions_notifications,
        "permissions_geolocation": survey.permissions_geolocation,
        "battery_charging": survey.battery_charging,
        "battery_level": survey.battery_level,
        "plugins_list": survey.plugins_list,
        "fonts_available": survey.fonts_available,

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
async def survey_chat(session_id: str = Form(...),message: str = Form(...),ip_address: str = Form(None),files: List[UploadFile] = File(None),db: Session = Depends(get_db)):
    print(f"[SURVEY CHAT] Received request - Session: {session_id}, Message: {message[:50]}...")  # ADD THIS LINE

    try:
        # Check if survey chat is enabled
        chat_setting = db.query(SystemSettings).filter(
            SystemSettings.setting_key == "survey_chat_enabled"
        ).first()

        if chat_setting and chat_setting.setting_value == "false":
            return {
                "response": "Lo siento, el chat de encuestas está temporalmente desactivado. Por favor, intenta más tarde.",
                "session_id": session_id,
                "progress": 0
            }
        
        if not session_id or not message:
            raise HTTPException(status_code=400, detail="Missing session_id or message")
        
        # Handle file uploads
        uploaded_files_info = []
        if files:
            session_folder = SURVEY_FILES_DIR / session_id
            session_folder.mkdir(exist_ok=True)
            
            for file in files:
                if file.filename:
                    # Generate unique filename
                    file_extension = Path(file.filename).suffix
                    unique_filename = f"{uuid.uuid4()}{file_extension}"
                    file_path = session_folder / unique_filename
                    
                    # Save file
                    with open(file_path, "wb") as buffer:
                        shutil.copyfileobj(file.file, buffer)
                    
                    # Store file info
                    file_info = {
                        "original_name": file.filename,
                        "saved_path": str(file_path),
                        "file_type": file.content_type,
                        "file_size": file_path.stat().st_size
                    }
                    uploaded_files_info.append(file_info)
                    
                    # Save to database
                    from models import SurveyFile
                    db_file = SurveyFile(
                        session_id=session_id,
                        file_name=file.filename,
                        file_path=str(file_path),
                        file_type=file.content_type,
                        file_size=file_path.stat().st_size
                    )
                    db.add(db_file)
            
            db.commit()
            
            # Append file info to message
            if uploaded_files_info:
                file_names = ", ".join([f["original_name"] for f in uploaded_files_info])
                message = f"{message}\n[Archivos adjuntos: {file_names}]"
        
        # Get or create survey response
        survey = survey_crud.get_survey_by_session(db, session_id)
        if not survey:
            survey = survey_crud.create_survey_response(db, session_id)

        # Save IP address and get geolocation data
        if ip_address and (not survey.user_ip or not survey.ip_city):
            survey_crud.update_survey_field(db, session_id, user_ip=ip_address)
            
            # Get comprehensive geolocation data
            geo_data = await get_ip_geolocation(ip_address)

            if geo_data:
                # Store geolocation data in dedicated fields
                survey_crud.update_survey_field(
                    db, 
                    session_id,
                    ip_city=geo_data.get('city'),
                    ip_region=geo_data.get('region'),
                    ip_country=geo_data.get('country'),
                    ip_postal_code=geo_data.get('postal_code'),
                    ip_latitude=str(geo_data.get('latitude')),
                    ip_longitude=str(geo_data.get('longitude')),
                    ip_timezone=geo_data.get('timezone'),
                    ip_isp=geo_data.get('isp'),
                    ip_organization=geo_data.get('organization'),
                    ip_asn=geo_data.get('asn'),
                    ip_is_proxy=geo_data.get('is_proxy', False),
                    ip_is_mobile=geo_data.get('is_mobile', False)
                )
                
                print(f"✅ [IP GEO SAVED] {geo_data.get('city')}, {geo_data.get('region')}, {geo_data.get('country')}")
        
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
        
        # Track current section based on conversation length
        current_section = "Inicio"
        conversation_count = len(history)
        if conversation_count >= 1: current_section = "A-Bienvenida"
        if conversation_count >= 3: current_section = "B-Datos Básicos"
        if conversation_count >= 7: current_section = "C-Documentos"
        if conversation_count >= 11: current_section = "D-Referencias"
        if conversation_count >= 13: current_section = "E-Gastos"
        if conversation_count >= 16: current_section = "F-Bienes"
        if conversation_count >= 18: current_section = "G-Deudas"
        if conversation_count >= 20: current_section = "H-Familia"
        if conversation_count >= 29: current_section = "I-Antecedentes"
        if conversation_count >= 31: current_section = "J-Evidencias"
        if conversation_count >= 36: current_section = "K-Cierre"
        
        # Update current section in database
        survey_crud.update_survey_field(db, session_id, current_section=current_section)
        
        # Get system prompt from database or use default
        prompt_setting = db.query(SystemSettings).filter(
            SystemSettings.setting_key == "survey_system_prompt"
        ).first()
        
        if prompt_setting and prompt_setting.setting_value:
            system_prompt = prompt_setting.setting_value
        else:
            # Default prompt if not found in database
            system_prompt = f"""Eres Clippy, un asistente virtual de verificación socioeconómica para 6Cias. Tu objetivo es recopilar información y evidencias de forma clara, ordenada y respetuosa, para completar la certificación de ingreso a un puesto de confianza.

            REGLAS GENERALES:
            - Haz preguntas una por una y espera respuesta antes de seguir
            - Si la persona contesta incompleto, pide precisión sin regañar
            - Mantén tono profesional, directo y amable
            - Al final, resume lo recabado y lista lo pendiente

            ORDEN DE LA ENCUESTA (SEGUIR ESTRICTAMENTE):

            A) BIENVENIDA E INTRODUCCIÓN:
            0. "Perfecto, vamos a comenzar con la encuesta. Soy el asistente virtual Clippy y te voy a estar guiando a través del proceso. Por favor responde lo más cercano a la verdad para que podamos completar esta prueba exitosamente."
            1. "¿Qué empresa está pidiendo tu certification y qué puesto es para certificar?"
            
            DATOS PERSONALES BÁSICOS:
            2. Nombre completo (apellidos y nombres)
            3. Fecha y lugar de nacimiento (o donde te hayan registrado)

            3. Correo electrónico
            4. Teléfono celular donde tengas habilitados mensajes electrónicos

            C) DOCUMENTOS PERSONALES:
            5. CURP (en este caso tu INE la trae o alguna licencia de conducir, es probable que la traiga en la parte de atrás)
            6. Número de seguridad social o IMSS
            7. Número registrado para impuestos (RFC, tax ID o ITIN)
            8. Licencia (si eres operador, la federal con tu número médico)
            9. Comprobante de domicilio con el número de contrato, qué empresa es y a nombre de quién está registrado (Si tienes CFE en México, es la que más ocupamos para verificar)

            D) REFERENCIAS LABORALES:
            10. "De casualidad, ¿tienes alguna referencia laboral nueva que quieras ingresar? Ya sea de compañeros, amistades, superiores o personas que te hayan visto trabajar, necesitamos ver sus números con WhatsApp."
                - "No importa que los hayas dado antes, esto acelerará el proceso"

            E) ENCUESTA SOCIOECONÓMICA - GASTOS E INGRESOS:
            11. "Vamos a ver la encuesta socioeconómica. En este caso, quisiera saber dónde es donde gastas más dinero, en qué áreas"
            12. "¿Cuánto es lo que gastas en total al mes? Un aproximado"
            13. "¿Tienes algún otro gasto o ingreso?"
            14. "¿Cuánto es lo que estás ganando? ¿Cuánto es lo que estás percibiendo? ¿Tienes algún negocio, rentas? Cuéntame a qué se dedican"

            F) BIENES PATRIMONIALES:
            15. "¿Cuáles son tus bienes patrimoniales a tu nombre? Casa, auto, negocios. Descríbelos en una sola línea, por favor"

            G) DEUDAS Y BURÓ:
            16. "¿Qué deudas tienes? Recuerda que vamos a investigar todo y que van a salir incluso deudas mercantiles o demandas, ya sea bancos, casa, auto, hipoteca, personales. ¿Qué deudas tienes?"
            17. "¿Te encuentras boletinado en algún buró de crédito?"

            H) ENCUESTA FAMILIAR:
            18. Contactos de tu padre y madre: nombre completo y a qué se dedican (si no tiene padre, pasar a la siguiente)
            19. Contactos de tus hermanos: nombres completos, número de contacto de WhatsApp y a qué se dedican
            20. "¿Dónde viven todos ellos? ¿Me puedes escribir?"
            21. "¿Los contactas seguido? ¿A quiénes?"
            22. "¿Me puedes decir si quieres que pongamos un contacto de emergencia en alguno de ellos?"
            23. En el caso de que tengas pareja: nombre, número y a qué se dedica
            24. "¿Tienes descendencia, hijos, adoptivos o de algún otro matrimonio? ¿Me puedes dar sus nombres completos?"
            25. "¿Gustas que pongamos a tu pareja como contacto de emergencia?"
            26. "¿Cómo es su relación?"
            27. "¿Todos ellos viven contigo o dónde viven? ¿Qué direcciones?" (Si no sabe la dirección exacta: "¿Me puedes dar un aproximado, colonia o por dónde están?")

            I) ANTECEDENTES Y VERIFICACIÓN:
            28. "Necesitamos que seas muy sincero en estas respuestas. Dime, ¿has tenido demandas, malas experiencias, antecedentes de problemas penales, mercantiles, alguna cuestión que sea adversa a las compañías que podamos encontrar? Recuerda que todo lo vamos a investigar y si tienes aunque sea un accidente es mejor reportarnos. ¿Tienes algo que reportar ahora que nosotros podríamos revisar y encontrar y que pueda salir mal en tu certificación?"

            J) EVIDENCIAS Y FOTOGRAFÍAS:
            29. "Te voy a pedir si me puedes mandar la fotografía de tu perfil de Facebook. Esto es para encontrarlo un poco más rápido y entregar más rápido el reporte, aunque de por sí los vamos a buscar"

            30. "Te voy a pedir que ahora, por favor, terminando esta encuesta, mandes cinco fotos de alrededor de toda tu casa."

            31. "Al mismo tiempo, terminando esas cinco fotos, toma unas cinco fotos de la calle principal, ya sea la entrada principal a tu fraccionamiento, a tu complejo, a tu condominio, a tu casa, donde se pueda ver desde afuera o desde adentro hacia afuera la casa, hacia la calle y la podemos nosotros certificar como que sí es tu vivienda"

            32. "Si me puedes compartir cartas de recomendación que tengas de manera digital"

            CANALES DE ENVÍO DE EVIDENCIAS:
            - Correo: solucion@6cias.com
            - WhatsApp: [número proporcionado de coordinación]
            "Todo esto al correo de solucion@6cias.com o al número proporcionado de coordinación a través de WhatsApp"

            K) CIERRE:
            "Muy bien, muchas gracias. Hemos terminado con la encuesta socioeconómica. La información será utilizada para tu proceso de certificación."

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
        
        # Extract data from user message and update survey based on conversation context
        user_msg_lower = message.lower()
        bot_response_lower = bot_response.lower()

        # Detect name in first message
        if "empresa" in bot_response_lower or "compañía" in bot_response_lower:
            if "aplicando" in bot_response_lower or "trabajar" in bot_response_lower:
                survey_crud.update_survey_field(db, session_id, company_name=message.strip())


        # Extract data based on bot's last question context
        # Check what the bot just asked to know what data we're receiving

        # A) Personal documents
        if "curp" in bot_response_lower and len(message) >= 16:
            survey_crud.update_survey_field(db, session_id, curp=message.strip())
        elif "seguridad social" in bot_response_lower or "imss" in bot_response_lower:
            survey_crud.update_survey_field(db, session_id, nss_imss=message.strip())
        elif "rfc" in bot_response_lower or "tax id" in bot_response_lower or "itin" in bot_response_lower:
            survey_crud.update_survey_field(db, session_id, rfc_tax_id=message.strip())
        elif "comprobante de domicilio" in bot_response_lower or "cfe" in bot_response_lower:
            survey_crud.update_survey_field(db, session_id, utility_provider=message.strip())

        # B) Birth information
        if "fecha" in bot_response_lower and "nacimiento" in bot_response_lower:
            survey_crud.update_survey_field(db, session_id, date_of_birth=message.strip())

        # C) Contact info
        if "correo" in bot_response_lower or "email" in bot_response_lower:
            survey_crud.update_survey_field(db, session_id, email=message.strip())
        elif "teléfono" in bot_response_lower or "celular" in bot_response_lower:
            survey_crud.update_survey_field(db, session_id, phone_whatsapp=message.strip())

        # D) Work references
        if "referencia laboral" in bot_response_lower:
            survey_crud.update_survey_field(db, session_id, work_references=message.strip())

        # E) Expenses
        if "gastas más dinero" in bot_response_lower or "áreas" in bot_response_lower:
            survey_crud.update_survey_field(db, session_id, expenses_list=message.strip())
        elif "gastas en total" in bot_response_lower or "aproximado" in bot_response_lower:
            survey_crud.update_survey_field(db, session_id, expenses_amounts=message.strip())

        # F) Income
        if "ganando" in bot_response_lower or "percibiendo" in bot_response_lower:
            survey_crud.update_survey_field(db, session_id, salary_bonus=message.strip())

        # G) Assets
        if "bienes patrimoniales" in bot_response_lower:
            survey_crud.update_survey_field(db, session_id, real_estate=message.strip())

        # H) Debts
        if "deudas" in bot_response_lower and "tienes" in bot_response_lower:
            survey_crud.update_survey_field(db, session_id, debts=message.strip())
        elif "buró de crédito" in bot_response_lower:
            survey_crud.update_survey_field(db, session_id, credit_bureau=message.strip())

        # I) Family contacts
        if "padre" in bot_response_lower or "madre" in bot_response_lower:
            survey_crud.update_survey_field(db, session_id, primary_family_contacts=message.strip())
        elif "hermanos" in bot_response_lower:
            current = survey.primary_family_contacts or ""
            survey_crud.update_survey_field(db, session_id, primary_family_contacts=current + "\n" + message.strip())
        elif "pareja" in bot_response_lower and "nombre" in bot_response_lower:
            survey_crud.update_survey_field(db, session_id, partner_name=message.strip())
        elif "hijos" in bot_response_lower or "descendencia" in bot_response_lower:
            survey_crud.update_survey_field(db, session_id, children_names=message.strip())

        # J) Background check
        if "demandas" in bot_response_lower or "antecedentes" in bot_response_lower:
            has_issues = "sí" in user_msg_lower or "si" in user_msg_lower
            survey_crud.update_survey_field(db, session_id, 
                                        has_legal_issues=has_issues,
                                        legal_issues_description=message.strip() if has_issues else None)

        # K) Evidence tracking
        if "facebook" in bot_response_lower:
            survey_crud.update_survey_field(db, session_id, facebook_profile_url=message.strip())
        
        # Calculate progress based on new prompt structure (11 main sections A-K)
        sections_completed = 0
        total_sections = 11

        # A) Welcome
        if survey.candidate_name: sections_completed += 1

        # B) Basic personal data (4 fields)
        if survey.date_of_birth and survey.phone_whatsapp and survey.email: sections_completed += 1

        # C) Personal documents (4 fields)
        if survey.curp and survey.nss_imss and survey.rfc_tax_id: sections_completed += 1

        # D) Work references
        if survey.work_references: sections_completed += 1

        # E) Socioeconomic - Expenses
        if survey.expenses_list and survey.expenses_amounts: sections_completed += 1

        # F) Assets
        if survey.real_estate: sections_completed += 1

        # G) Debts
        if survey.debts or survey.credit_bureau: sections_completed += 1

        # H) Family survey
        if survey.primary_family_contacts: sections_completed += 1

        # I) Background check
        if survey.has_legal_issues is not None: sections_completed += 1

        # J) Evidence
        if survey.facebook_profile_url or survey.home_photos_submitted: sections_completed += 1

        # K) Closure (always true if we reach here)
        if len(history) > 25: sections_completed += 1  # Approximate completion

        progress = int((sections_completed / total_sections) * 100)
        
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
            "session_id": session_id,
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
            Note: si el candidato menciona un trabajo que no figura en la lista, se limita a la entrevista, obviamente, surgen preguntas como "¿Qué te pareció más llamativo de la vacante y te interesó?" (porque no hay listado para ese puesto)


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
            Note: si el candidato menciona un trabajo que no figura en la lista, se limita a la entrevista, obviamente, surgen preguntas como "¿Qué te pareció más llamativo de la vacante y te interesó?" (porque no hay listado para ese puesto)

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

@app.get("/survey/{session_id}/files")
async def get_survey_files(session_id: str, db: Session = Depends(get_db)):
    """Get all files uploaded for a survey session"""
    from models import SurveyFile
    
    files = db.query(SurveyFile).filter(
        SurveyFile.session_id == session_id
    ).order_by(SurveyFile.uploaded_at.desc()).all()
    
    return {
        "files": [
            {
                "id": f.id,
                "file_name": f.file_name,
                "file_type": f.file_type,
                "file_size": f.file_size,
                "uploaded_at": f.uploaded_at.isoformat()
            }
            for f in files
        ]
    }

@app.get("/survey/file/{session_id}/{file_id}")
async def get_survey_file(session_id: str, file_id: str, db: Session = Depends(get_db)):
    """Serve a specific file by ID or search by original filename"""
    from models import SurveyFile
    
    # Try to find by ID first
    try:
        file_id_int = int(file_id)
        file_record = db.query(SurveyFile).filter(
            SurveyFile.id == file_id_int,
            SurveyFile.session_id == session_id
        ).first()
    except ValueError:
        # If not a number, try to find by original filename
        file_record = db.query(SurveyFile).filter(
            SurveyFile.session_id == session_id,
            SurveyFile.file_name == file_id
        ).first()
    
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    
    file_path = Path(file_record.file_path)
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    
    return FileResponse(file_path)

@app.get("/api/settings/survey_prompt")
async def get_survey_prompt(db: Session = Depends(get_db)):
    """Get the current survey system prompt"""
    try:
        setting = db.query(SystemSettings).filter(
            SystemSettings.setting_key == "survey_system_prompt"
        ).first()
        
        if setting:
            return {"prompt": setting.setting_value}
        else:
            # Return default prompt if not found
            return {"prompt": "DEFAULT_PROMPT_NOT_SET"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/settings/survey_prompt")
async def update_survey_prompt(request: dict, db: Session = Depends(get_db)):
    """Update the survey system prompt"""
    try:
        prompt = request.get("prompt", "")
        
        if not prompt:
            raise HTTPException(status_code=400, detail="Prompt cannot be empty")
        
        setting = db.query(SystemSettings).filter(
            SystemSettings.setting_key == "survey_system_prompt"
        ).first()
        
        if setting:
            setting.setting_value = prompt
            setting.updated_at = datetime.utcnow()
        else:
            setting = SystemSettings(
                setting_key="survey_system_prompt",
                setting_value=prompt
            )
            db.add(setting)
        
        db.commit()
        db.refresh(setting)
        
        return {"message": "Survey prompt updated successfully", "prompt": prompt}
    except HTTPException as he:
        raise he
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/survey/connection-log")
async def log_connection(
    session_id: str = Form(...),
    connection_quality: str = Form(...),
    connection_speed: float = Form(0),
    connection_type: str = Form(...),
    latency: int = Form(0),
    event_type: str = Form("quality_check"),
    db: Session = Depends(get_db)
):
    """Log user connection quality for monitoring"""
    try:
        from models import ConnectionLog
        
        # Create connection log entry
        connection_log = ConnectionLog(
            session_id=session_id,
            connection_quality=connection_quality,
            connection_speed=str(connection_speed),
            connection_type=connection_type,
            latency=latency,
            event_type=event_type
        )
        db.add(connection_log)
        db.commit()
        
        # Also update the survey's IP and add a note about connection issues
        survey = survey_crud.get_survey_by_session(db, session_id)
        if survey and connection_quality in ['muy baja', 'baja', 'sin conexión']:
            # Log connection problems
            existing_notes = survey.notes or ""
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
            new_note = f"\n[{timestamp}] ⚠️ Conexión {connection_quality} ({connection_type}, {connection_speed} Mbps)"
            survey_crud.update_survey_field(db, session_id, notes=existing_notes + new_note)
        
        print(f"📊 [CONNECTION LOG] Session: {session_id} | Quality: {connection_quality} | Speed: {connection_speed} Mbps | Type: {connection_type} | Latency: {latency}ms | Event: {event_type}")
        
        return {"message": "Connection logged successfully"}
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"❌ Error logging connection: {e}")
        return {"message": "Error logging connection"}
    
@app.get("/survey/{session_id}/connection-history")
async def get_connection_history(session_id: str, db: Session = Depends(get_db)):
    """Get connection history for a survey session"""
    from models import ConnectionLog
    
    logs = db.query(ConnectionLog).filter(
        ConnectionLog.session_id == session_id
    ).order_by(ConnectionLog.created_at.desc()).limit(50).all()
    
    return {
        "logs": [
            {
                "id": log.id,
                "quality": log.connection_quality,
                "speed": log.connection_speed,
                "type": log.connection_type,
                "latency": log.latency,
                "event": log.event_type,
                "timestamp": log.created_at.isoformat()
            }
            for log in logs
        ]
    }

@app.get("/survey/all")
async def get_all_surveys(db: Session = Depends(get_db)):
    """Get all surveys with statistics"""
    from models import ConnectionLog
    
    surveys = db.query(SurveyResponse).order_by(SurveyResponse.created_at.desc()).all()
    
    total = len(surveys)
    completed = sum(1 for s in surveys if s.survey_completed)
    in_progress = sum(1 for s in surveys if s.current_section and not s.survey_completed)
    
    # Today's surveys
    today = datetime.utcnow().date()
    today_count = sum(1 for s in surveys if s.created_at.date() == today)
    
    # Format surveys with connection data
    formatted_surveys = []
    for survey in surveys:
        # Get connection stats for this survey
        connection_logs = db.query(ConnectionLog).filter(
            ConnectionLog.session_id == survey.session_id
        ).order_by(ConnectionLog.created_at.desc()).all()
        
        # Calculate connection stats
        total_logs = len(connection_logs)
        offline_count = sum(1 for log in connection_logs if log.event_type == 'offline')
        poor_quality_count = sum(1 for log in connection_logs if log.connection_quality in ['muy baja', 'baja'])
        
        # Get latest connection status
        latest_connection = connection_logs[0] if connection_logs else None
        
        formatted_surveys.append({
            "id": survey.id,
            "session_id": survey.session_id,
            "candidate_name": survey.candidate_name,
            "email": survey.email,
            "phone_whatsapp": survey.phone_whatsapp,
            "current_section": survey.current_section,
            "survey_completed": survey.survey_completed,
            "created_at": survey.created_at.isoformat() if survey.created_at else None,
            "updated_at": survey.updated_at.isoformat() if survey.updated_at else None,
            
            # ADD CONNECTION DATA
            "connection_stats": {
                "total_checks": total_logs,
                "offline_events": offline_count,
                "poor_quality_count": poor_quality_count,
                "latest_quality": latest_connection.connection_quality if latest_connection else "desconocida",
                "latest_speed": latest_connection.connection_speed if latest_connection else "N/A",
                "has_issues": offline_count > 0 or poor_quality_count > 2
            }
        })
    
    return {
        "total": total,
        "completed": completed,
        "in_progress": in_progress,
        "today": today_count,
        "surveys": formatted_surveys
    }

@app.post("/survey/gps-location")
async def save_gps_location(
    session_id: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    accuracy: float = Form(None),
    gps_timestamp: str = Form(None),
    db: Session = Depends(get_db)
):
    """Save GPS location for survey session"""
    try:
        survey = survey_crud.get_survey_by_session(db, session_id)
        
        if not survey:
            survey = survey_crud.create_survey_response(db, session_id)
        
        # Store GPS data in notes or create new fields
        gps_data = f"GPS: {latitude}, {longitude} (Accuracy: {accuracy}m) at {gps_timestamp}"
        
        existing_notes = survey.notes or ""
        updated_notes = f"{existing_notes}\n{gps_data}" if existing_notes else gps_data
        
        survey_crud.update_survey_field(
            db, 
            session_id, 
            notes=updated_notes
        )
        
        print(f"📍 [GPS] Session: {session_id} | Lat: {latitude}, Lng: {longitude} | Accuracy: {accuracy}m")
        
        return {"message": "GPS location saved", "latitude": latitude, "longitude": longitude}
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))    

@app.post("/survey/browser-fingerprint")
async def save_browser_fingerprint(
    session_id: str = Form(...),
    browser_user_agent: str = Form(None),
    browser_name: str = Form(None),
    browser_version: str = Form(None),
    browser_os: str = Form(None),
    browser_platform: str = Form(None),
    browser_language: str = Form(None),
    browser_languages: str = Form(None),
    browser_timezone: str = Form(None),
    browser_timezone_offset: int = Form(None),
    screen_width: int = Form(None),
    screen_height: int = Form(None),
    screen_avail_width: int = Form(None),
    screen_avail_height: int = Form(None),
    screen_color_depth: int = Form(None),
    screen_pixel_depth: int = Form(None),
    device_pixel_ratio: str = Form(None),
    cpu_cores: int = Form(None),
    device_memory: int = Form(None),
    max_touch_points: int = Form(None),
    has_touch_support: bool = Form(None),
    connection_type: str = Form(None),
    connection_downlink: str = Form(None),
    connection_rtt: int = Form(None),
    connection_effective_type: str = Form(None),
    canvas_fingerprint: str = Form(None),
    webgl_vendor: str = Form(None),
    webgl_renderer: str = Form(None),
    do_not_track: str = Form(None),
    cookies_enabled: bool = Form(None),
    local_storage_enabled: bool = Form(None),
    session_storage_enabled: bool = Form(None),
    indexed_db_enabled: bool = Form(None),
    permissions_notifications: str = Form(None),
    permissions_geolocation: str = Form(None),
    battery_charging: bool = Form(None),
    battery_level: int = Form(None),
    plugins_list: str = Form(None),
    fonts_available: str = Form(None),
    db: Session = Depends(get_db)
):
    """Save browser fingerprint data"""
    
    survey_crud.update_survey_field(
        db, 
        session_id,
        browser_user_agent=browser_user_agent,
        browser_name=browser_name,
        browser_version=browser_version,
        browser_os=browser_os,
        browser_platform=browser_platform,
        browser_language=browser_language,
        browser_languages=browser_languages,
        browser_timezone=browser_timezone,
        browser_timezone_offset=browser_timezone_offset,
        screen_width=screen_width,
        screen_height=screen_height,
        screen_avail_width=screen_avail_width,
        screen_avail_height=screen_avail_height,
        screen_color_depth=screen_color_depth,
        screen_pixel_depth=screen_pixel_depth,
        device_pixel_ratio=device_pixel_ratio,
        cpu_cores=cpu_cores,
        device_memory=device_memory,
        max_touch_points=max_touch_points,
        has_touch_support=has_touch_support,
        connection_type=connection_type,
        connection_downlink=connection_downlink,
        connection_rtt=connection_rtt,
        connection_effective_type=connection_effective_type,
        canvas_fingerprint=canvas_fingerprint,
        webgl_vendor=webgl_vendor,
        webgl_renderer=webgl_renderer,
        do_not_track=do_not_track,
        cookies_enabled=cookies_enabled,
        local_storage_enabled=local_storage_enabled,
        session_storage_enabled=session_storage_enabled,
        indexed_db_enabled=indexed_db_enabled,
        permissions_notifications=permissions_notifications,
        permissions_geolocation=permissions_geolocation,
        battery_charging=battery_charging,
        battery_level=battery_level,
        plugins_list=plugins_list,
        fonts_available=fonts_available
    )
    
    print(f"🔍 [FINGERPRINT] {session_id} | Browser: {browser_name} {browser_version} | OS: {browser_os} | Screen: {screen_width}x{screen_height}")
    
    return {"status": "success", "message": "Browser fingerprint saved"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


