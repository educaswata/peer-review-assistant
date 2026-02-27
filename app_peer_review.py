import streamlit as st
import time
import os
import re

try:
    from google import genai
    from google.genai import types
    genai_available = True
except ImportError:
    genai = None
    genai_available = False

st.set_page_config(page_title="Scientific Peer Review Assistant", page_icon="🔬", layout="wide")

# -------------------------
# PASSWORD PROTECTION
# -------------------------
def check_password():
    """Returns `True` if the user had the correct password."""

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        # Try to get password from secrets, fallback to a default '203560Dk'
        expected_password = ""
        try:
            expected_password = st.secrets.get("APP_PASSWORD", "203560Dk")
        except Exception:
            expected_password = "203560Dk"

        if st.session_state["password"] == expected_password:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # don't store password
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # First run, show input for password.
        st.text_input(
            "Por favor, introduce la contraseña para acceder a la aplicación:", type="password", on_change=password_entered, key="password"
        )
        return False
    elif not st.session_state["password_correct"]:
        # Password not correct, show input + error.
        st.text_input(
            "Por favor, introduce la contraseña para acceder a la aplicación:", type="password", on_change=password_entered, key="password"
        )
        st.error("😕 Contraseña incorrecta")
        return False
    else:
        # Password correct.
        return True

if not check_password():
    st.stop()  # Do not continue running the rest of the app

# If password is correct, the app continues below
st.title("🔬 Scientific Peer Review Assistant")
st.markdown("Sube un manuscrito en PDF para obtener una evaluación preliminar estructurada que apoye tu revisión humana.")

# -------------------------
# SETUP & API KEY
# -------------------------
with st.sidebar:
    st.header("Configuración")
    
    secret_key = ""
    try:
        secret_key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        pass
        
    if not secret_key:
        try:
            import toml
            secrets_path = os.path.join(os.path.dirname(__file__), ".streamlit", "secrets.toml")
            if os.path.exists(secrets_path):
                with open(secrets_path, "r", encoding="utf-8") as f:
                    secrets_data = toml.load(f)
                    secret_key = secrets_data.get("general", {}).get("GEMINI_API_KEY", "")
        except Exception:
            pass

    if "api_key" not in st.session_state or not st.session_state.api_key.strip():
        st.session_state.api_key = secret_key

    with st.expander("Configuración Avanzada", expanded=False):
        api_key_input = st.text_input("Google Gemini API Key", value=st.session_state.api_key, type="password")
        st.session_state.api_key = api_key_input
        
    api_key = st.session_state.api_key

    st.markdown("---")
    st.markdown("**Instrucciones:**")
    st.markdown("1. Sube el manuscrito en PDF.\n2. (Opcional) Pega las guías de la revista.\n3. Haz clic en 'Generar Revisión'.")

# -------------------------
# CHAT INTERFACE PIPELINE
# -------------------------

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Hello! I am your Scientific Peer Review Assistant. Please upload the manuscript PDF in the sidebar to begin. You can ask me questions about specific sections, discuss potential flaws, or instruct me on what to focus on. Once we've discussed the paper, you can click 'Generar Revisión Estructurada' below."}
    ]

# Initialize uploaded files tracker
if "processed_files" not in st.session_state:
    st.session_state.processed_files = []

# Sidebar for Image/File Uploads and Guidelines
with st.sidebar:
    st.header("Datos del Manuscrito")
    uploaded_files = st.file_uploader("Sube manuscritos (PDF)", accept_multiple_files=True, type=['pdf'])
    
    journal_guidelines = st.text_area(
        "Guías de la revista (Opcional)", 
        value=st.session_state.get('journal_guidelines', ''),
        placeholder="Pega aquí instrucciones específicas de formato o citación de la revista (ej. APA, Vancouver)...",
        height=150
    )
    st.session_state['journal_guidelines'] = journal_guidelines
    
    if uploaded_files:
        for f in uploaded_files:
            if f.name not in st.session_state.processed_files:
                # Store the file data in session state as a message
                st.session_state.messages.append({
                    "role": "user",
                    "content": f"[Archivo subido: {f.name}]",
                    "file_data": f.getvalue(),
                    "mime_type": f.type
                })
                st.session_state.processed_files.append(f.name)
                # Acknowledge the upload
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"He recibido el archivo '{f.name}'. I have analyzed it and am ready to discuss it with you. What specific areas would you like me to look at first?"
                })
                st.rerun()

