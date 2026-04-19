#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tts_engine.py — Motor TTS (gTTS + pygame), beeps de UI y utilidades de texto.
"""

import re
import math
import array
import time
import hashlib
import threading
from config import AUDIO_DIR
from session import SessionManager

# ── Dependencias opcionales ──────────────────────────────────────────────────

try:
    import pygame
    pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=1024)
    PYGAME_OK = True
except Exception:
    PYGAME_OK = False

try:
    from gtts import gTTS
    GTTS_OK = True
except ImportError:
    GTTS_OK = False


# ═══════════════════════════════════════════════════════════════════════════════
# BEEPS DE INTERFAZ
# ═══════════════════════════════════════════════════════════════════════════════

_SAMPLE_RATE = 22050


def _make_tone(freq: float, dur_ms: int, vol: float, fade_s: float) -> "pygame.mixer.Sound":
    n = int(_SAMPLE_RATE * dur_ms / 1000)
    buf = array.array('h', [0] * n)
    fade_n = max(int(_SAMPLE_RATE * fade_s), 1)
    for i in range(n):
        env = min(min(i, n - i, fade_n) / fade_n, 1.0)
        buf[i] = int(vol * env * 32767 * math.sin(2 * math.pi * freq * i / _SAMPLE_RATE))
    return pygame.mixer.Sound(buffer=buf)


def _play_ready_beep():
    """Reproduce un beep doble agradable para indicar que el audio está listo."""
    if not PYGAME_OK:
        return
    try:
        t1 = _make_tone(880,  120, vol=0.45, fade_s=0.015)
        t2 = _make_tone(1100, 150, vol=0.45, fade_s=0.015)
        t1.play()
        time.sleep(0.18)
        t2.play()
    except Exception:
        pass


def _play_tab_beep(n: int):
    """Reproduce n pitidos cortos para indicar cambio de pestaña (1=tab1, 2=tab2)."""
    if not PYGAME_OK:
        return
    try:
        tone = _make_tone(900, 90, vol=0.4, fade_s=0.008)
        for i in range(n):
            tone.play()
            if i < n - 1:
                time.sleep(0.18)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# UTILIDADES DE TEXTO
# ═══════════════════════════════════════════════════════════════════════════════

def tokenize(text: str) -> list[str]:
    """Divide el texto en palabras (sin espacios)."""
    return [w for w in re.split(r"\s+", text.strip()) if w]


def _syllables_es(word: str) -> int:
    """Cuenta sílabas aproximadas de una palabra en español."""
    clean = re.sub(r"[^aeiouáéíóúüAEIOUÁÉÍÓÚÜ]", "", word.lower())
    groups = re.findall(r"[aeiouáéíóúü]+", clean)
    return max(1, len(groups))


def split_sentences(text: str) -> list[str]:
    """Divide el texto en oraciones para generar audio por segmento."""
    parts = re.split(r'(?<=[.!?…])\s+', text.strip())
    result = []
    for part in parts:
        if len(part) > 220:
            sub = re.split(r'(?<=[,;])\s+', part)
            result.extend(sub)
        else:
            result.append(part)
    return [s for s in result if s.strip()]


def _distribute_timings(words: list[str], dur_ms: int, offset_ms: int) -> list[tuple[int, int]]:
    """Distribuye dur_ms entre las palabras proporcional a sus sílabas."""
    syls = [_syllables_es(w) for w in words]
    total_syls = max(sum(syls), 1)
    timings = []
    t = offset_ms
    for i, w in enumerate(words):
        word_dur = int(dur_ms * syls[i] / total_syls)
        word_dur = max(60, word_dur)
        timings.append((t, t + word_dur))
        t += word_dur
    return timings


# ═══════════════════════════════════════════════════════════════════════════════
# MOTOR TTS
# ═══════════════════════════════════════════════════════════════════════════════

class TTSEngine:
    """
    Motor TTS que reproduce oraciones de forma encadenada (una a la vez).
    Cada oración reinicia get_pos() a 0, eliminando la deriva acumulativa
    que ocurría al concatenar MP3s y rastrear posición global.
    """

    def __init__(self, sessions: SessionManager):
        self.sessions      = sessions
        self.words:        list[str]  = []   # todas las palabras, lista plana
        self.current_index: int       = 0
        self.is_playing:   bool       = False
        self.is_paused:    bool       = False
        self.on_word:      callable   = None
        self.on_end:       callable   = None
        self._audio_ready: bool       = False
        self._preparing:   bool       = False
        self._sentences:   list[dict] = []   # dicts con datos por oración
        self._cur_sent_idx: int       = 0
        self._stop_evt     = threading.Event()
        self._cancel_prep  = threading.Event()

    # ── Preparación ──────────────────────────────────────────────────────────

    def cancel_prepare(self):
        self._cancel_prep.set()

    def prepare(self, text: str, slow: bool,
                on_ready: callable = None, on_error: callable = None,
                on_progress: callable = None,
                on_cancelled: callable = None):
        self._audio_ready  = False
        self._preparing    = True
        self._cancel_prep.clear()
        self.current_index = 0
        self._cur_sent_idx = 0
        speed_tag = "lento" if slow else "normal"

        def _gen():
            if not GTTS_OK:
                if on_error:
                    on_error("gTTS no está instalado.")
                return

            sentences   = split_sentences(text)
            total_sents = len(sentences)
            all_words:  list[str]  = []
            sent_data:  list[dict] = []
            word_offset = 0

            for idx_s, sent in enumerate(sentences):
                if self._cancel_prep.is_set():
                    self._preparing = False
                    if on_cancelled:
                        on_cancelled()
                    return

                sent_words = tokenize(sent)
                if not sent_words:
                    continue

                h_sent    = hashlib.md5((sent + speed_tag).encode()).hexdigest()[:14]
                sent_path = AUDIO_DIR / f"s_{h_sent}.mp3"

                if not sent_path.exists():
                    try:
                        gTTS(text=sent, lang="es", slow=slow).save(str(sent_path))
                    except Exception as e:
                        if on_error:
                            on_error(str(e))
                        return

                if self._cancel_prep.is_set():
                    self._preparing = False
                    if on_cancelled:
                        on_cancelled()
                    return

                try:
                    snd    = pygame.mixer.Sound(str(sent_path))
                    dur_ms = max(1, int(snd.get_length() * 1000))
                    del snd
                except Exception:
                    ms_per_syl = 182 if slow else 133
                    dur_ms = sum(_syllables_es(w) * ms_per_syl for w in sent_words)

                # Los timings son locales a la oración (offset=0), sin acumulación.
                local_timings = _distribute_timings(sent_words, dur_ms, 0)

                sent_data.append({
                    "words":         sent_words,
                    "audio_path":    sent_path,
                    "dur_ms":        dur_ms,
                    "word_offset":   word_offset,
                    "local_timings": local_timings,
                })
                all_words.extend(sent_words)
                word_offset += len(sent_words)

                if on_progress:
                    on_progress(idx_s + 1, total_sents)

            self.words      = all_words
            self._sentences = sent_data
            self._audio_ready = True
            self._preparing   = False
            if on_ready:
                on_ready()

        threading.Thread(target=_gen, daemon=True).start()

    # ── Reproducción ─────────────────────────────────────────────────────────

    def play(self):
        if not PYGAME_OK or not self._audio_ready:
            return
        if self.is_paused:
            self._stop_evt.clear()
            pygame.mixer.music.unpause()
            self.is_paused  = False
            self.is_playing = True
            threading.Thread(target=self._sync_loop,
                             args=(self._cur_sent_idx,), daemon=True).start()
        else:
            self._stop_evt.clear()
            self._load_and_play(self._cur_sent_idx)

    def _load_and_play(self, sent_idx: int):
        if sent_idx >= len(self._sentences):
            self.is_playing = False
            self.is_paused  = False
            if self.on_end:
                self.on_end()
            return
        sent = self._sentences[sent_idx]
        try:
            pygame.mixer.music.load(str(sent["audio_path"]))
            pygame.mixer.music.play()
        except Exception as e:
            return
        self.is_playing = True
        threading.Thread(target=self._sync_loop,
                         args=(sent_idx,), daemon=True).start()

    def _sync_loop(self, sent_idx: int):
        sent          = self._sentences[sent_idx]
        local_timings = sent["local_timings"]
        word_offset   = sent["word_offset"]
        prev_global   = -1

        while not self._stop_evt.is_set():
            if not pygame.mixer.music.get_busy():
                if self._stop_evt.is_set():
                    return
                # Oración terminó — avanzar a la siguiente
                next_idx = sent_idx + 1
                self._cur_sent_idx = next_idx
                if next_idx < len(self._sentences):
                    self._load_and_play(next_idx)
                else:
                    self.is_playing = False
                    self.is_paused  = False
                    if self.on_end:
                        self.on_end()
                return

            pos = pygame.mixer.music.get_pos()
            if pos < 0:
                time.sleep(0.025)
                continue

            for i, (s, e) in enumerate(local_timings):
                if s <= pos < e:
                    global_idx = word_offset + i
                    if global_idx != prev_global:
                        prev_global        = global_idx
                        self.current_index = global_idx
                        if self.on_word:
                            self.on_word(global_idx)
                    break

            time.sleep(0.025)

    def pause(self):
        if not self.is_playing or self.is_paused:
            return
        self._stop_evt.set()
        pygame.mixer.music.pause()
        self.is_paused = True

    def toggle(self):
        if self.is_playing and not self.is_paused:
            self.pause()
        else:
            self.play()

    def stop(self):
        self._stop_evt.set()
        if PYGAME_OK:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
        self.is_playing    = False
        self.is_paused     = False
        self._cur_sent_idx = 0
        self.current_index = 0

    def goto_word(self, index: int):
        if not self._sentences or index >= len(self.words):
            return
        # Encontrar la oración que contiene esta palabra
        sent_idx = 0
        for i, sent in enumerate(self._sentences):
            if sent["word_offset"] <= index < sent["word_offset"] + len(sent["words"]):
                sent_idx = i
                break

        was_playing = self.is_playing and not self.is_paused
        self._stop_evt.set()
        time.sleep(0.05)
        self._cur_sent_idx = sent_idx
        self.current_index = index

        if PYGAME_OK and self._audio_ready:
            try:
                pygame.mixer.music.load(str(self._sentences[sent_idx]["audio_path"]))
                pygame.mixer.music.play()
                if not was_playing:
                    pygame.mixer.music.pause()
                    self.is_paused  = True
                    self.is_playing = True
                else:
                    self.is_paused = False
                    self.is_playing = True
                    self._stop_evt.clear()
                    threading.Thread(target=self._sync_loop,
                                     args=(sent_idx,), daemon=True).start()
            except Exception:
                pass

        if self.on_word:
            self.on_word(index)

    def prev_sentence(self):
        """Salta al inicio de la oración anterior (o la actual si es la primera)."""
        target = max(0, self._cur_sent_idx - 1)
        first_word = self._sentences[target]["word_offset"]
        self.goto_word(first_word)

    def next_sentence(self):
        """Salta al inicio de la oración siguiente."""
        target = min(len(self._sentences) - 1, self._cur_sent_idx + 1)
        first_word = self._sentences[target]["word_offset"]
        self.goto_word(first_word)
