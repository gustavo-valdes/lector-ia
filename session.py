#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
session.py — Modelos de sesión y gestión de persistencia.
"""

import json
from pathlib import Path

from config import SESSIONS_DIR, AUDIO_DIR


# ═══════════════════════════════════════════════════════════════════════════════
# SESIONES
# ═══════════════════════════════════════════════════════════════════════════════

class Session:
    def __init__(self, session_id: str, name: str, created_at: str,
                 file_path: str, system_prompt: str,
                 messages: list, bookmarks: dict | None = None,
                 qa_messages: list | None = None):
        self.id            = session_id
        self.name          = name
        self.created_at    = created_at
        self.file_path     = file_path
        self.system_prompt = system_prompt
        self.messages      = messages       # [{"role": "user"|"model", "content": str}]
        self.bookmarks     = bookmarks or {}  # {"1": idx, ..., "10": idx}
        self.qa_messages   = qa_messages or []  # historial de preguntas/respuestas

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "name":          self.name,
            "created_at":    self.created_at,
            "file_path":     self.file_path,
            "system_prompt": self.system_prompt,
            "messages":      self.messages,
            "bookmarks":     self.bookmarks,
            "qa_messages":   self.qa_messages,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        # Migración: sesiones antiguas tienen "bookmark" (int) en vez de "bookmarks" (dict)
        bookmarks = d.get("bookmarks")
        if bookmarks is None:
            old = d.get("bookmark")
            bookmarks = {"1": old} if old is not None else {}
        return cls(
            d["id"], d["name"], d["created_at"],
            d.get("file_path", ""), d.get("system_prompt", ""),
            d.get("messages", []), bookmarks,
            d.get("qa_messages", []),
        )


class SessionManager:
    def save(self, session: Session):
        path = SESSIONS_DIR / f"{session.id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session.to_dict(), f, indent=2, ensure_ascii=False)

    def load(self, session_id: str) -> Session:
        path = SESSIONS_DIR / f"{session_id}.json"
        with open(path, "r", encoding="utf-8") as f:
            return Session.from_dict(json.load(f))

    def list_all(self) -> list[dict]:
        sessions = []
        for p in sorted(SESSIONS_DIR.glob("*.json"),
                        key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
                sessions.append({"id": d["id"], "name": d["name"],
                                  "created_at": d.get("created_at", "")})
            except Exception:
                pass
        return sessions

    def delete(self, session_id: str):
        p = SESSIONS_DIR / f"{session_id}.json"
        if p.exists():
            p.unlink()

    def audio_path(self, text_hash: str, speed: str) -> Path:
        return AUDIO_DIR / f"{text_hash}_{speed}.mp3"
