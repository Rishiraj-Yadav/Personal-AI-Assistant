"""
Response Sanitizer - Phase 3
============================

Sanitizes and formats responses for the frontend.
"""

import re
from typing import Optional
from loguru import logger


class ResponseSanitizer:
    """
    Sanitizes LLM responses for clean output.
    
    - Removes thinking tags
    - Cleans up formatting
    - Handles markdown properly
    """
    
    # Patterns to remove
    REMOVE_PATTERNS = [
        r'<thinking>.*?</thinking>',
        r'<internal>.*?</internal>',
        r'\[THINKING\].*?\[/THINKING\]',
        r'```json\s*\{[^}]+\}\s*```',  # Remove raw JSON blocks
    ]
    
    def __init__(self):
        self._patterns = [
            re.compile(p, re.DOTALL | re.IGNORECASE)
            for p in self.REMOVE_PATTERNS
        ]
        logger.info("✅ ResponseSanitizer initialized")
    
    def sanitize(self, text: str) -> str:
        """
        Sanitize response text.
        
        Args:
            text: Raw response text
            
        Returns:
            Cleaned response text
        """
        if not text:
            return ""
        
        result = text
        
        # Remove unwanted patterns
        for pattern in self._patterns:
            result = pattern.sub('', result)
        
        # Clean up excessive whitespace
        result = re.sub(r'\n{3,}', '\n\n', result)
        result = result.strip()
        
        return result
    
    def format_for_display(self, text: str, max_length: Optional[int] = None) -> str:
        """
        Format text for display.
        
        Args:
            text: Text to format
            max_length: Optional maximum length
            
        Returns:
            Formatted text
        """
        result = self.sanitize(text)
        
        if max_length and len(result) > max_length:
            result = result[:max_length - 3] + "..."
        
        return result


# Global instance
response_sanitizer = ResponseSanitizer()
