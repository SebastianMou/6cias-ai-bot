from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqladmin import Admin, ModelView
import google.genai as genai  # Line 5

from config import settings
from database import engine, get_db, Base
from models import Conversation, Candidate, InterviewQuestion
from schemas import (
    ChatRequest, ChatResponse, ChatHistoryResponse,
    ConversationCreate, CandidateCreate
)
import crud

import os
from pathlib import Path

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

def load_job_description(job_title: str) -> str:
    """Load job description from file if it exists"""
    # Normalize the job title to match filename
    filename = job_title.lower().replace(" ", "_").replace("ó", "o").replace("á", "a") + ".txt"
    filepath = JOBS_DIR / filename
    
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
        job_name = file.stem.replace("_", " ").title()
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

        # First, check current message for job mention
        for job in get_available_jobs():
            if job.lower() in user_message_lower:
                detected_job = job
                print(f"[FOUND] Job mentioned in current message: '{job}'")
                break

        # If not found in current message, check conversation history (only if user needs details)
        if not detected_job and needs_job_info:
            for conv in history:
                conv_text = (conv.user_message + " " + conv.bot_response).lower()
                for job in get_available_jobs():
                    if job.lower() in conv_text:
                        detected_job = job
                        print(f"[FOUND] Job mentioned in conversation history: '{job}'")
                        break
                if detected_job:
                    break

        # Only load file if: (1) Job just mentioned, OR (2) User asking for details
        should_load_file = detected_job and (
            (detected_job.lower() in user_message_lower) or  # Just mentioned
            needs_job_info  # Asking for details
        )

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
            model='gemini-2.0-flash-exp',
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