# Display chat messages from history on app rerun
st.subheader("Discusión de Revisión")
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# React to user input in chat
if prompt := st.chat_input("Discute el documento o pide clarificaciones..."):
    # Display user message in chat message container
    st.chat_message("user").markdown(prompt)
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})

    # Display assistant response in chat message container
    with st.chat_message("assistant"):
        if not api_key:
            response = "Por favor, introduce tu Google Gemini API Key en la barra lateral para usar el chat."
            st.markdown(response)
            st.session_state.messages.append({"role": "assistant", "content": response})
        elif not genai_available:
            response = "La librería google-genai no está disponible."
            st.markdown(response)
            st.session_state.messages.append({"role": "assistant", "content": response})
        else:
            with st.spinner("Analizando requerimiento..."):
                try:
                    client = genai.Client(api_key=api_key)
                    
                    contents_list = []
                    system_prompt_chat = (
                        "You are a highly rigorous, direct Scientific Peer Review sparring partner (like Professor Peter Svensson). "
                        "Your job is to discuss the uploaded manuscript with the user, answer their questions about the methodology, "
                        "identify fundamental flaws, and help them refine their critique BEFORE generating the final structured report. "
                        "1. Be implacable with design flaws (e.g., observational studies claiming 'effectiveness', lack of control groups, non-validated questionnaires). "
                        "2. If the user points out a flaw, validate it but encourage a firm, direct tone in the critique (e.g., 'The authors must explain why...'). "
                        "3. Always maintain a professional, strict, academic tone in English without sugar-coating fundamental issues. "
                    )
                    contents_list.append(system_prompt_chat)
                    
                    for msg in st.session_state.messages:
                        if msg["role"] == "user":
                            if "file_data" in msg:
                                part = types.Part.from_bytes(
                                    data=msg["file_data"],
                                    mime_type=msg["mime_type"]
                                )
                                contents_list.append(part)
                                contents_list.append(f"User uploaded a file: {msg['content']}")
                            else:
                                contents_list.append(f"User: {msg['content']}")
                        elif msg["role"] == "assistant":
                            contents_list.append(f"Assistant: {msg['content']}")
                            
                    contents_list.append("Answer as Assistant:")
                    
                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=contents_list
                    )
                    reply = response.text
                    st.markdown(reply)
                    st.session_state.messages.append({"role": "assistant", "content": reply})
                except Exception as e:
                    error_msg = f"Se produjo un error: {e}"
                    st.error(error_msg)
                    st.session_state.messages.append({"role": "assistant", "content": error_msg})

st.write("---")

# -------------------------
# FINAL REPORT GENERATION
# -------------------------
col_gen1, col_gen2 = st.columns([1, 4])

with col_gen1:
    analyze_btn = st.button("Generar Revisión Estructurada", type="primary", use_container_width=True)

