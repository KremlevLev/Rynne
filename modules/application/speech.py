# modules/application/speech.py
from __future__ import annotations

import asyncio
import itertools
import logging
import re
import time

from modules.audio.tts import (
    reset_interrupt_flag,
    speak,
    stop_speaking,
    warm_up_tts,
)
from modules.domain.state import (
    AssistantState,
    RuntimeState,
)


logger = logging.getLogger("SpeechService")


def prepare_text_for_speech(
    text: str,
    *,
    max_total_characters: int = 700,
) -> str:
    """
    Подготавливает экранный текст для синтеза речи.

    Удаляет или сокращает:
    - блоки кода;
    - Markdown-таблицы;
    - URL;
    - техническую разметку;
    - чрезмерно длинный текст.

    Точный исходный ответ при этом остается доступен в display_text.
    """
    if not text or not text.strip():
        return ""

    original_text = text.strip()
    clean_text = original_text

    # Не озвучиваем многострочные блоки кода.
    clean_text = re.sub(
        r"```.*?```",
        " Код показан на экране. ",
        clean_text,
        flags=re.DOTALL,
    )

    # Не озвучиваем XML-подобные вызовы инструментов.
    clean_text = re.sub(
        r"<function=[^>]+>.*?</function>",
        " ",
        clean_text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Удаляем HTML/XML-разметку.
    clean_text = re.sub(
        r"<[^>]+>",
        " ",
        clean_text,
    )

    prepared_lines: list[str] = []
    removed_table_lines = 0

    for raw_line in clean_text.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        # Markdown-таблицы.
        if line.startswith("|") and line.endswith("|"):
            removed_table_lines += 1
            continue

        # Разделители Markdown-таблиц.
        if re.fullmatch(r"[\s|:\-]+", line):
            removed_table_lines += 1
            continue

        # Заголовки Markdown превращаем в обычный текст.
        line = re.sub(
            r"^#{1,6}\s*",
            "",
            line,
        )

        # Убираем маркеры списков.
        line = re.sub(
            r"^\s*[-*+]\s+",
            "",
            line,
        )
        line = re.sub(
            r"^\s*\d+[.)]\s+",
            "",
            line,
        )

        # Убираем Markdown-выделение и inline code.
        line = line.replace("**", "")
        line = line.replace("__", "")
        line = line.replace("`", "")

        # Не читаем URL целиком.
        line = re.sub(
            r"https?://\S+",
            "ссылка показана на экране",
            line,
            flags=re.IGNORECASE,
        )

        # Слишком длинные Windows-пути заменяем краткой фразой.
        line = re.sub(
            r"\b[A-Za-z]:\\(?:[^\\\s]+\\){2,}[^,\s]*",
            "путь показан на экране",
            line,
        )

        # Не читаем длинные хэши и токены.
        line = re.sub(
            r"\b[a-fA-F0-9]{32,}\b",
            "идентификатор показан на экране",
            line,
        )

        prepared_lines.append(line)

    clean_text = " ".join(prepared_lines)
    clean_text = re.sub(
        r"\s+",
        " ",
        clean_text,
    ).strip()

    # Если ответ состоял только из таблицы, все равно даем короткую
    # голосовую обратную связь.
    if not clean_text and removed_table_lines > 0:
        return "Сэр, подробности показаны в таблице на экране."

    if not clean_text:
        return ""

    if len(clean_text) <= max_total_characters:
        return clean_text

    shortened = clean_text[:max_total_characters]

    # Предпочитаем закончить на границе предложения.
    sentence_end = max(
        shortened.rfind("."),
        shortened.rfind("!"),
        shortened.rfind("?"),
    )

    if sentence_end >= 120:
        shortened = shortened[:sentence_end + 1]
    else:
        last_space = shortened.rfind(" ")

        if last_space > 0:
            shortened = shortened[:last_space]

        shortened = shortened.rstrip(" ,;:-") + "."

    return (
        shortened
        + " Подробности показаны на экране."
    )


def split_speech_chunks(
    text: str,
    *,
    max_chunk_characters: int = 420,
) -> list[str]:
    """
    Разбивает текст на фрагменты безопасного размера для Silero.

    Silero не получает строку длиннее max_chunk_characters.
    """
    clean_text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    if not clean_text:
        return []

    sentences = re.split(
        r"(?<=[.!?])\s+",
        clean_text,
    )

    chunks: list[str] = []
    current_chunk = ""

    for sentence in sentences:
        sentence = sentence.strip()

        if not sentence:
            continue

        # Если одно предложение само по себе слишком длинное,
        # разбиваем его по словам.
        if len(sentence) > max_chunk_characters:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""

            words = sentence.split()
            word_chunk = ""

            for word in words:
                candidate = (
                    f"{word_chunk} {word}".strip()
                )

                if (
                    word_chunk
                    and len(candidate) > max_chunk_characters
                ):
                    chunks.append(word_chunk)
                    word_chunk = word
                else:
                    word_chunk = candidate

            if word_chunk:
                chunks.append(word_chunk)

            continue

        candidate = (
            f"{current_chunk} {sentence}".strip()
        )

        if (
            current_chunk
            and len(candidate) > max_chunk_characters
        ):
            chunks.append(current_chunk)
            current_chunk = sentence
        else:
            current_chunk = candidate

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


class SpeechService:
    """
    Единый менеджер голосовых сообщений Nova.

    Гарантии:
    - только один TTS-worker;
    - сообщения воспроизводятся последовательно;
    - interrupt не отменяет голосовой цикл приложения;
    - shutdown корректно завершает worker;
    - устаревшие сообщения не воспроизводятся после interrupt.
    """

    def __init__(
        self,
        runtime: RuntimeState,
        event_handler=None,
        warm_up_on_start: bool = False,
    ) -> None:
        self.runtime = runtime
        self.event_handler = event_handler
        self.warm_up_on_start = warm_up_on_start

        self._queue: asyncio.PriorityQueue[
            tuple[
                int,
                int,
                int,
                str | None,
                asyncio.Future[None] | None,
            ]
        ] = asyncio.PriorityQueue()

        self._counter = itertools.count()
        self._worker_task: asyncio.Task[None] | None = None
        self._warmup_task: asyncio.Task[None] | None = None

        self._closed = False

        # После каждого interrupt поколение увеличивается.
        # Элементы старых поколений больше не воспроизводятся.
        self._generation = 0

        # Future текущего воспроизводимого сообщения.
        self._current_future: asyncio.Future[None] | None = None
        self._current_generation: int | None = None

        # Защищает start/close от одновременного исполнения.
        self._lifecycle_lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        return (
            self._worker_task is not None
            and not self._worker_task.done()
        )

    @property
    def queued_messages(self) -> int:
        return self._queue.qsize()

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError(
                    "SpeechService уже закрыт."
                )

            if self.is_running:
                return

            self._worker_task = asyncio.create_task(
                self._run(),
                name="nova-speech-worker",
            )
            if self.warm_up_on_start:
                self._warmup_task = asyncio.create_task(
                    self._warm_up(),
                    name="nova-tts-warmup",
                )

            logger.info("TTS worker запущен.")

    async def _warm_up(self) -> bool:
        started_at = time.monotonic()
        self._publish_status("loading", "Загружаю локальный голос Nova…")
        try:
            ready = bool(await asyncio.to_thread(warm_up_tts))
        except Exception:
            logger.exception("Ошибка фоновой подготовки TTS.")
            ready = False
        elapsed = time.monotonic() - started_at
        if ready:
            logger.info("TTS подготовлен за %.1f сек.", elapsed)
            self._publish_status("ready", f"Голос Nova готов · {elapsed:.1f} с")
        else:
            self._publish_status("error", "Локальный голос не загрузился. Проверьте журнал TTS.")
        return ready

    async def say(
        self,
        text: str,
        *,
        priority: int = 10,
        wait: bool = True,
    ) -> None:
        """
        Добавляет сообщение в очередь.

        wait=True:
            метод ожидает завершения или штатного прерывания речи.

        Прерывание пользователем не выбрасывает CancelledError наружу.
        Отмена родительской задачи при shutdown по-прежнему работает.
        """
        if self._closed:
            logger.debug(
                "Речь проигнорирована: SpeechService закрыт."
            )
            return

        if not self.is_running:
            await self.start()

        speech_text = prepare_text_for_speech(text)

        if not speech_text:
            logger.debug(
                "После подготовки не осталось текста для TTS."
            )
            return

        loop = asyncio.get_running_loop()
        completed: asyncio.Future[None] = (
            loop.create_future()
        )

        generation = self._generation

        await self._queue.put(
            (
                priority,
                next(self._counter),
                generation,
                speech_text,
                completed,
            )
        )
        self._publish_status("queued", "Готовлю голосовой ответ…")

        if not wait:
            return

        try:
            await completed

        except asyncio.CancelledError:
            # Если завершается всё приложение, отмена должна пройти
            # дальше и позволить корректно остановить voice_task.
            if self.runtime.is_shutting_down:
                raise

            # Пользовательское прерывание TTS — штатная операция.
            logger.info(
                "Ожидание речи завершено после прерывания."
            )
            return

        except Exception:
            logger.exception(
                "Не удалось озвучить сообщение."
            )

    async def interrupt(self) -> None:
        """
        Немедленно прерывает текущую речь и очищает очередь.

        Не отменяет voice loop и не завершает приложение.
        """
        if self._closed:
            return

        self._generation += 1

        logger.info(
            "Прерывание TTS. Новое поколение очереди: %s.",
            self._generation,
        )

        # Сначала разблокируем корутину, которая ожидает текущую речь.
        current_future = self._current_future

        if (
            current_future is not None
            and not current_future.done()
        ):
            current_future.set_result(None)

        # Останавливаем sounddevice/Silero в рабочем потоке.
        try:
            await asyncio.to_thread(
                stop_speaking
            )
        except Exception:
            logger.exception(
                "Ошибка во время остановки TTS."
            )

        # Очищаем еще не начатые сообщения.
        while True:
            try:
                (
                    _priority,
                    _counter,
                    _generation,
                    _text,
                    future,
                ) = self._queue.get_nowait()

            except asyncio.QueueEmpty:
                break

            try:
                if (
                    future is not None
                    and not future.done()
                ):
                    # Не cancel(): ожидание речи должно завершиться
                    # штатно, не отменяя родительскую задачу.
                    future.set_result(None)
            finally:
                self._queue.task_done()

        # Глобальное состояние определяет RuntimeState, а не TTS.
        if not self.runtime.is_shutting_down:
            next_state = (
                AssistantState.LISTENING
                if self.runtime.is_active
                else AssistantState.SLEEPING
            )

            await self.runtime.set_state(next_state)

    def _publish_status(self, status: str, message: str) -> None:
        if self.event_handler is not None:
            self.event_handler(
                "voice_status",
                {
                    "status": status,
                    "message": message,
                    "mode": "tts",
                },
            )

    async def close(self) -> None:
        async with self._lifecycle_lock:
            if self._closed:
                return

            logger.info("Закрытие SpeechService.")
            self._closed = True
            self._generation += 1

            current_future = self._current_future

            if (
                current_future is not None
                and not current_future.done()
            ):
                current_future.set_result(None)

            try:
                await asyncio.to_thread(
                    stop_speaking
                )
            except Exception:
                logger.exception(
                    "Ошибка остановки TTS при закрытии."
                )

            if self._warmup_task is not None:
                # asyncio.to_thread itself cannot abort an in-flight model load,
                # but awaiting it prevents a detached task from outliving Core.
                try:
                    await asyncio.wait_for(
                        asyncio.shield(self._warmup_task),
                        timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    logger.warning("TTS warm-up всё ещё завершается в фоне.")
                except Exception:
                    logger.exception("Ошибка фоновой подготовки TTS.")
                finally:
                    self._warmup_task = None

            # Завершаем ожидающие сообщения.
            while True:
                try:
                    (
                        _priority,
                        _counter,
                        _generation,
                        _text,
                        future,
                    ) = self._queue.get_nowait()

                except asyncio.QueueEmpty:
                    break

                try:
                    if (
                        future is not None
                        and not future.done()
                    ):
                        future.set_result(None)
                finally:
                    self._queue.task_done()

            worker_task = self._worker_task

            if worker_task is None:
                return

            # Sentinel с максимальным приоритетом.
            await self._queue.put(
                (
                    -1_000_000,
                    next(self._counter),
                    self._generation,
                    None,
                    None,
                )
            )

            try:
                await asyncio.wait_for(
                    worker_task,
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "TTS worker не завершился вовремя. "
                    "Выполняется принудительная отмена."
                )
                worker_task.cancel()

                await asyncio.gather(
                    worker_task,
                    return_exceptions=True,
                )
            finally:
                self._worker_task = None

            logger.info("SpeechService закрыт.")

    async def _run(self) -> None:
        logger.debug("Цикл TTS worker начал работу.")

        try:
            while True:
                (
                    _priority,
                    _counter,
                    generation,
                    text,
                    completed,
                ) = await self._queue.get()

                self._current_future = completed
                self._current_generation = generation
                speech_succeeded = False

                try:
                    # Sentinel.
                    if text is None:
                        return

                    # Сообщение было поставлено до interrupt.
                    if generation != self._generation:
                        if (
                            completed is not None
                            and not completed.done()
                        ):
                            completed.set_result(None)

                        continue

                    if (
                        self._warmup_task is not None
                        and not self._warmup_task.done()
                    ):
                        self._publish_status("loading", "Завершаю подготовку голоса…")
                        await asyncio.shield(self._warmup_task)

                    reset_interrupt_flag()

                    await self.runtime.set_state(
                        AssistantState.SPEAKING
                    )
                    self._publish_status("speaking", "Nova отвечает голосом…")

                    chunks = split_speech_chunks(text)

                    logger.debug(
                        "TTS сообщение разделено на %s фрагментов.",
                        len(chunks),
                    )

                    for chunk in chunks:
                        # Проверяем поколение до каждого фрагмента.
                        if generation != self._generation:
                            logger.debug(
                                "TTS остановлен между фрагментами."
                            )
                            break

                        played = await asyncio.to_thread(
                            speak,
                            chunk,
                        )
                        if played is False:
                            if generation != self._generation:
                                break
                            raise RuntimeError(
                                "Silero не смог синтезировать или воспроизвести речь."
                            )
                    speech_succeeded = generation == self._generation

                    if (
                        completed is not None
                        and not completed.done()
                    ):
                        completed.set_result(None)

                except asyncio.CancelledError:
                    if (
                        completed is not None
                        and not completed.done()
                    ):
                        completed.set_result(None)

                    raise

                except Exception as exc:
                    logger.exception(
                        "Ошибка TTS worker."
                    )
                    self._publish_status(
                        "error",
                        "Голос временно недоступен; текстовый ответ уже показан.",
                    )

                    if (
                        completed is not None
                        and not completed.done()
                    ):
                        completed.set_exception(exc)

                finally:
                    self._current_future = None
                    self._current_generation = None
                    self._queue.task_done()

                    if not self.runtime.is_shutting_down:
                        next_state = (
                            AssistantState.LISTENING
                            if self.runtime.is_active
                            else AssistantState.SLEEPING
                        )

                        await self.runtime.set_state(
                            next_state
                        )
                    if speech_succeeded:
                        self._publish_status("ready", "Голос готов.")

        except asyncio.CancelledError:
            logger.info("TTS worker отменен.")
            raise

        finally:
            # Любой оставшийся текущий Future должен завершиться,
            # чтобы другие части приложения не зависли.
            current_future = self._current_future

            if (
                current_future is not None
                and not current_future.done()
            ):
                current_future.set_result(None)

            self._current_future = None
            self._current_generation = None

            logger.debug("Цикл TTS worker завершен.")
