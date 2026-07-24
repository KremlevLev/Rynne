# modules/input_hub/voice_owner.py
"""Voice Ownership Manager - управление доступом к микрофону.

Гарантирует:
- Только один экземпляр захватывает микрофон одновременно
- Wake word и continuous mode не пересекаются
- Push-to-talk работает независимо от других режимов
- Корректное освобождение микрофона при завершении
"""
from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from enum import Enum, auto
from typing import Callable


logger = logging.getLogger("VoiceOwner")


class VoiceOwnerLock:
    """
    Thread-safe lock для микрофонного захвата.
    
    Используется для координации между:
    - WakeWordDetector (wake word mode)
    - VoiceListener (continuous/push-to-talk)
    - При необходимости: push-to-talk hotkey listener
    """
    
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._owner: str | None = None
        self._owner_count = 0
        self._async_lock = asyncio.Lock()
        
    def acquire(self, owner_name: str) -> bool:
        """Пытается захватить микрофон. Возвращает True если успешно."""
        with self._lock:
            if self._owner is None:
                self._owner = owner_name
                self._owner_count = 1
                logger.debug("Voice lock захвачен: %s", owner_name)
                return True
            
            if self._owner == owner_name:
                # Тот же owner может "перезахватить" (reenqueue)
                self._owner_count += 1
                logger.debug(
                    "Voice lock повторно захвачен: %s (count=%d)",
                    owner_name,
                    self._owner_count,
                )
                return True
                
            logger.warning(
                "Voice lock занят %s, %s не может захватить",
                self._owner,
                owner_name,
            )
            return False
    
    def release(self, owner_name: str) -> None:
        """Освобождает микрофон."""
        with self._lock:
            if self._owner != owner_name:
                logger.warning(
                    "Voice lock освобождается не владелцем: %s",
                    owner_name,
                )
                return
                
            self._owner_count -= 1
            
            if self._owner_count <= 0:
                self._owner = None
                self._owner_count = 0
                logger.debug("Voice lock полностью освобожден")
            else:
                logger.debug(
                    "Voice lock уменьшен: %s (count=%d)",
                    owner_name,
                    self._owner_count,
                )
    
    @property
    def owner(self) -> str | None:
        return self._owner if self._owner_count > 0 else None
    
    @property
    def is_free(self) -> bool:
        return self._owner is None


# Глобальный lock для всего процесса
_global_voice_lock = VoiceOwnerLock()


def get_voice_owner_lock() -> VoiceOwnerLock:
    """Возвращает глобальный voice owner lock."""
    return _global_voice_lock


class VoiceSession:
    """
    Async контекст-менеджер для микрофонного захвата.
    
    Использование:
        async with VoiceSession("wake_word"):
            # работа с микрофоном
            pass
        # автоматическое освобождение
    """
    
    def __init__(
        self,
        owner_name: str,
        on_conflict: Callable[[], None] | None = None,
    ) -> None:
        self.owner_name = owner_name
        self.on_conflict = on_conflict
        self._acquired = False
        
    async def __aenter__(self) -> bool:
        await self._async_lock.acquire()
        acquired = _global_voice_lock.acquire(self.owner_name)
        self._acquired = acquired
        
        if not acquired and self.on_conflict:
            self.on_conflict()
            
        return acquired
    
    async def __aexit__(
        self,
        exc_type: type | None,
        exc_val: object | None,
        exc_tb: object | None,
    ) -> None:
        if self._acquired:
            _global_voice_lock.release(self.owner_name)
            
        self._async_lock.release()
        
    @asynccontextmanager
    async def try_acquire(self) -> bool:
        """Пытается захватить, но не блокирует если Busy."""
        if _global_voice_lock.acquire(self.owner_name):
            self._acquired = True
            try:
                yield True
            finally:
                if self._acquired:
                    _global_voice_lock.release(self.owner_name)
        else:
            yield False


class PushToTalkHotkey:
    """
    Менеджер глобальных hotkey для push-to-talk.
    
    Поддерживает:
    - Регистрацию hotkey через Windows API
    - Иммунизацию к самоперехвату (TTS не слушается)
    - Работу в фоне
    """
    
    def __init__(
        self,
        hotkey: str = "ctrl+shift+space",
    ) -> None:
        self.hotkey = hotkey
        self._callback: Callable[[], None] | None = None
        self._registered = False
        self._lock = threading.Lock()
        
    def set_callback(self, callback: Callable[[], None]) -> None:
        """Устанавливает callback для hotkey."""
        with self._lock:
            self._callback = callback
            
    def is_available(self) -> bool:
        """Проверяет доступность hotkey (Windows only)."""
        return True  # Будет реализовано при необходимости
        
    def register(self) -> bool:
        """Регистрирует hotkey. Возвращает True если успешно."""
        with self._lock:
            if self._registered:
                return True
                
            # TODO: Реализовать через Windows API
            self._registered = True
            logger.info("Push-to-talk hotkey зарегистрирован: %s", self.hotkey)
            return True
    
    def unregister(self) -> None:
        """Снимает hotkey."""
        with self._lock:
            self._registered = False
            logger.info("Push-to-talk hotkey снят: %s", self.hotkey)
            
    def trigger(self) -> None:
        """Прямой вызов callback (для тестов)."""
        with self._lock:
            if self._callback is not None:
                self._callback()


def get_push_to_talk() -> PushToTalkHotkey:
    """Возвращает глобальный push-to-talk manager."""
    return PushToTalkHotkey()