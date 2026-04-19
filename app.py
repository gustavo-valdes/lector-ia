#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — Clase principal LectorIA (ventana, pestañas, lógica de UI).
Reescrito en PySide6.
"""

import io
import wave
import threading
import uuid
from pathlib import Path
from datetime import datetime
import sys

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QListWidget, QPushButton, QLineEdit, QTextEdit,
    QLabel, QMenuBar, QMenu, QFileDialog, QMessageBox, QProgressBar,
    QDialog, QTabWidget, QRadioButton, QButtonGroup, QScrollArea, QAbstractItemView
)
from PySide6.QtCore import Qt, QTimer, Slot, Signal
from PySide6.QtGui import QTextCursor, QTextCharFormat, QColor, QFont, QKeySequence, QShortcut, QAction

from config import Config
from session import Session, SessionManager
from gemini_client import GeminiClient
from tts_engine import TTSEngine, _play_ready_beep, _play_tab_beep

# ── Dependencias opcionales para grabación de voz ────────────────────────────

try:
    import sounddevice as sd
    import numpy as np
    SD_OK = True
except ImportError:
    SD_OK = False
    np    = None

try:
    import speech_recognition as sr
    SR_OK = True
except ImportError:
    SR_OK = False


# ═══════════════════════════════════════════════════════════════════════════════
# APLICACIÓN PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

class LectorIA(QMainWindow):

    # Definir una señal global para ejecutar callbacks en el hilo principal
    _main_thread_action = Signal(object)

    def __init__(self):
        super().__init__()
        self._main_thread_action.connect(self._execute_main_thread_action)
        
        self.cfg      = Config()
        self.sessions = SessionManager()
        self.gemini   = GeminiClient(self.cfg)

        # TTS pestaña 1 (transcripción)
        self.tts = TTSEngine(self.sessions)
        self.tts.on_word = lambda i: self.run_in_main(lambda: self._highlight_word(i))
        self.tts.on_end  = lambda: self.run_in_main(self._on_playback_end)

        # TTS pestaña 2 (respuestas IA)
        self.tts_qa = TTSEngine(self.sessions)
        self.tts_qa.on_word = lambda i: self.run_in_main(lambda: self._highlight_word_qa(i))
        self.tts_qa.on_end  = lambda: self.run_in_main(self._on_qa_playback_end)

        self.current_session = None
        self.current_file = ""
        self.reader_text = ""
        self._system_prompt = self.cfg.default_prompt
        self._word_positions = []
        self._qa_response_idx = 0
        self._sessions_index = []
        self._slow_mode = False

        # Estado grabación
        self._recording = False
        self._rec_frames = []
        self._rec_stream = None
        self._qa_messages = []
        self._qa_reader_text = ""
        self._processing = False
        self._process_cancel = threading.Event()

        self._build_window()
        self._build_menu()
        self._build_layout()
        self._bind_keys()
        self._refresh_sessions()

        for btn in self.findChildren(QPushButton):
            if btn.font().pointSize() < 18:
                f = btn.font()
                f.setPointSize(18)
                btn.setFont(f)

    @Slot(object)
    def _execute_main_thread_action(self, func):
        func()
        
    def run_in_main(self, func):
        self._main_thread_action.emit(func)

    # ── Ventana ──────────────────────────────────────────────────────────────

    def _build_window(self):
        self.setWindowTitle("LectorIA – Asistente de Lectura Accesible")
        self.resize(1400, 900)
        self.setMinimumSize(960, 640)
        self.showMaximized()

    # ── Menú ─────────────────────────────────────────────────────────────────

    def _build_menu(self):
        bar = self.menuBar()

        m_file = bar.addMenu("&Archivo")
        
        act_new = QAction("Nueva sesión", self)
        act_new.setShortcut("Ctrl+Space")
        act_new.triggered.connect(lambda: self._new_session())
        m_file.addAction(act_new)

        act_open = QAction("Abrir archivo...", self)
        act_open.setShortcut("Ctrl+O")
        act_open.triggered.connect(self._pick_file)
        m_file.addAction(act_open)

        m_file.addSeparator()

        act_ren = QAction("Renombrar sesión...", self)
        act_ren.setShortcut("F2")
        act_ren.triggered.connect(self._rename_session)
        m_file.addAction(act_ren)

        act_del = QAction("Eliminar sesión actual", self)
        act_del.triggered.connect(self._delete_session)
        m_file.addAction(act_del)

        m_file.addSeparator()

        act_quit = QAction("Salir", self)
        act_quit.setShortcut("Alt+F4")
        act_quit.triggered.connect(self.close)
        m_file.addAction(act_quit)

        m_cfg = bar.addMenu("&Configuración")
        
        act_inst = QAction("Instrucciones del asistente...", self)
        act_inst.triggered.connect(self._dlg_system_prompt)
        m_cfg.addAction(act_inst)

        m_cfg.addSeparator()

        act_api = QAction("Clave API de Gemini...", self)
        act_api.triggered.connect(self._dlg_api_key)
        m_cfg.addAction(act_api)

        act_mod = QAction("Modelo de Gemini...", self)
        act_mod.triggered.connect(self._dlg_model)
        m_cfg.addAction(act_mod)

        m_help = bar.addMenu("A&yuda")
        
        act_short = QAction("Atajos y consejos...", self)
        act_short.triggered.connect(self._dlg_shortcuts)
        m_help.addAction(act_short)

        act_abt = QAction("Acerca de...", self)
        act_abt.triggered.connect(self._dlg_about)
        m_help.addAction(act_abt)

    # ── Layout ───────────────────────────────────────────────────────────────

    def _build_layout(self):
        self.splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(self.splitter)

        self._build_sidebar()
        
        self.tabs = QTabWidget()
        font = self.tabs.font()
        font.setPointSize(14)
        self.tabs.setFont(font)
        
        self._build_reader_tab()
        self._build_qa_tab()

        self.tabs.addTab(self.tab1_widget, "📖 Transcripción (Ctrl+←)")
        self.tabs.addTab(self.tab2_widget, "💬 Preguntas (Ctrl+→)")
        
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.splitter.addWidget(self.sidebar_widget)
        self.splitter.addWidget(self.tabs)
        
        self.splitter.setSizes([320, 1080])

    # ── Sidebar ──────────────────────────────────────────────────────────────

    def _build_sidebar(self):
        self.sidebar_widget = QWidget()
        lay = QVBoxLayout(self.sidebar_widget)
        lay.setContentsMargins(14, 12, 14, 12)

        lbl_title = QLabel("🎧 LectorIA")
        font = lbl_title.font()
        font.setPointSize(24)
        font.setBold(True)
        lbl_title.setFont(font)
        lay.addWidget(lbl_title)

        lbl_sub = QLabel("Lectura accesible para todos")
        font_sub = lbl_sub.font()
        font_sub.setPointSize(14)
        lbl_sub.setFont(font_sub)
        lay.addWidget(lbl_sub)

        btn_new = QPushButton("＋  Nueva Sesión (Ctrl+Space)")
        btn_new.setMinimumHeight(40)
        btn_new.clicked.connect(lambda: self._new_session())
        lay.addWidget(btn_new)

        lay.addSpacing(10)
        lbl_sess = QLabel("SESIONES")
        font_sec = lbl_title.font()
        font_sec.setPointSize(12)
        font_sec.setBold(True)
        lbl_sess.setFont(font_sec)
        lay.addWidget(lbl_sess)

        self.lb_sessions = QListWidget()
        self.lb_sessions.setSelectionMode(QAbstractItemView.SingleSelection)
        font_list = self.lb_sessions.font()
        font_list.setPointSize(14)
        self.lb_sessions.setFont(font_list)
        self.lb_sessions.itemSelectionChanged.connect(self._on_session_pick)
        self.lb_sessions.itemDoubleClicked.connect(lambda item: self._rename_session())
        lay.addWidget(self.lb_sessions)

        btn_ren = QPushButton("✏  Renombrar sesión  (F2)")
        btn_ren.clicked.connect(self._rename_session)
        lay.addWidget(btn_ren)

        lay.addSpacing(10)
        lbl_arch = QLabel("ARCHIVO")
        lbl_arch.setFont(font_sec)
        lay.addWidget(lbl_arch)

        self.lbl_file = QLabel("Sin archivo seleccionado")
        self.lbl_file.setWordWrap(True)
        lay.addWidget(self.lbl_file)

        btn_pick = QPushButton("📁  Abrir/Reemplazar (Ctrl+O)")
        btn_pick.setMinimumHeight(35)
        btn_pick.clicked.connect(self._pick_file)
        lay.addWidget(btn_pick)

        lay.addSpacing(10)

        self.btn_process = QPushButton("⚡  Procesar con IA")
        self.btn_process.setMinimumHeight(45)
        self.btn_process.setEnabled(False)
        self.btn_process.clicked.connect(self._btn_process_clicked)
        lay.addWidget(self.btn_process)

        self.lbl_session_name = QLabel("")
        self.lbl_session_name.setWordWrap(True)
        font_it = self.lbl_session_name.font()
        font_it.setItalic(True)
        self.lbl_session_name.setFont(font_it)
        lay.addWidget(self.lbl_session_name)

    def _on_tab_changed(self, index):
        if index == 0:
            self._speak_text("Transcripción del texto")
        else:
            self._speak_text("Haz tu pregunta")

    # ── Pestaña 1: Lector ────────────────────────────────────────────────────

    def _build_reader_tab(self):
        self.tab1_widget = QWidget()
        lay = QVBoxLayout(self.tab1_widget)

        hdr_lay = QHBoxLayout()
        lbl_title = QLabel("📖  Lectura en Voz Alta")
        font = lbl_title.font()
        font.setPointSize(20)
        font.setBold(True)
        lbl_title.setFont(font)
        hdr_lay.addWidget(lbl_title)
        
        hdr_lay.addStretch()
        lay.addLayout(hdr_lay)

        self.txt_reader = QTextEdit()
        font_txt = self.txt_reader.font()
        font_txt.setPointSize(18)
        self.txt_reader.setFont(font_txt)
        self.txt_reader.setReadOnly(True)
        self.txt_reader.mouseReleaseEvent = self._on_reader_click
        lay.addWidget(self.txt_reader)

        ctrl_lay = QHBoxLayout()

        self.btn_play = QPushButton("▶")
        font_play = self.btn_play.font()
        font_play.setPointSize(20)
        self.btn_play.setFont(font_play)
        self.btn_play.clicked.connect(self._toggle_play)
        ctrl_lay.addWidget(self.btn_play)

        self.lbl_audio_status = QLabel("")
        ctrl_lay.addWidget(self.lbl_audio_status)

        self.lbl_progress_sents = QLabel("")
        ctrl_lay.addWidget(self.lbl_progress_sents)
        
        ctrl_lay.addStretch()

        self.btn_cancel_audio = QPushButton("✖  Cancelar audio")
        self.btn_cancel_audio.setVisible(False)
        self.btn_cancel_audio.clicked.connect(self._cancel_audio_prep)
        ctrl_lay.addWidget(self.btn_cancel_audio)

        lay.addLayout(ctrl_lay)

        prog_lay = QHBoxLayout()
        self.lbl_progress = QLabel("")
        prog_lay.addWidget(self.lbl_progress)
        prog_lay.addStretch()
        self.lbl_bookmark = QLabel("")
        prog_lay.addWidget(self.lbl_bookmark)
        
        lay.addLayout(prog_lay)




    # ── Pestaña 2: Preguntas ─────────────────────────────────────────────────

    def _build_qa_tab(self):
        self.tab2_widget = QWidget()
        lay = QVBoxLayout(self.tab2_widget)

        hdr_lay = QHBoxLayout()
        lbl_title = QLabel("💬  Preguntas sobre el Texto")
        font = lbl_title.font()
        font.setPointSize(20)
        font.setBold(True)
        lbl_title.setFont(font)
        hdr_lay.addWidget(lbl_title)
        hdr_lay.addStretch()

        rec_status = "Enter: grabar/detener  ·  Espacio: leer respuesta"
        if not (SD_OK and SR_OK):
            rec_status = "⚠ Instala sounddevice y SpeechRecognition para voz"
        
        lbl_info = QLabel(rec_status)
        hdr_lay.addWidget(lbl_info)
        lay.addLayout(hdr_lay)

        self.txt_qa = QTextEdit()
        font_qa = self.txt_qa.font()
        font_qa.setPointSize(16)
        self.txt_qa.setFont(font_qa)
        self.txt_qa.setReadOnly(True)
        lay.addWidget(self.txt_qa)

        rdr_hdr_lay = QHBoxLayout()
        lbl_resp = QLabel("Respuesta:")
        font_b = lbl_resp.font()
        font_b.setBold(True)
        lbl_resp.setFont(font_b)
        rdr_hdr_lay.addWidget(lbl_resp)

        self.btn_qa_prev = QPushButton("◀")
        self.btn_qa_prev.setEnabled(False)
        self.btn_qa_prev.clicked.connect(lambda: self._qa_nav(-1))
        rdr_hdr_lay.addWidget(self.btn_qa_prev)

        self.lbl_qa_resp_counter = QLabel("")
        rdr_hdr_lay.addWidget(self.lbl_qa_resp_counter)

        self.btn_qa_next = QPushButton("▶")
        self.btn_qa_next.setEnabled(False)
        self.btn_qa_next.clicked.connect(lambda: self._qa_nav(+1))
        rdr_hdr_lay.addWidget(self.btn_qa_next)
        rdr_hdr_lay.addStretch()

        self.lbl_qa_progress = QLabel("")
        rdr_hdr_lay.addWidget(self.lbl_qa_progress)
        lay.addLayout(rdr_hdr_lay)

        self.txt_reader_qa = QTextEdit()
        font_rqa = self.txt_reader_qa.font()
        font_rqa.setPointSize(16)
        self.txt_reader_qa.setFont(font_rqa)
        self.txt_reader_qa.setReadOnly(True)
        self.txt_reader_qa.setMaximumHeight(200)
        lay.addWidget(self.txt_reader_qa)

        hint = ("Presiona Enter para grabar tu pregunta" if SD_OK and SR_OK
                else "⚠  pip install sounddevice SpeechRecognition")
        self.lbl_rec_status = QLabel(hint)
        self.lbl_rec_status.setWordWrap(True)
        lay.addWidget(self.lbl_rec_status)

        qa_ctrl_lay = QHBoxLayout()

        self.btn_qa_play = QPushButton("▶")
        font_play2 = self.btn_qa_play.font()
        font_play2.setPointSize(20)
        self.btn_qa_play.setFont(font_play2)
        self.btn_qa_play.setEnabled(False)
        self.btn_qa_play.clicked.connect(self._toggle_qa_play)
        qa_ctrl_lay.addWidget(self.btn_qa_play)

        self.lbl_qa_audio_status = QLabel("")
        qa_ctrl_lay.addWidget(self.lbl_qa_audio_status)

        self.lbl_qa_progress_sents = QLabel("")
        qa_ctrl_lay.addWidget(self.lbl_qa_progress_sents)

        qa_ctrl_lay.addStretch()
        lay.addLayout(qa_ctrl_lay)
        


    # ── Atajos ───────────────────────────────────────────────────────────────

    def _bind_keys(self):
        # En PySide6, definiremos QShortcuts globales
        QShortcut(QKeySequence(Qt.Key_Space), self).activated.connect(self._space_key)
        QShortcut(QKeySequence(Qt.Key_Left), self).activated.connect(self._left_key)
        QShortcut(QKeySequence(Qt.Key_Right), self).activated.connect(self._right_key)
        QShortcut(QKeySequence("Ctrl+Right"), self).activated.connect(lambda: self.tabs.setCurrentIndex(1))
        QShortcut(QKeySequence("Ctrl+Left"), self).activated.connect(lambda: self.tabs.setCurrentIndex(0))
        QShortcut(QKeySequence(Qt.Key_Return), self).activated.connect(self._enter_key)
        QShortcut(QKeySequence(Qt.Key_Up), self).activated.connect(self._up_key)
        QShortcut(QKeySequence(Qt.Key_Down), self).activated.connect(self._down_key)
        QShortcut(QKeySequence("Ctrl+Up"), self).activated.connect(lambda: self._nav_sessions(-1))
        QShortcut(QKeySequence("Ctrl+Down"), self).activated.connect(lambda: self._nav_sessions(+1))

        # Marcadores 1–10: Ctrl+1..9 guarda, Ctrl+0 guarda en slot 10
        #                   Alt+1..9 va al slot,  Alt+0 va al slot 10
        for i in range(1, 11):
            key = str(i % 10)  # "1".."9", "0" para slot 10
            slot = i
            QShortcut(QKeySequence(f"Ctrl+{key}"), self).activated.connect(
                lambda s=slot: self._save_bookmark(s))
            QShortcut(QKeySequence(f"Alt+{key}"), self).activated.connect(
                lambda s=slot: self._goto_bookmark(s))
        
        # Atajo local para borrar sesiones
        QShortcut(QKeySequence(Qt.Key_Backspace), self.lb_sessions).activated.connect(self._prompt_delete_session)

    def _enter_key(self):
        focused = self.focusWidget()
        if isinstance(focused, QLineEdit):
            return
        if self.tabs.currentIndex() == 1:
            self._toggle_recording()

    def _space_key(self):
        focused = self.focusWidget()
        if isinstance(focused, QLineEdit):
            return
        if self.tabs.currentIndex() == 0:
            self._toggle_play()
        else:
            self._toggle_qa_play()

    def _left_key(self):
        focused = self.focusWidget()
        if isinstance(focused, QLineEdit):
            return
        if self.tabs.currentIndex() == 0:
            self.tts.prev_sentence()
        else:
            self.tts_qa.prev_sentence()

    def _right_key(self):
        focused = self.focusWidget()
        if isinstance(focused, QLineEdit):
            return
        if self.tabs.currentIndex() == 0:
            self.tts.next_sentence()
        else:
            self.tts_qa.next_sentence()

    def _up_key(self):
        focused = self.focusWidget()
        if isinstance(focused, QLineEdit):
            return
        if self.tabs.currentIndex() == 1:
            self._qa_nav_and_play(-1)

    def _down_key(self):
        focused = self.focusWidget()
        if isinstance(focused, QLineEdit):
            return
        if self.tabs.currentIndex() == 1:
            self._qa_nav_and_play(+1)

    # ═══════════════════════════════════════════════════════════════════════
    # LÓGICA DE SESIONES
    # ═══════════════════════════════════════════════════════════════════════

    def _refresh_sessions(self):
        self.lb_sessions.clear()
        self._sessions_index = self.sessions.list_all()
        for s in self._sessions_index:
            self.lb_sessions.addItem(s["name"])

    def _nav_sessions(self, delta: int):
        n = self.lb_sessions.count()
        if n == 0: return
        row = self.lb_sessions.currentRow()
        if row < 0: row = 0
        else: row += delta
        row = max(0, min(n - 1, row))
        self.lb_sessions.setCurrentRow(row)

    def _on_session_pick(self):
        rows = [item.row() for item in self.lb_sessions.selectedIndexes()]
        if not rows:
            return
        s_name = self._sessions_index[rows[0]]["name"]
        self._speak_text(s_name)
        self._load_session(self._sessions_index[rows[0]]["id"])

    def _load_session(self, sid: str):
        try:
            self.current_session = self.sessions.load(sid)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo cargar la sesión:\n{e}")
            return

        s = self.current_session
        self.lbl_session_name.setText(s.name)
        self._system_prompt = s.system_prompt or self.cfg.default_prompt

        if s.file_path:
            self.current_file = s.file_path
            self.lbl_file.setText(Path(s.file_path).name)
            self.btn_process.setEnabled(True)

        last_model = next(
            (m["content"] for m in reversed(s.messages) if m["role"] == "model"), "")
        if last_model:
            self._load_reader(last_model)
            self._update_bookmark_label()

        self._qa_messages = list(s.qa_messages)
        self.txt_qa.clear()
        for m in self._qa_messages:
            self._append_qa(m["role"], m["content"])

        pairs = self._get_qa_pairs()
        if pairs:
            self._qa_response_idx = len(pairs) - 1
            q, r = pairs[self._qa_response_idx]
            self._load_qa_reader(self._qa_pair_text(q, r))
        self._update_qa_nav()

    def _new_session(self, auto_pick=True):
        self.tts.cancel_prepare()
        self.tts.stop()
        self.tts_qa.stop()
        self._process_cancel.set()
        self._processing = False
        self.btn_cancel_audio.setVisible(False)
        self.btn_process.setText("⚡  Procesar con IA")
        self.current_session     = None
        self.current_file        = ""
        self.reader_text         = ""
        self._word_positions     = []
        self._qa_messages        = []
        self._qa_reader_text     = ""
        self._system_prompt      = self.cfg.default_prompt

        self.lbl_file.setText("Sin archivo seleccionado")
        self.lbl_session_name.setText("")
        self.btn_process.setEnabled(False)
        self.lbl_progress.setText("")
        self.lbl_bookmark.setText("")
        self.lbl_audio_status.setText("")
        self.btn_play.setText("▶")
        self.lbl_qa_audio_status.setText("")
        self.btn_qa_play.setText("▶")
        self.btn_qa_play.setEnabled(False)

        self.txt_reader.clear()
        self.txt_qa.clear()
        self.txt_reader_qa.clear()
        self.lbl_qa_progress.setText("")

        self.lb_sessions.clearSelection()

        self._qa_response_idx = 0
        self._update_qa_nav()

        hint = ("Presiona Enter para grabar tu pregunta" if SD_OK and SR_OK
                else "⚠  pip install sounddevice SpeechRecognition")
        self.lbl_rec_status.setText(hint)
        if auto_pick:
            self._pick_file()

    def _speak_text(self, text: str, on_done=None):
        def _run():
            try:
                from gtts import gTTS
                import pygame
                from io import BytesIO
                tts = gTTS(text=text, lang="es", slow=False)
                fp = BytesIO()
                tts.write_to_fp(fp)
                fp.seek(0)
                snd = pygame.mixer.Sound(fp)
                ch = snd.play()
                while ch.get_busy():
                    pygame.time.wait(100)
            except Exception:
                pass
            if on_done:
                self.run_in_main(on_done)
        threading.Thread(target=_run, daemon=True).start()

    def _prompt_delete_session(self):
        rows = [item.row() for item in self.lb_sessions.selectedIndexes()]
        if not rows:
            return
        
        idx = rows[0]
        sid = self._sessions_index[idx]["id"]
        s_name = self._sessions_index[idx]["name"]
        
        # Reproducir voz de la IA
        self._speak_text(f"¿desea borrar: {s_name}?")

        msg = QMessageBox(self)
        msg.setWindowTitle("Confirmar eliminación")
        msg.setText(f"¿Desea borrar la sesión «{s_name}»?")
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        msg.setDefaultButton(QMessageBox.Ok)
        
        if msg.exec() == QMessageBox.Ok:
            self.sessions.delete(sid)
            if self.current_session and self.current_session.id == sid:
                self.current_session = None
                self._new_session(auto_pick=False)
            self._refresh_sessions()

    def _delete_session(self):
        self._prompt_delete_session()

    # ═══════════════════════════════════════════════════════════════════════
    # ARCHIVOS Y PROCESAMIENTO IA
    # ═══════════════════════════════════════════════════════════════════════

    def _pick_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar archivo",
            "",
            "Archivos soportados (*.pdf *.jpg *.jpeg *.png *.bmp *.webp);;PDF (*.pdf);;Imágenes (*.jpg *.jpeg *.png *.bmp *.webp)"
        )
        if path:
            self.current_file = path
            self.lbl_file.setText(Path(path).name)
            self.btn_process.setEnabled(True)
            self._prompt_process_ia()

    def _prompt_process_ia(self):
        self._speak_text("¿Procesar documento con IA?")
        msg = QMessageBox(self)
        msg.setWindowTitle("Procesar documento")
        msg.setText("¿Desea procesar el documento con IA?")
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        msg.setDefaultButton(QMessageBox.Ok)
        if msg.exec() == QMessageBox.Ok:
            self._process_file()

    def _btn_process_clicked(self):
        if self._processing:
            self._cancel_process()
        else:
            self._process_file()

    def _cancel_process(self):
        self._process_cancel.set()
        self._processing = False
        self.btn_process.setText("⚡  Procesar con IA")
        self.btn_process.setEnabled(bool(self.current_file))
        self.lbl_audio_status.setText("Procesamiento cancelado")

    def _process_file(self):
        if not self.current_file:
            QMessageBox.warning(self, "Aviso", "Selecciona un archivo primero.")
            return
        if not self.cfg.api_key:
            QMessageBox.warning(self, "Clave API requerida",
                "Configura tu clave API de Gemini en:\nConfiguración > Clave API de Gemini")
            self._dlg_api_key()
            return

        self._processing = True
        self._process_cancel.clear()
        self.btn_process.setText("✖  Cancelar")
        self.lbl_audio_status.setText("⏳ Procesando con IA...")

        system_prompt = self._system_prompt
        threading.Thread(
            target=self._process_thread,
            args=(system_prompt,), daemon=True
        ).start()

    def _process_thread(self, system_prompt: str):
        response = self.gemini.process_file(self.current_file, system_prompt)
        if self._process_cancel.is_set():
            return
        name     = self.gemini.generate_name(response)
        if self._process_cancel.is_set():
            return
        sid      = uuid.uuid4().hex[:10]
        messages = [
            {"role": "user",  "content": f"[Archivo: {Path(self.current_file).name}]"},
            {"role": "model", "content": response},
        ]
        self.current_session = Session(
            session_id=sid, name=name,
            created_at=datetime.now().isoformat(),
            file_path=self.current_file,
            system_prompt=system_prompt,
            messages=messages,
        )
        self.sessions.save(self.current_session)
        self.run_in_main(lambda: self._on_process_done(response, name))

    def _on_process_done(self, response: str, name: str):
        self._processing = False
        self.btn_process.setEnabled(True)
        self.btn_process.setText("⚡  Procesar con IA")
        self.lbl_session_name.setText(name)

        self._qa_messages       = []
        self._qa_reader_text    = ""
        self._qa_response_idx   = 0
        self.txt_qa.clear()
        self.txt_reader_qa.clear()
        self._update_qa_nav()

        # Refrescar la lista de sesiones
        self._refresh_sessions()

        # Seleccionar la sesión sin disparar el evento _on_session_pick 
        # que volvería a procesar _load_session y _load_reader generando 
        # una condición de carrera en el Motor TTS.
        self.lb_sessions.blockSignals(True)
        for i, s in enumerate(self._sessions_index):
            if s["id"] == self.current_session.id:
                self.lb_sessions.setCurrentRow(i)
                break
        self.lb_sessions.blockSignals(False)
        
        # Primero enfocar en la pestaña
        self.tabs.setCurrentIndex(0)
        
        # Finalmente, cargar el texto en el lector (con anuncio)
        self._load_reader(response, is_new=True)

    # ═══════════════════════════════════════════════════════════════════════
    # GRABACIÓN DE VOZ Y PREGUNTAS
    # ═══════════════════════════════════════════════════════════════════════

    def _toggle_recording(self):
        if self._recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        if not (SD_OK and SR_OK):
            self.lbl_rec_status.setText("⚠  Instala las dependencias:  pip install sounddevice SpeechRecognition")
            return
        if not self.current_session:
            self.lbl_rec_status.setText("⚠  Procesa un documento primero antes de hacer preguntas.")
            return

        self._recording   = True
        self._rec_frames  = []
        self.lbl_rec_status.setText("🔴  Grabando...  Presiona Enter para detener")

        def _callback(indata, frames, time_info, status):
            if self._recording:
                self._rec_frames.append(indata.copy())

        try:
            self._rec_stream = sd.InputStream(
                samplerate=16000, channels=1,
                dtype="int16", callback=_callback
            )
            self._rec_stream.start()
        except Exception as e:
            self._recording = False
            self.lbl_rec_status.setText(f"⚠  Error al iniciar micrófono: {e}")

    def _stop_recording(self):
        if not self._recording:
            return
        self._recording = False
        try:
            self._rec_stream.stop()
            self._rec_stream.close()
        except Exception:
            pass

        if not self._rec_frames:
            self.lbl_rec_status.setText("No se grabó audio. Intenta de nuevo.")
            return

        self.lbl_rec_status.setText("⏳  Procesando pregunta...")
        threading.Thread(target=self._transcribe_and_ask, daemon=True).start()

    def _transcribe_and_ask(self):
        """Transcribe el audio grabado y consulta a Gemini."""
        try:
            audio_data = np.concatenate(self._rec_frames, axis=0)
            wav_buf    = io.BytesIO()
            with wave.open(wav_buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(audio_data.tobytes())
            wav_buf.seek(0)
        except Exception as e:
            self.run_in_main(lambda: self.lbl_rec_status.setText(f"⚠  Error al procesar audio: {e}"))
            return

        try:
            recognizer = sr.Recognizer()
            with sr.AudioFile(wav_buf) as source:
                audio = recognizer.record(source)
            question = recognizer.recognize_google(audio, language="es-ES")
        except sr.UnknownValueError:
            self.run_in_main(lambda: self.lbl_rec_status.setText("No se entendió el audio. Intenta de nuevo."))
            return
        except Exception as e:
            self.run_in_main(lambda: self.lbl_rec_status.setText(f"⚠  Error al transcribir: {e}"))
            return

        q = question
        self.run_in_main(lambda: self.lbl_rec_status.setText(f'🗣  "{q}"  —  Consultando IA...'))
        self._speak_text("Procesando tu pregunta")

        doc_text = self.reader_text or ""
        response = self.gemini.qa_with_context(doc_text, self._qa_messages, question, self._system_prompt)
        self.run_in_main(lambda: self._on_qa_done(question, response))

    def _on_qa_done(self, question: str, response: str):
        self._qa_messages.append({"role": "user",  "content": question})
        self._qa_messages.append({"role": "model", "content": response})

        if self.current_session:
            self.current_session.qa_messages = self._qa_messages
            self.sessions.save(self.current_session)

        self._append_qa("user",  question)
        self._append_qa("model", response)

        self.lbl_rec_status.setText("Presiona Enter para grabar otra pregunta  ·  Espacio para escuchar la respuesta")
        pairs = self._get_qa_pairs()
        self._qa_response_idx = len(pairs) - 1
        self._load_qa_reader(self._qa_pair_text(question, response), is_new=True)
        self._update_qa_nav()

    def _append_qa(self, role: str, text: str):
        if role == "user":
            self.txt_qa.append("<b>Tú:</b><br>" + text + "<br>")
        elif role == "model":
            self.txt_qa.append("<b>Asistente:</b><br>" + text + "<br>")
        else:
            self.txt_qa.append("<i>" + text + "</i><br>")
        
        sb = self.txt_qa.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ═══════════════════════════════════════════════════════════════════════
    # TTS PESTAÑA 2
    # ═══════════════════════════════════════════════════════════════════════

    def _get_qa_responses(self) -> list:
        return [m["content"] for m in self._qa_messages if m["role"] == "model"]

    def _get_qa_pairs(self) -> list[tuple[str, str]]:
        pairs = []
        for i, m in enumerate(self._qa_messages):
            if m["role"] == "model":
                question = ""
                if i > 0 and self._qa_messages[i - 1]["role"] == "user":
                    question = self._qa_messages[i - 1]["content"]
                pairs.append((question, m["content"]))
        return pairs

    def _qa_pair_text(self, question: str, response: str) -> str:
        if question:
            return f"Pregunta: {question}\n\nRespuesta: {response}"
        return response

    def _update_qa_nav(self):
        responses = self._get_qa_responses()
        n   = len(responses)
        idx = self._qa_response_idx
        self.btn_qa_prev.setEnabled(idx > 0)
        self.btn_qa_next.setEnabled(idx < n - 1)
        if n > 0:
            self.lbl_qa_resp_counter.setText(f"{idx + 1} / {n}")
        else:
            self.lbl_qa_resp_counter.setText("")

    def _qa_nav(self, delta: int):
        pairs = self._get_qa_pairs()
        new_idx = self._qa_response_idx + delta
        if new_idx < 0 or new_idx >= len(pairs):
            return
        self._qa_response_idx = new_idx
        q, r = pairs[new_idx]
        self._load_qa_reader(self._qa_pair_text(q, r))
        self._update_qa_nav()

    def _qa_nav_and_play(self, delta: int):
        pairs = self._get_qa_pairs()
        new_idx = self._qa_response_idx + delta
        if new_idx < 0 or new_idx >= len(pairs):
            return
        self._qa_response_idx = new_idx
        q, r = pairs[new_idx]
        self._load_qa_reader(self._qa_pair_text(q, r), auto_play=True)
        self._update_qa_nav()

    def _load_qa_reader(self, text: str, auto_play: bool = False, is_new: bool = False):
        self.tts_qa.stop()
        self._qa_reader_text = text

        self.txt_reader_qa.setPlainText(text)
        slow = False

        def _after_qa_prepare():
            words = self.tts_qa.words
            self.lbl_qa_progress.setText(f"Palabras: 0 / {len(words)}")
            self.lbl_qa_progress_sents.setText("")
            self.lbl_qa_audio_status.setText("✔ Listo — clic en una palabra o Espacio")
            self.btn_qa_play.setEnabled(True)

            if auto_play:
                self.tts_qa.play()
                self.btn_qa_play.setText("⏸")
            elif is_new:
                self._speak_text("Respuesta procesada")

        def _on_qa_progress(done: int, total: int):
            def _upd():
                self.lbl_qa_progress_sents.setText(f"{done}/{total} oraciones")
            self.run_in_main(_upd)

        def _on_qa_error(msg: str):
            self.lbl_qa_progress_sents.setText("")
            self.lbl_qa_audio_status.setText(f"⚠ {msg}")

        self.lbl_qa_audio_status.setText("⏳ Generando audio...")
        self.lbl_qa_progress_sents.setText("")
        self.btn_qa_play.setEnabled(False)
        self.tts_qa.prepare(text, slow,
                             on_ready=lambda: self.run_in_main(_after_qa_prepare),
                             on_error=lambda m: self.run_in_main(lambda: _on_qa_error(m)),
                             on_progress=lambda d, t: _on_qa_progress(d, t))

    def _toggle_qa_play(self):
        if not self._qa_reader_text:
            return
        if not self.tts_qa._audio_ready:
            return
        self.tts_qa.toggle()
        self.btn_qa_play.setText("⏸" if (self.tts_qa.is_playing and not self.tts_qa.is_paused) else "▶")

    def _highlight_word_qa(self, index: int):
        total = len(self.tts_qa.words)
        word = self.tts_qa.words[index] if index < total else ""
        self.lbl_qa_progress.setText(f"Palabras: «{word}» ({index + 1} / {total})")
        
        self._apply_highlight(self.txt_reader_qa, text_ref=self._qa_reader_text, words_ref=self.tts_qa.words, idx=index)

    def _on_qa_playback_end(self):
        self.btn_qa_play.setText("▶")
        self._clear_highlight(self.txt_reader_qa)



    # ═══════════════════════════════════════════════════════════════════════
    # LECTOR (PESTAÑA 1)
    # ═══════════════════════════════════════════════════════════════════════

    def _load_reader(self, text: str, is_new: bool = False):
        self.tts.stop()
        self.reader_text     = text
        self._word_positions = []

        self.txt_reader.setPlainText(text)
        QApplication.processEvents() # Forzar que se pinte en pantalla inmediatamente
        
        slow = False

        def _after_prepare():
            if self.reader_text != text:
                return
            self.btn_cancel_audio.setVisible(False)
            words = self.tts.words
            self._word_positions = []

            # Simple word position caching
            cur_pos = 0
            for w in words:
                idx = text.find(w, cur_pos)
                if idx != -1:
                    self._word_positions.append((idx, idx + len(w)))
                    cur_pos = idx + len(w)
                else:
                    self._word_positions.append(None)

            self.lbl_progress.setText(f"Palabras: 0 / {len(words)}")
            self.lbl_progress_sents.setText("")
            self.lbl_audio_status.setText("✔ Listo — clic en una palabra o Espacio")
            self.btn_play.setEnabled(True)

            if is_new:
                self._speak_text("Audio procesado")

        def _on_progress(done: int, total: int):
            def _upd():
                if self.reader_text != text: return
                self.lbl_progress_sents.setText(f"{done}/{total} oraciones")
            self.run_in_main(_upd)

        def _on_error(msg: str):
            if self.reader_text != text: return
            self.btn_cancel_audio.setVisible(False)
            self.lbl_progress_sents.setText("")
            self.lbl_audio_status.setText(f"⚠ {msg}")

        def _on_cancelled():
            def _upd():
                if self.reader_text != text: return
                self.btn_cancel_audio.setVisible(False)
                self.lbl_progress_sents.setText("")
                self.lbl_audio_status.setText("Generación de audio cancelada")
                self.btn_play.setEnabled(False)
            self.run_in_main(_upd)

        def _start_prep():
            if self.reader_text != text:
                return
            self.lbl_audio_status.setText("⏳ Generando audio…")
            self.lbl_progress_sents.setText("")
            self.btn_play.setEnabled(False)
            self.btn_cancel_audio.setVisible(True)
            self.tts.prepare(text, slow,
                             on_ready=lambda: self.run_in_main(_after_prepare),
                             on_error=lambda m: self.run_in_main(lambda: _on_error(m)),
                             on_progress=lambda d, t: _on_progress(d, t),
                             on_cancelled=_on_cancelled)

        if is_new:
            self._speak_text("Texto procesado", on_done=_start_prep)
        else:
            _start_prep()

    def _toggle_play(self):
        if not self.reader_text:
            QMessageBox.information(self, "Sin texto", "Procesa un archivo primero para activar la lectura.")
            return
        if not self.tts._audio_ready:
            return
        self.tts.toggle()
        self.btn_play.setText("⏸" if (self.tts.is_playing and not self.tts.is_paused) else "▶")

    def _clear_highlight(self, text_edit: QTextEdit):
        text_edit.setExtraSelections([])

    def _apply_highlight(self, text_edit: QTextEdit, text_ref: str, words_ref: list, idx: int):
        self._clear_highlight(text_edit)
        
        # Simple find pos logic
        if idx >= len(words_ref): return
        word = words_ref[idx]
        
        pos = 0
        for i in range(idx):
            fpos = text_ref.find(words_ref[i], pos)
            pos = fpos + len(words_ref[i]) if fpos != -1 else pos
            
        final_pos = text_ref.find(word, pos)
        if final_pos != -1:
            selection = QTextEdit.ExtraSelection()
            fmt = QTextCharFormat()
            fmt.setBackground(QColor("#ffeb3b"))
            fmt.setForeground(QColor("black"))
            fmt.setFontOverline(True)
            fmt.setFontUnderline(True)
            selection.format = fmt

            cursor = text_edit.textCursor()
            cursor.setPosition(final_pos)
            cursor.setPosition(final_pos + len(word), QTextCursor.KeepAnchor)
            selection.cursor = cursor
            
            text_edit.setExtraSelections([selection])
            
            # Limpiamos la selección del cursor principal para dejar solo el extra
            cursor.clearSelection()
            text_edit.setTextCursor(cursor)
            # Centramos la visualización verificando que QTextEdit no posee un centerCursor nativo
            text_edit.ensureCursorVisible()
            scrollbar = text_edit.verticalScrollBar()
            rect = text_edit.cursorRect()
            viewport_height = text_edit.viewport().height()
            scrollbar.setValue(int(scrollbar.value() + rect.center().y() - viewport_height / 2))

    def _highlight_word(self, index: int):
        self._apply_highlight(self.txt_reader, text_ref=self.reader_text, words_ref=self.tts.words, idx=index)
        total = len(self.tts.words)
        word = self.tts.words[index] if index < total else ""
        self.lbl_progress.setText(f"Palabras: «{word}»  ({index + 1} / {total})")

    def _on_playback_end(self):
        self.btn_play.setText("▶")
        self._clear_highlight(self.txt_reader)

    def _on_reader_click(self, event):
        super(QTextEdit, self.txt_reader).mouseReleaseEvent(event)
        
        if not self.tts._audio_ready or not self._word_positions:
            return
            
        cursor = self.txt_reader.cursorForPosition(event.pos())
        click_idx = cursor.position()
        
        target = None
        for i, pos in enumerate(self._word_positions):
            if pos is None:
                continue
            start, end = pos
            if start <= click_idx <= end:
                target = i
                break
            if start > click_idx:
                target = i
                break
        if target is None and self._word_positions:
            target = len(self._word_positions) - 1
        if target is not None:
            self.tts.goto_word(target)



    def _cancel_audio_prep(self):
        self.tts.cancel_prepare()

    # ═══════════════════════════════════════════════════════════════════════
    # MARCADORES
    # ═══════════════════════════════════════════════════════════════════════

    def _save_bookmark(self, slot: int = 1):
        if not self.current_session:
            self._speak_text("No hay sesión activa")
            return
        if not self.tts.words:
            self._speak_text("No hay texto cargado en el lector")
            return
        idx  = self.tts.current_index
        word = self.tts.words[idx] if idx < len(self.tts.words) else ""
        self.current_session.bookmarks[str(slot)] = idx
        self.sessions.save(self.current_session)
        self._update_bookmark_label()
        self._speak_text(f"Marcador {slot} guardado en: {word}")

    def _goto_bookmark(self, slot: int = 1):
        if not self.current_session:
            self._speak_text("No hay sesión activa")
            return
        idx = self.current_session.bookmarks.get(str(slot))
        if idx is None:
            self._speak_text(f"No hay marcador {slot} guardado")
            return
        if not self.tts._audio_ready:
            self._speak_text("El audio todavía se está preparando")
            return
        self.tts.goto_word(idx)
        self.btn_play.setText("▶")
        word = self.tts.words[idx] if self.tts.words and idx < len(self.tts.words) else ""
        self._speak_text(f"Marcador {slot}: {word}")

    def _update_bookmark_label(self):
        if self.current_session and self.current_session.bookmarks:
            slots = sorted(self.current_session.bookmarks.keys(), key=lambda x: int(x))
            self.lbl_bookmark.setText(f"🔖 Marcadores guardados: {', '.join(slots)}")
        else:
            self.lbl_bookmark.setText("")

    # ═══════════════════════════════════════════════════════════════════════
    # DIÁLOGOS DE CONFIGURACIÓN
    # ═══════════════════════════════════════════════════════════════════════

    def _dlg_system_prompt(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Instrucciones del Asistente")
        dlg.resize(900, 680)
        lay = QVBoxLayout(dlg)

        lbl = QLabel("Instrucciones del Asistente")
        font = lbl.font()
        font.setPointSize(20)
        font.setBold(True)
        lbl.setFont(font)
        lay.addWidget(lbl)

        tabs = QTabWidget()
        font_tab = tabs.font()
        font_tab.setPointSize(13)
        tabs.setFont(font_tab)

        # ── Pestaña 1: Reglas de transcripción ──────────────────────────────
        tab_trans = QWidget()
        tlay = QVBoxLayout(tab_trans)
        hint1 = QLabel(
            "Define cómo la IA debe transcribir el documento. "
            "Estas reglas se aplican antes que cualquier instrucción adicional."
        )
        hint1.setWordWrap(True)
        tlay.addWidget(hint1)
        txt_trans = QTextEdit()
        txt_trans.setPlainText(self.cfg.transcription_prompt)
        font_txt = txt_trans.font()
        font_txt.setPointSize(13)
        txt_trans.setFont(font_txt)
        tlay.addWidget(txt_trans)
        tabs.addTab(tab_trans, "📋  Reglas de transcripción")

        # ── Pestaña 2: Instrucciones adicionales ────────────────────────────
        tab_extra = QWidget()
        elay = QVBoxLayout(tab_extra)
        hint2 = QLabel(
            "Instrucciones adicionales del docente. Se añaden después de las reglas de "
            "transcripción y se guardan por sesión si hay una activa."
        )
        hint2.setWordWrap(True)
        elay.addWidget(hint2)
        txt_extra = QTextEdit()
        txt_extra.setPlainText(self._system_prompt)
        font_txt2 = txt_extra.font()
        font_txt2.setPointSize(13)
        txt_extra.setFont(font_txt2)
        elay.addWidget(txt_extra)
        tabs.addTab(tab_extra, "➕  Instrucciones adicionales")

        lay.addWidget(tabs)

        btn = QPushButton("Guardar")
        btn.setMinimumHeight(38)

        def _save():
            # Guardar reglas de transcripción
            self.cfg.set("transcription_prompt", txt_trans.toPlainText().strip())
            self.gemini.reconfigure()
            # Guardar instrucciones adicionales
            extra = txt_extra.toPlainText().strip()
            self._system_prompt = extra
            self.cfg.set("default_system_prompt", extra)
            if self.current_session:
                self.current_session.system_prompt = extra
                self.sessions.save(self.current_session)
            dlg.accept()

        btn.clicked.connect(_save)
        lay.addWidget(btn)
        dlg.exec()

    def _rename_session(self):
        if not self.current_session:
            QMessageBox.information(self, "Sin sesión", "Selecciona una sesión primero.")
            return
            
        dlg = QDialog(self)
        dlg.setWindowTitle("Renombrar sesión")
        dlg.resize(500, 150)
        lay = QVBoxLayout(dlg)
        
        lbl = QLabel("Nuevo nombre de la sesión")
        font = lbl.font()
        font.setBold(True)
        lbl.setFont(font)
        lay.addWidget(lbl)
        
        entry = QLineEdit()
        entry.setText(self.current_session.name)
        entry.selectAll()
        lay.addWidget(entry)
        
        btn = QPushButton("Renombrar")
        
        def _apply():
            new_name = entry.text().strip()
            if not new_name:
                return
            self.current_session.name = new_name
            self.sessions.save(self.current_session)
            self.lbl_session_name.setText(new_name)
            self._refresh_sessions()
            for i, s in enumerate(self._sessions_index):
                if s["id"] == self.current_session.id:
                    self.lb_sessions.setCurrentRow(i)
                    break
            dlg.accept()
            
        btn.clicked.connect(_apply)
        entry.returnPressed.connect(_apply)
        lay.addWidget(btn)
        
        dlg.exec()


    def _dlg_api_key(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Configurar API de Gemini")
        dlg.resize(600, 200)
        lay = QVBoxLayout(dlg)
        
        lbl = QLabel("Clave API de Google Gemini")
        font = lbl.font()
        font.setBold(True)
        lbl.setFont(font)
        lay.addWidget(lbl)
        
        lay.addWidget(QLabel("Obtén tu clave en aistudio.google.com"))
        
        entry = QLineEdit()
        entry.setEchoMode(QLineEdit.Password)
        entry.setText(self.cfg.api_key)
        lay.addWidget(entry)
        
        btn = QPushButton("Guardar")
        
        def _save():
            key = entry.text().strip()
            self.cfg.set("api_key", key)
            self.gemini.reconfigure()
            dlg.accept()
            QMessageBox.information(self, "Guardado", "Clave API configurada correctamente.")
            
        btn.clicked.connect(_save)
        lay.addWidget(btn)
        dlg.exec()


    def _dlg_model(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Modelo de Gemini")
        dlg.resize(600, 300)
        lay = QVBoxLayout(dlg)
        
        lbl = QLabel("Seleccionar modelo")
        font = lbl.font()
        font.setBold(True)
        lbl.setFont(font)
        lay.addWidget(lbl)
        
        models = [
            ("gemini-2.5-flash",      "Gemini 2.5 Flash     — Recomendado: velocidad y precio"),
            ("gemini-2.5-pro",        "Gemini 2.5 Pro       — Mayor capacidad y razonamiento"),
            ("gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite — Más económico y rápido"),
        ]
        
        group = QButtonGroup(dlg)
        btns = []
        for val, desc in models:
            rb = QRadioButton(desc)
            if val == self.cfg.model:
                rb.setChecked(True)
            lay.addWidget(rb)
            group.addButton(rb)
            btns.append((rb, val))
            
        btn = QPushButton("Guardar")
        
        def _save():
            selected = self.cfg.model
            for b, v in btns:
                if b.isChecked():
                    selected = v
                    break
            self.cfg.set("model", selected)
            self.gemini.reconfigure()
            dlg.accept()
            
        btn.clicked.connect(_save)
        lay.addWidget(btn)
        dlg.exec()


    def _dlg_shortcuts(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Ayuda – LectorIA")
        dlg.resize(740, 580)
        lay = QVBoxLayout(dlg)

        tabs = QTabWidget()
        font_tab = tabs.font()
        font_tab.setPointSize(13)
        tabs.setFont(font_tab)

        # ── Pestaña 1: Atajos ────────────────────────────────────────────────
        tab_keys = QWidget()
        tlay = QVBoxLayout(tab_keys)

        lbl = QLabel("Atajos de Teclado")
        font = lbl.font()
        font.setBold(True)
        font.setPointSize(16)
        lbl.setFont(font)
        tlay.addWidget(lbl)

        shortcuts = [
            ("Borrar",                     "Borrar (proyecto seleccionado)"),
            ("Espacio",                    "Reproducir / Pausar (pestaña activa)"),
            ("← Flecha izquierda",         "Retroceder 5 s (pestaña activa)"),
            ("→ Flecha derecha",           "Avanzar 5 s (pestaña activa)"),
            ("↑ Flecha arriba",            "Respuesta anterior (pestaña Preguntas)"),
            ("↓ Flecha abajo",             "Respuesta siguiente (pestaña Preguntas)"),
            ("Ctrl + 1 … Ctrl + 9",        "Guardar marcador en ranura 1–9"),
            ("Ctrl + 0",                   "Guardar marcador en ranura 10"),
            ("Alt + 1 … Alt + 9",          "Ir al marcador de ranura 1–9"),
            ("Alt + 0",                    "Ir al marcador de ranura 10"),
            ("Ctrl + ←",                   "Ir a pestaña Transcripción  (Voz)"),
            ("Ctrl + →",                   "Ir a pestaña Preguntas  (Voz)"),
            ("Enter",                      "Comenzar / detener grabación (pestaña Preguntas)"),
            ("Ctrl + Espacio",             "Nueva sesión"),
            ("Ctrl + O",                   "Abrir archivo"),
            ("F2",                         "Renombrar sesión"),
        ]

        grid = QWidget()
        glay = QVBoxLayout(grid)
        for key, action in shortcuts:
            rlay = QHBoxLayout()
            l1 = QLabel(key)
            l1.setMinimumWidth(230)
            f = l1.font()
            f.setBold(True)
            l1.setFont(f)
            rlay.addWidget(l1)
            rlay.addWidget(QLabel(action))
            glay.addLayout(rlay)

        scroll1 = QScrollArea()
        scroll1.setWidgetResizable(True)
        scroll1.setWidget(grid)
        tlay.addWidget(scroll1)
        tabs.addTab(tab_keys, "⌨  Atajos de Teclado")

        # ── Pestaña 2: Consejos ──────────────────────────────────────────────
        tab_tips = QWidget()
        tiplay = QVBoxLayout(tab_tips)

        lbl2 = QLabel("Consejos de Uso")
        font2 = lbl2.font()
        font2.setBold(True)
        font2.setPointSize(16)
        lbl2.setFont(font2)
        tiplay.addWidget(lbl2)

        tips = [
            (
                "El asistente solo analiza tu documento por defecto",
                "Al hacer preguntas en la pestaña Preguntas, el asistente responde basándose "
                "únicamente en el documento que cargaste. Si necesitas que también busque "
                "información adicional en internet para complementar la respuesta, pídeselo "
                "explícitamente: por ejemplo, «busca en internet más información sobre este "
                "tema». El asistente te avisará cuando use fuentes externas."
            ),
            (
                "Navegar con el teclado",
                "Toda la aplicación puede controlarse sin ratón. Usa Tab y Shift+Tab para "
                "moverte entre controles, las flechas del teclado para navegar el texto y las "
                "sesiones, y los atajos indicados arriba para las funciones principales."
            ),
            (
                "Sesiones y continuidad",
                "Cada documento procesado crea una sesión que se guarda automáticamente, "
                "incluyendo el historial de preguntas. Puedes retomar "
                "cualquier sesión desde la lista lateral."
            ),
            (
                "Velocidad y pausa",
                "Puedes pausar y reanudar la lectura con Espacio en cualquier momento. "
                "Usa las flechas ← y → para retroceder o avanzar oraciones si necesitas "
                "escuchar un fragmento de nuevo."
            ),
        ]

        tips_widget = QWidget()
        tips_lay = QVBoxLayout(tips_widget)
        tips_lay.setSpacing(18)
        for title, body in tips:
            lbl_t = QLabel(f"• {title}")
            ft = lbl_t.font()
            ft.setBold(True)
            ft.setPointSize(13)
            lbl_t.setFont(ft)
            tips_lay.addWidget(lbl_t)
            lbl_b = QLabel(body)
            lbl_b.setWordWrap(True)
            fb = lbl_b.font()
            fb.setPointSize(13)
            lbl_b.setFont(fb)
            tips_lay.addWidget(lbl_b)

        scroll2 = QScrollArea()
        scroll2.setWidgetResizable(True)
        scroll2.setWidget(tips_widget)
        tiplay.addWidget(scroll2)
        tabs.addTab(tab_tips, "💡  Consejos de Uso")

        lay.addWidget(tabs)
        dlg.exec()

    def _dlg_about(self):
        QMessageBox.about(
            self,
            "Acerca de LectorIA",
            "LectorIA – Asistente de Lectura Accesible\n"
            "Versión 1.0 (PySide6)\n\n"
            "Diseñado para estudiantes con discapacidad visual\n"
            "en colegios regulares.\n\n"
            "Tecnologías: Python · Google Gemini AI · gTTS · PySide6\n\n"
            "Con ♥ para quienes más lo necesitan."
        )

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LectorIA()
    window.show()
    sys.exit(app.exec())
