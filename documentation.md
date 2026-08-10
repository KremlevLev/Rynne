# Rynne 2.0 - Компактный план

## Выполненные задачи (✅)

- Gemini Provider integration (api keys, модели, priority 20)
- Quota groups в ModelGateway
- Execution Checkpoint и Execution Ledger
- ToolObservation для контекста
- Obsidian Adapter
- **7. Разделение счётчиков** - обновлен `modules/tools/budgets.py`
- **8. Целевой бюджет запроса** - обновлены лимиты в `AgentBudget`
- **10. Model Catalog** - создан `modules/brain/model_catalog.py` + тесты
- **Приоритет 5 - Tool Visibility** - создан `modules/tools/tool_visibility.py`
- **Clean up main.py** - удалено дублирование `resolved_request`
- **Приоритет 7 - Reasoning Loop** - создан `modules/agent/reasoning.py` + тесты
- **Приоритет 11 - Tool Composition** - создан `modules/tools/composition.py`:
  - ToolChain и ToolChainStep для цепочек инструментов
  - ToolComposer для выполнения цепочек
  - Параллельное выполнение через `run_parallel()` в ReasoningLoop

## Текущие задачи

### 9. ModelGateway статус
- ✅ KeySlot с cooldown
- ✅ Route cooldown
- ✅ Model cooldown
- ✅ Provider cooldown
- ✅ Quota group cooldown (Gemini, Groq)
- ✅ Гроq → Gemini → OpenRouter fallback

### Приоритет 5 - Tool Visibility
- ✅ PUBLIC_SKILLS - публичные навыки (видимы модели)
- ✅ INTERNAL_PRIMITIVES - внутренние примитивы (скрыты)
- ✅ RECOVERY_TOOLS - инструменты восстановления (только для recovery)

## Будущие улучшения (планируются)

### Приоритет 8 - Advanced Research Tools
- Deep web research: многошаговое исследование с анализом источников
- Source verification: проверка достоверности источников
- Citation management: автоматическое формирование списка источников
- Research synthesis: объединение информации из разных источников

### Приоритет 9 - Memory Enhancement
- Hierarchical memory: дерево памяти с приоритетами
- Memory decay: "забывание" устаревшей информации
- Memory consolidation: периодическое обобщение памяти
- Semantic search: векторный поиск по памяти

### Приоритет 10 - Multi-modal Reasoning
- Vision reasoning: анализ экрана + выполнение действий
- OCR integration: распознавание текста + последующее действие
- Screenshot analysis: понимание UI через изображения
- Visual planning: планирование на основе визуального контекста

### Приоритет 12 - Recovery & Self-healing
- Automatic rollback: откат при неудачах
- Alternative paths: поиск альтернативных решений
- Graceful degradation: работа в упрощенном режиме
- Self-diagnostics: диагностика самого агента

## Тесты
```bash
python -m pytest tests/ -q  # 315 passed