with col_gen2:
    if analyze_btn:
        if not api_key:
            st.error("Por favor, introduce tu Google Gemini API Key en la barra lateral.")
        elif not genai_available:
            st.error("La librería google-genai no está disponible.")
        elif len(st.session_state.messages) <= 1:
            st.error("Por favor, sube un archivo PDF en el panel lateral primero para analizar.")
        else:
            with st.spinner("Redactando el informe de revisión formal final estructurado..."):
                try:
                    client = genai.Client(api_key=api_key)
                    
                    # Ensure we have the guidelines
                    j_guidelines = st.session_state.get('journal_guidelines', '')

                    # Enhanced System Prompt based on user instructions and example
                    system_prompt = f"""
Eres un revisor experto de manuscritos científicos (peer reviewer), como el Profesor Peter Svensson. Tu objetivo es proporcionar una evaluación profunda, crítica, rigurosa y estructurada de un manuscrito científico.
Has discutido previamente el artículo con el usuario en el historial de chat provisto. Sintetiza todo el conocimiento y las críticas acordadas en un ÚNICO reporte final coherente en Inglés.

CARACTERÍSTICAS DEL ASISTENTE:
- Rol: Revisor científico sumamente riguroso y metodológico. 
- Tono: Directo, académico, sin rodeos. Idioma: INGLÉS.
- Foco: Eres implacable con defectos de diseño (ej. estudios observacionales reclamando "efectividad", falta de grupos de control adecuados, cuestionarios no validados, poder estadístico, falta de criterios DC/TMD). Si las fallas metodológicas socavan la validez, recomendarás el rechazo ("rejection").

ESTRUCTURA DE REVISIÓN OBLIGATORIA:

Primero, escribe tu "Confidential Comments to the Editor" (o un resumen inicial dirigido al editor):
[Escribe un resumen evaluando el diseño del estudio, el impacto de las fallas metodológicas y si recomiendas rechazo (ej. "I therefore recommend rejection.") o revisión mayor].

Segundo, escribe tus "Comments to the authors":
[Párrafo introductorio resumiendo el estudio, su propósito y declarando firmemente las fallas metodológicas sustanciales que encuentras].

Luego, presenta tus críticas en una lista numerada secuencial (Comment 1, Comment 2, etc.). CADA COMENTARIO DEBE SER UN PÁRRAFO DIRECTO Y EXPLICATIVO QUE COMBINE EL PROBLEMA Y LA ACCIÓN REQUERIDA (ej. "Please explain why...", "The authors should...", "Align the wording..."). 
No uses viñetas. Usa este formato:

Comment 1:
[Descripción detallada de la debilidad metodológica, terminología incorrecta o asunción causal errónea, seguida inmediatamente por tu directiva firme de lo que los autores deben hacer para corregirlo, justificarlo o reformatearlo].

Comment 2:
[Siguiente crítica y directiva...].

Asegúrate de enfocarte en:
- Reclamaciones causales ("effectiveness") en estudios transversales.
- Omisión de estándares diagnósticos internacionales (ej. DC/TMD, ICOP) a favor de solo cuestionarios (ej. Fonseca).
- Falta de reportes sobre el tipo de férula (splint), justificación, y protocolo de desgaste.
- Justificaciones de poder estadístico y sesgos de grupos pequeños/no balanceados.

Guías específicas de la revista a considerar (si las hay):
{j_guidelines if j_guidelines else "Ninguna especificada."}
"""
                    
                    contents_list = []
                    contents_list.append(system_prompt)
                    
                    # Accumulate context
                    for msg in st.session_state.messages[1:]: # Skip the greeting
                        if msg["role"] == "user":
                            if "file_data" in msg:
                                part = types.Part.from_bytes(
                                    data=msg["file_data"],
                                    mime_type=msg["mime_type"]
                                )
                                contents_list.append(part)
                            else:
                                contents_list.append(f"User Note/Discussion: {msg['content']}")
                        elif msg["role"] == "assistant":
                            # We only care about the PDF and user notes usually, but assistant responses provide context of agreed critique.
                            contents_list.append(f"Assistant Note: {msg['content']}")
                            
                    contents_list.append("Based on the manuscript and the discussion above, generate the final structured Peer Review Report following the EXACT required format:")
                    
                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=contents_list
                    )
                    
                    st.session_state['review_report'] = response.text
                    
                except Exception as e:
                    st.error(f"Se produjo un error durante la redacción del reporte: {str(e)}")

# Always display the report if it exists
if 'review_report' in st.session_state:
    st.subheader("Informe de Revisión Final")
    
    def update_report():
        st.session_state.review_report = st.session_state.report_editor

    st.text_area(
        "Edita el reporte final (Opcional):", 
        value=st.session_state['review_report'], 
        height=600,
        key="report_editor",
        on_change=update_report
    )
    
    st.download_button(
        label="Descargar Informe (TXT)",
        data=st.session_state['review_report'],
        file_name="informe_revision_pares.txt",
        mime="text/plain",
        type="primary"
    )
