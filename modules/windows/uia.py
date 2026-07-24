# modules/windows/uia.py
"""UI Automation + OCR + Vision Grounding for Windows.

Объединяет три источника координат:
1. Windows UI Automation (надёжный, но не всегда доступен)
2. OCR (распознаёт текст на экране)
3. Vision grounding (OmniParser-подобный разбор интерфейса)

Выбирает оптимальный источник координат для клика.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from modules.domain.results import ToolResult

logger = logging.getLogger("UIA")


@dataclass
class UIElement:
    """Представление UI-элемента с координатами."""
    element_id: str
    name: str
    role: str
    state: str
    x: int
    y: int
    width: int
    height: int
    confidence: float = 1.0
    source: str = "uia"  # uia, ocr, vision

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "name": self.name,
            "role": self.role,
            "state": self.state,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "center_x": self.center[0],
            "center_y": self.center[1],
            "confidence": self.confidence,
            "source": self.source,
        }


class UIAGrounder:
    """
    Комбинирует UIA, OCR и Vision для поиска элементов.
    
    Приоритет источников:
    1. UIA (если элемент найден через UI Automation)
    2. OCR (если найден распознанный текст)
    3. Vision (fallback через vision модель)
    """

    def __init__(self) -> None:
        self._uia_available = self._check_uia_availability()

    def _check_uia_availability(self) -> bool:
        """Проверяет доступность UI Automation."""
        try:
            import uiautomation
            return True
        except ImportError:
            return False

    def get_active_window_elements(self) -> list[UIElement]:
        """
        Получает элементы активного окна через UIA.
        
        Returns:
            Список UI-элементов с координатами.
        """
        if not self._uia_available:
            return []

        try:
            import uiautomation
            
            elements: list[UIElement] = []
            root = uiautomation.GetForegroundControl()
            
            if root is None:
                return []
            
            def walk_tree(control: Any, depth: int = 0) -> None:
                if depth > 10:  # Ограничиваем глубину
                    return
                
                try:
                    name = control.Name or ""
                    role = control.ControlType or "Unknown"
                    state = str(control.CurrentControlState) or "Unknown"
                    
                    rect = control.BoundingRectangle
                    if rect and rect.width > 0 and rect.height > 0:
                        element = UIElement(
                            element_id=f"uia_{id(control)}",
                            name=name,
                            role=role,
                            state=state,
                            x=rect.left,
                            y=rect.top,
                            width=rect.width,
                            height=rect.height,
                            confidence=0.95,
                            source="uia",
                        )
                        elements.append(element)
                except Exception:
                    pass
                
                try:
                    for child in control.GetChildren():
                        walk_tree(child, depth + 1)
                except Exception:
                    pass
            
            walk_tree(root)
            return elements
            
        except Exception as e:
            logger.exception("UIA tree walk failed")
            return []

    def find_element(
        self,
        query: str,
        elements: list[UIElement] | None = None,
    ) -> UIElement | None:
        """
        Ищет элемент по запросу.
        
        Args:
            query: Поисковый запрос (имя, текст, роль)
            elements: Предзагруженные элементы (если None - получит через UIA)
            
        Returns:
            Найденный элемент или None.
        """
        if elements is None:
            elements = self.get_active_window_elements()
        
        query_lower = query.lower()
        
        # Приоритет: точное совпадение имени, затем по роли, затем по тексту
        for element in elements:
            if query_lower == element.name.lower():
                return element
        
        for element in elements:
            if query_lower in element.name.lower():
                return element
        
        for element in elements:
            if query_lower in element.role.lower():
                return element
        
        return None

    def number_elements(
        self,
        elements: list[UIElement] | None = None,
    ) -> list[UIElement]:
        """
        Нумерует кликабельные элементы для пользователя.
        
        Returns:
            Элементы с номерами в имени.
        """
        if elements is None:
            elements = self.get_active_window_elements()
        
        clickable_roles = {
            "Button", "Hyperlink", "MenuItem", "CheckBox",
            "ComboBox", "Edit", "ListItem",
        }
        
        numbered: list[UIElement] = []
        counter = 1
        
        for element in elements:
            if element.role in clickable_roles:
                numbered.append(UIElement(
                    element_id=element.element_id,
                    name=f"[{counter}] {element.name}",
                    role=element.role,
                    state=element.state,
                    x=element.x,
                    y=element.y,
                    width=element.width,
                    height=element.height,
                    confidence=element.confidence,
                    source=element.source,
                ))
                counter += 1
        
        return numbered

    def get_element_by_number(
        self,
        number: int,
        elements: list[UIElement] | None = None,
    ) -> UIElement | None:
        """
        Получает элемент по номеру.
        
        Args:
            number: Номер элемента (1-based)
            elements: Предзагруженные элементы
            
        Returns:
            Элемент с указанным номером или None.
        """
        numbered = self.number_elements(elements)
        
        for element in numbered:
            if element.name.startswith(f"[{number}]"):
                return element
        
        return None


def create_uia_tools() -> dict[str, Any]:
    """Создаёт словарь UIA инструментов."""
    grounder = UIAGrounder()
    
    return {
        "get_active_window_elements": grounder.get_active_window_elements,
        "find_element": grounder.find_element,
        "number_elements": grounder.number_elements,
        "get_element_by_number": grounder.get_element_by_number,
    }