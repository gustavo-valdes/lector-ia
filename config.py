#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config.py — Rutas de la aplicación y configuración persistente.
"""

import sys
import json
from pathlib import Path


# ═══════════════════════════════════════════════════════════════════════════════
# RUTAS DE LA APLICACIÓN
# ═══════════════════════════════════════════════════════════════════════════════

def get_app_dir() -> Path:
    """Devuelve el directorio base de la app (funciona en .exe y en dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


APP_DIR      = get_app_dir()
SESSIONS_DIR = APP_DIR / "sessions"
AUDIO_DIR    = APP_DIR / "audio_cache"
CONFIG_FILE  = APP_DIR / "config.json"

SESSIONS_DIR.mkdir(exist_ok=True)
AUDIO_DIR.mkdir(exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════════════════

class Config:
    _DEFAULT_PROMPT = (
        "INSTRUCCIONES DE FORMATO PARA AUDIO:\n"
        "Escribe los números de forma que suenen natural al escucharlos "
        "(por ejemplo, 'dos mil veinticuatro' en vez de '2024' si está en un contexto narrativo; "
        "mantén cifras exactas en fórmulas o datos numéricos).\n"
        "Expande las siglas la primera vez que aparezcan "
        "(por ejemplo, 'Organización Mundial de la Salud, OMS').\n"
        "Las fórmulas matemáticas o químicas descríbelas en palabras "
        "(por ejemplo, 'H subíndice 2 O' para H₂O)."
    )

    _DEFAULT_TRANSCRIPTION_PROMPT = (
        "TAREA: Transcripción fiel de documento para lector de voz.\n\n"
        "REGLAS ESTRICTAS — síguelas sin excepción:\n"
        "1. TEXTO: Copia el texto del documento palabra por palabra, exactamente como aparece. "
        "No resumas, no parafrasees, no reordenes, no agregues explicaciones ni comentarios.\n"
        "2. IMÁGENES Y DIAGRAMAS: Para cada imagen, gráfico o figura que no tenga texto, "
        "inserta una descripción entre corchetes: [Imagen: ...] o [Figura: ...], "
        "describiendo su contenido con precisión para alguien que no puede verla. "
        "Si la imagen contiene texto, transcribe ese texto directamente.\n"
        "3. FORMATO: No uses Markdown (sin asteriscos, sin guiones de lista, sin #). "
        "Usa texto plano con saltos de línea naturales tal como aparecen en el documento.\n"
        "4. OMISIONES: Ignora sellos, marcas de agua, arrugas, bordes decorativos y "
        "cualquier elemento que no sea contenido informativo.\n"
        "5. PROHIBIDO: No agregues frases introductorias como 'A continuación...', "
        "'El documento dice...', ni conclusiones ni resúmenes al final.\n\n"
        "Comienza la transcripción ahora, directamente con el contenido del documento:"
    )

    def __init__(self):
        self._data: dict = {}
        self._load()

    def _load(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception:
                self._data = {}

    def save(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value):
        self._data[key] = value
        self.save()

    @property
    def api_key(self) -> str:
        return self._data.get("api_key", "")

    @property
    def model(self) -> str:
        return self._data.get("model", "gemini-2.5-flash")

    @property
    def default_prompt(self) -> str:
        return self._data.get("default_system_prompt", self._DEFAULT_PROMPT)

    @property
    def transcription_prompt(self) -> str:
        return self._data.get("transcription_prompt", self._DEFAULT_TRANSCRIPTION_PROMPT)
