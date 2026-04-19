#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gemini_client.py — Cliente para la API de Google Gemini.
"""

import io as _io
from pathlib import Path
from datetime import datetime

from config import Config

# ── Dependencias opcionales ──────────────────────────────────────────────────

try:
    from google import genai as _genai
    from google.genai import types as _genai_types
    GENAI_OK = True
except ImportError:
    GENAI_OK = False

try:
    import fitz  # PyMuPDF
    PYMUPDF_OK = True
except ImportError:
    PYMUPDF_OK = False

try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    PIL_OK = False


# ═══════════════════════════════════════════════════════════════════════════════
# CLIENTE GEMINI
# ═══════════════════════════════════════════════════════════════════════════════

class GeminiClient:
    def __init__(self, config: Config):
        self.config = config
        self._client = None
        self._configure()

    def _configure(self):
        self._configure_error = None
        if not GENAI_OK:
            self._configure_error = "La librería google-genai no está instalada."
            return
        if not self.config.api_key:
            return
        try:
            self._client = _genai.Client(api_key=self.config.api_key)
        except Exception as e:
            self._client = None
            self._configure_error = str(e)

    def reconfigure(self):
        self._configure()

    def _is_ready(self) -> bool:
        return self._client is not None

    def process_file(self, file_path: str, system_prompt: str) -> str:
        if not self._is_ready():
            detail = getattr(self, "_configure_error", None)
            if detail:
                return f"⚠ Error al inicializar Gemini: {detail}"
            return "⚠ Error: Configura la clave API de Gemini primero (Configuración > Clave API)."
        try:
            contents = self._build_contents(file_path)
            extra = f"INSTRUCCIONES ADICIONALES DEL DOCENTE:\n{system_prompt}" if system_prompt else ""
            system_instruction = self.config.transcription_prompt
            if extra:
                system_instruction += "\n\n" + extra
            cfg = _genai_types.GenerateContentConfig(
                system_instruction=system_instruction,
            )
            resp = self._client.models.generate_content(
                model=self.config.model,
                contents=contents,
                config=cfg,
            )
            return resp.text
        except Exception as e:
            return f"⚠ Error al procesar el archivo: {e}"

    def _build_contents(self, file_path: str) -> list:
        """Construye la lista de partes con el contenido del documento."""
        parts = []
        ext = Path(file_path).suffix.lower()

        if ext == ".pdf":
            parts.extend(self._pdf_parts(file_path))
        elif ext in (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"):
            if PIL_OK:
                img = Image.open(file_path)
                parts.append(img)
            else:
                parts.append(f"[Imagen: {Path(file_path).name}]")

        return parts

    def _pdf_parts(self, pdf_path: str) -> list:
        if not PYMUPDF_OK:
            return [f"[Error: PyMuPDF no disponible — no se puede leer {pdf_path}]"]
        parts = []
        doc = fitz.open(pdf_path)
        for page_num, page in enumerate(doc):
            text = page.get_text()
            if text.strip():
                parts.append(f"[Página {page_num + 1}]\n{text}\n")
            for img_info in page.get_images(full=True):
                try:
                    xref = img_info[0]
                    base = doc.extract_image(xref)
                    if PIL_OK:
                        pil_img = Image.open(_io.BytesIO(base["image"]))
                        parts.append(f"\n[Imagen en página {page_num + 1}]:\n")
                        parts.append(pil_img)
                except Exception:
                    pass
        doc.close()
        return parts

    def chat(self, history: list, new_message: str) -> str:
        if not self._is_ready():
            return "⚠ Error: Configura la clave API de Gemini primero."
        try:
            gemini_history = []
            for m in history:
                role = "user" if m["role"] == "user" else "model"
                gemini_history.append(
                    _genai_types.Content(
                        role=role,
                        parts=[_genai_types.Part.from_text(text=m["content"])]
                    )
                )
            chat_obj = self._client.chats.create(
                model=self.config.model,
                history=gemini_history,
            )
            resp = chat_obj.send_message(new_message)
            return resp.text
        except Exception as e:
            return f"⚠ Error en el chat: {e}"

    def qa_with_context(self, doc_text: str, qa_history: list, question: str, system_prompt: str = "") -> str:
        """Responde una pregunta usando el texto del documento como contexto."""
        if not self._is_ready():
            return "⚠ Error: Configura la clave API de Gemini primero."
        try:
            gemini_history = [
                _genai_types.Content(
                    role="user",
                    parts=[_genai_types.Part.from_text(
                        text=(
                            "El siguiente es el contenido de un documento que estoy estudiando:\n\n"
                            + doc_text[:12000] +
                            "\n\nResponde mis preguntas sobre este documento. "
                            "Tus respuestas serán leídas en voz alta, así que escribe sin "
                            "asteriscos, guiones ni símbolos Markdown. Usa lenguaje natural y oral."
                        )
                    )]
                ),
                _genai_types.Content(
                    role="model",
                    parts=[_genai_types.Part.from_text(
                        text="Entendido. He leído el documento y estoy listo para responder tus preguntas."
                    )]
                ),
            ]
            for m in qa_history:
                role = "user" if m["role"] == "user" else "model"
                gemini_history.append(
                    _genai_types.Content(
                        role=role,
                        parts=[_genai_types.Part.from_text(text=m["content"])]
                    )
                )
            
            cfg = _genai_types.GenerateContentConfig()
            if system_prompt:
                cfg.system_instruction = system_prompt

            chat_obj = self._client.chats.create(
                model=self.config.model,
                history=gemini_history,
                config=cfg
            )
            resp = chat_obj.send_message(question)
            return resp.text
        except Exception as e:
            return f"⚠ Error al responder la pregunta: {e}"

    def generate_name(self, content: str) -> str:
        if not self._is_ready():
            return f"Sesión {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        try:
            prompt = (
                "En máximo 5 palabras, escribe un título descriptivo en español "
                "para el siguiente contenido. Solo el título, sin puntuación extra "
                "ni comillas:\n\n" + content[:600]
            )
            resp = self._client.models.generate_content(
                model=self.config.model,
                contents=prompt,
            )
            return resp.text.strip()[:60]
        except Exception:
            return f"Sesión {datetime.now().strftime('%d/%m/%Y %H:%M')}"
