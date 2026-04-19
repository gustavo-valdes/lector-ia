#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LectorIA - Asistente de Lectura Accesible para Estudiantes con Discapacidad Visual
Versión 2.0

Punto de entrada de la aplicación.
Módulos:
  config.py        — rutas y configuración persistente
  session.py       — modelos de sesión y persistencia
  gemini_client.py — cliente de la API de Google Gemini
  tts_engine.py    — motor TTS, beeps y utilidades de texto
app.py           — clase principal LectorIA (ventana, pestañas, lógica)
"""

import os
import sys

from app import LectorIA


from PySide6.QtWidgets import QApplication

if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        os.chdir(os.path.dirname(sys.executable))
    
    # PySide6 application loop setup
    qapp = QApplication(sys.argv)
    window = LectorIA()
    window.show()
    sys.exit(qapp.exec())
