# tests/test_voice_owner.py
"""Тесты для Voice Ownership Manager."""
from __future__ import annotations

from modules.input_hub.voice_owner import (
    VoiceOwnerLock,
    PushToTalkHotkey,
    get_voice_owner_lock,
    get_push_to_talk,
)


class TestVoiceOwnerLock:
    """Тесты VoiceOwnerLock."""
    
    def test_initial_state(self) -> None:
        lock = VoiceOwnerLock()
        assert lock.owner is None
        assert lock.is_free is True
        
    def test_acquire_by_free_lock(self) -> None:
        lock = VoiceOwnerLock()
        result = lock.acquire("wake_word")
        assert result is True
        assert lock.owner == "wake_word"
        assert lock.is_free is False
        
    def test_acquire_by_owner(self) -> None:
        lock = VoiceOwnerLock()
        lock.acquire("wake_word")
        # Тот же owner может перезахватить
        result = lock.acquire("wake_word")
        assert result is True
        assert lock._owner_count == 2
        
    def test_acquire_when_locked(self) -> None:
        lock = VoiceOwnerLock()
        lock.acquire("wake_word")
        # Другой owner не может захватить
        result = lock.acquire("continuous")
        assert result is False
        assert lock.owner == "wake_word"

    def test_non_reentrant_recorder_lease_rejects_duplicate_stream(self) -> None:
        lock = VoiceOwnerLock()
        assert lock.acquire("wake_word", allow_reentrant=False)
        assert not lock.acquire("wake_word", allow_reentrant=False)
        assert lock._owner_count == 1
        
    def test_release(self) -> None:
        lock = VoiceOwnerLock()
        lock.acquire("wake_word")
        lock.release("wake_word")
        assert lock.is_free is True
        
    def test_release_non_owner(self) -> None:
        lock = VoiceOwnerLock()
        lock.acquire("wake_word")
        lock.release("continuous")  # Не владелец
        assert lock.owner == "wake_word"
        
    def test_multiple_acquire_release(self) -> None:
        lock = VoiceOwnerLock()
        for _ in range(3):
            lock.acquire("wake_word")
        assert lock._owner_count == 3
        
        lock.release("wake_word")
        assert lock._owner_count == 2
        
        lock.release("wake_word")
        assert lock._owner_count == 1
        
        lock.release("wake_word")
        assert lock.is_free is True


class TestPushToTalkHotkey:
    """Тесты PushToTalkHotkey."""
    
    def test_initial_state(self) -> None:
        ptt = PushToTalkHotkey("ctrl+shift+space")
        assert ptt.hotkey == "ctrl+shift+space"
        assert ptt.is_available() is True
        assert ptt._callback is None
        
    def test_set_callback(self) -> None:
        ptt = PushToTalkHotkey()
        called = []
        
        def my_callback() -> None:
            called.append(1)
            
        ptt.set_callback(my_callback)
        ptt.trigger()
        
        assert len(called) == 1
        
    def test_register_unregister(self) -> None:
        ptt = PushToTalkHotkey()
        assert ptt.register() is True
        assert ptt._registered is True
        
        # Повторная регистрация
        assert ptt.register() is True
        
        ptt.unregister()
        assert ptt._registered is False
        
    def test_trigger_without_callback(self) -> None:
        ptt = PushToTalkHotkey()
        # Не должно падать
        ptt.trigger()
        
    def test_multiple_triggers(self) -> None:
        ptt = PushToTalkHotkey()
        results: list[int] = []
        
        def my_callback() -> None:
            results.append(1)
            
        ptt.set_callback(my_callback)
        
        # Тестируем многократные вызовы
        for _ in range(100):
            ptt.trigger()
            
        assert len(results) == 100


class TestGlobalFunctions:
    """Тесты глобальных функций."""
    
    def test_get_voice_owner_lock_returns_singleton(self) -> None:
        lock1 = get_voice_owner_lock()
        lock2 = get_voice_owner_lock()
        assert lock1 is lock2
        
    def test_get_push_to_talk_returns_new_instance(self) -> None:
        ptt1 = get_push_to_talk()
        ptt2 = get_push_to_talk()
        # Каждый вызов возвращает новый экземпляр
        assert ptt1 is not ptt2
