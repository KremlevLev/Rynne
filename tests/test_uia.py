# tests/test_uia.py
"""Tests for UIA + OCR + Vision Grounding module."""
import pytest
from unittest.mock import MagicMock, patch

from modules.windows.uia import UIElement, UIAGrounder, create_uia_tools


class TestUIElement:
    """Tests for UIElement dataclass."""

    def test_center_calculation(self):
        """Test center point calculation."""
        element = UIElement(
            element_id="test_1",
            name="Button",
            role="Button",
            state="Enabled",
            x=100,
            y=200,
            width=50,
            height=30,
        )
        assert element.center == (125, 215)

    def test_to_dict(self):
        """Test serialization to dictionary."""
        element = UIElement(
            element_id="test_1",
            name="Test",
            role="Edit",
            state="Focused",
            x=0,
            y=0,
            width=100,
            height=50,
            confidence=0.9,
            source="ocr",
        )
        result = element.to_dict()
        
        assert result["element_id"] == "test_1"
        assert result["name"] == "Test"
        assert result["role"] == "Edit"
        assert result["state"] == "Focused"
        assert result["x"] == 0
        assert result["y"] == 0
        assert result["width"] == 100
        assert result["height"] == 50
        assert result["center_x"] == 50
        assert result["center_y"] == 25
        assert result["confidence"] == 0.9
        assert result["source"] == "ocr"


class TestUIAGrounder:
    """Tests for UIAGrounder class."""

    def test_init_without_uia(self):
        """Test initialization when uiautomation is not available."""
        with patch("modules.windows.uia.UIAGrounder._check_uia_availability", return_value=False):
            grounder = UIAGrounder()
            assert grounder._uia_available is False

    def test_init_with_uia(self):
        """Test initialization when uiautomation is available."""
        with patch("modules.windows.uia.UIAGrounder._check_uia_availability", return_value=True):
            grounder = UIAGrounder()
            assert grounder._uia_available is True

    def test_get_active_window_elements_without_uia(self):
        """Test getting elements when UIA is not available."""
        with patch("modules.windows.uia.UIAGrounder._check_uia_availability", return_value=False):
            grounder = UIAGrounder()
            elements = grounder.get_active_window_elements()
            assert elements == []

    def test_find_element_exact_match(self):
        """Test finding element by exact name match."""
        grounder = UIAGrounder()
        elements = [
            UIElement("1", "OK", "Button", "Enabled", 0, 0, 50, 30),
            UIElement("2", "Cancel", "Button", "Enabled", 60, 0, 50, 30),
        ]
        
        result = grounder.find_element("OK", elements)
        assert result is not None
        assert result.name == "OK"

    def test_find_element_partial_match(self):
        """Test finding element by partial name match."""
        grounder = UIAGrounder()
        elements = [
            UIElement("1", "OK Button", "Button", "Enabled", 0, 0, 50, 30),
            UIElement("2", "Cancel", "Button", "Enabled", 60, 0, 50, 30),
        ]
        
        result = grounder.find_element("OK", elements)
        assert result is not None
        assert result.name == "OK Button"

    def test_find_element_by_role(self):
        """Test finding element by role when name not found."""
        grounder = UIAGrounder()
        elements = [
            UIElement("1", "Submit", "Button", "Enabled", 0, 0, 50, 30),
            UIElement("2", "Input Field", "Edit", "Focused", 60, 0, 100, 30),
        ]
        
        result = grounder.find_element("Edit", elements)
        assert result is not None
        assert result.role == "Edit"

    def test_find_element_not_found(self):
        """Test finding element that doesn't exist."""
        grounder = UIAGrounder()
        elements = [
            UIElement("1", "OK", "Button", "Enabled", 0, 0, 50, 30),
        ]
        
        result = grounder.find_element("NonExistent", elements)
        assert result is None

    def test_number_elements(self):
        """Test numbering clickable elements."""
        grounder = UIAGrounder()
        elements = [
            UIElement("1", "OK", "Button", "Enabled", 0, 0, 50, 30),
            UIElement("2", "Text", "Text", "Enabled", 60, 0, 100, 30),
            UIElement("3", "Cancel", "Button", "Enabled", 170, 0, 50, 30),
            UIElement("4", "Input", "Edit", "Focused", 230, 0, 100, 30),
        ]
        
        numbered = grounder.number_elements(elements)
        
        # Only Button and Edit should be numbered (clickable)
        assert len(numbered) == 3
        assert numbered[0].name == "[1] OK"
        assert numbered[1].name == "[2] Cancel"
        assert numbered[2].name == "[3] Input"

    def test_get_element_by_number(self):
        """Test getting element by its number."""
        grounder = UIAGrounder()
        elements = [
            UIElement("1", "OK", "Button", "Enabled", 0, 0, 50, 30),
            UIElement("2", "Cancel", "Button", "Enabled", 60, 0, 50, 30),
        ]
        
        result = grounder.get_element_by_number(1, elements)
        assert result is not None
        assert result.name == "[1] OK"

    def test_get_element_by_number_not_found(self):
        """Test getting element by number that doesn't exist."""
        grounder = UIAGrounder()
        elements = [
            UIElement("1", "OK", "Button", "Enabled", 0, 0, 50, 30),
        ]
        
        result = grounder.get_element_by_number(99, elements)
        assert result is None


class TestCreateUIATools:
    """Tests for create_uia_tools factory function."""

    def test_create_uia_tools(self):
        """Test that all tools are created."""
        tools = create_uia_tools()
        
        assert "get_active_window_elements" in tools
        assert "find_element" in tools
        assert "number_elements" in tools
        assert "get_element_by_number" in tools
        
        assert callable(tools["get_active_window_elements"])
        assert callable(tools["find_element"])
        assert callable(tools["number_elements"])
        assert callable(tools["get_element_by_number"])