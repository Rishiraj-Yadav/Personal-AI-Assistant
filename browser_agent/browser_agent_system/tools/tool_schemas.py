"""
Tool schemas in Anthropic tool_use format.
The BrowserAgent uses these to let Claude call browser functions.
"""

BROWSER_TOOLS = [
    {
        "name": "navigate",
        "description": "Navigate the browser to a URL. Always use this first before any other action.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full URL to navigate to (must include https://)"
                }
            },
            "required": ["url"]
        }
    },
    {
        "name": "click",
        "description": "Click an element on the page using a CSS selector or visible text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector (e.g. '#submit-btn', '.login-form button') or visible text of element"
                },
                "description": {
                    "type": "string",
                    "description": "Human-readable description of what you're clicking (for logging)"
                }
            },
            "required": ["selector"]
        }
    },
    {
        "name": "type_text",
        "description": "Type text into an input field, textarea, or search box.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector of the input element"
                },
                "text": {
                    "type": "string",
                    "description": "Text to type into the field"
                },
                "clear_first": {
                    "type": "boolean",
                    "description": "Whether to clear the field before typing (default: true)",
                    "default": True
                }
            },
            "required": ["selector", "text"]
        }
    },
    {
        "name": "get_text",
        "description": "Get the visible text content from an element or the whole page. Use this to read page content, search results, articles, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector of element to read (default: 'body' for full page)",
                    "default": "body"
                }
            }
        }
    },
    {
        "name": "get_page_info",
        "description": "Get current page URL, title, and a summary of all interactive elements (inputs, buttons, links). Use this to understand what's on the page before interacting.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "screenshot",
        "description": "Take a screenshot of the current browser page. Returns base64 image data. Use when you need to visually verify something.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Optional file path to save screenshot (e.g. 'result.png'). If omitted, returns base64."
                }
            }
        }
    },
    {
        "name": "scroll",
        "description": "Scroll the page up or down.",
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["up", "down"],
                    "description": "Direction to scroll"
                },
                "amount": {
                    "type": "integer",
                    "description": "Pixels to scroll (default: 300)",
                    "default": 300
                }
            },
            "required": ["direction"]
        }
    },
    {
        "name": "wait_for_element",
        "description": "Wait for an element to appear on the page. Useful after clicking buttons that trigger dynamic content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector to wait for"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Max wait time in milliseconds (default: 10000)",
                    "default": 10000
                }
            },
            "required": ["selector"]
        }
    },
    {
        "name": "extract_links",
        "description": "Extract all clickable links from the current page. Useful for navigating to sub-pages.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "execute_script",
        "description": "Run JavaScript code in the browser context. Use for advanced interactions the other tools can't handle.",
        "input_schema": {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "JavaScript code to execute. Use return statement for values."
                }
            },
            "required": ["script"]
        }
    },
    {
        "name": "select_option",
        "description": "Select an option from a <select> dropdown element.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector of the <select> element"
                },
                "value": {
                    "type": "string",
                    "description": "Value or label of the option to select"
                }
            },
            "required": ["selector", "value"]
        }
    },
    {
        "name": "press_key",
        "description": "Press a keyboard key (e.g. Enter to submit a form, Tab to move focus, Escape to close a modal).",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Key name: Enter, Tab, Escape, ArrowUp, ArrowDown, Backspace, etc."
                }
            },
            "required": ["key"]
        }
    },
    {
        "name": "go_back",
        "description": "Go back to the previous page in browser history.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_html",
        "description": "Get the raw HTML of an element. Useful for scraping structured data like tables, lists, or JSON embedded in HTML.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector (default: 'body')",
                    "default": "body"
                }
            }
        }
    }
]
