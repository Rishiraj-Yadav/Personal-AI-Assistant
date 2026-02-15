"""
Code Specialist Agent - COMPLETE MULTI-FILE VERSION
Generates complete project structures with proper organization
Like v0.dev, Cursor AI, and Copilot
"""
import os
import re
from typing import Dict, Any, List, Optional
from loguru import logger
import google.generativeai as genai


class CodeSpecialistAgent:
    """
    Code Specialist - Generates complete projects with proper structure
    Uses Google Gemini Pro for code generation
    """
    
    def __init__(self):
        """Initialize code specialist with Gemini Pro"""
        api_key = os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            logger.warning("⚠️ GOOGLE_API_KEY not set")
        
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash')
        logger.info("✅ Code Specialist initialized with Gemini Pro")
    
    async def generate_code(
        self, 
        description: str,
        context: Optional[str] = None,
        iteration: int = 1,
        previous_error: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate complete project with proper structure
        
        Returns multi-file project instead of single file
        """
        
        if iteration == 1:
            # First iteration: Generate complete project
            prompt = self._create_generation_prompt(description, context)
        else:
            # Fix iteration: Debug and fix errors
            prompt = self._create_fix_prompt(description, previous_error, context)
        
        try:
            logger.info(f"🎨 Generating code (iteration {iteration})...")
            response = self.model.generate_content(prompt)
            code_output = response.text.strip()
            
            # Parse multi-file output
            parse_result = self._parse_multi_file_output(code_output)
            
            if not parse_result["files"]:
                # Fallback to single file if parsing fails
                logger.warning("⚠️ Multi-file parsing failed, treating as single file")
                return self._handle_single_file(code_output, description)
            
            # Detect project type and configuration
            project_config = self._detect_project_config(parse_result["files"])
            
            logger.info(f"✅ Generated {len(parse_result['files'])} files")
            logger.info(f"📦 Project type: {project_config['project_type']}")
            
            return {
                "success": True,
                "files": parse_result["files"],
                "structure": parse_result["structure"],
                "main_file": parse_result["main_file"],
                "project_type": project_config["project_type"],
                "language": project_config["language"],
                "is_server": project_config["is_server"],
                "start_command": project_config["start_command"],
                "install_command": project_config["install_command"],
                "port": project_config["port"],
                "dependencies": project_config["dependencies"],
                "raw_output": code_output
            }
        
        except Exception as e:
            logger.error(f"❌ Code generation error: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "files": {},
                "raw_output": ""
            }
    
    def _create_generation_prompt(self, description: str, context: Optional[str]) -> str:
        """Create prompt for initial code generation"""
        
        return f"""You are an expert software engineer. Generate a COMPLETE, PRODUCTION-READY project based on the user's request.

User Request: "{description}"

CRITICAL INSTRUCTIONS:
1. Generate a COMPLETE project with PROPER FOLDER STRUCTURE
2. Create MULTIPLE files, not a single monolithic file
3. Follow best practices for the technology stack
4. Include ALL necessary configuration files (package.json, requirements.txt, etc.)
5. Make it READY TO RUN - no placeholders or TODOs

OUTPUT FORMAT (STRICTLY FOLLOW):

PROJECT_TYPE: [react/flask/express/fastapi/django/nextjs/etc]
PROJECT_NAME: [project_folder_name]
DESCRIPTION: [Brief description of the project]

FILES:
--- path/to/file1.ext ---
[Complete file content]

--- path/to/file2.ext ---
[Complete file content]

--- path/to/file3.ext ---
[Complete file content]

STRUCTURE:
[ASCII tree of project structure]

SETUP:
[Installation/setup commands]

RUN:
[Command to start the project]

PORT:
[Port number where server runs, or NONE if not a server]

EXAMPLES:

Example 1 - React App:
PROJECT_TYPE: react
PROJECT_NAME: todo-app
DESCRIPTION: Simple todo list application

FILES:
--- package.json ---
{{
  "name": "todo-app",
  "version": "1.0.0",
  "scripts": {{
    "start": "react-scripts start",
    "build": "react-scripts build"
  }},
  "dependencies": {{
    "react": "^18.0.0",
    "react-dom": "^18.0.0",
    "react-scripts": "5.0.1"
  }}
}}

--- public/index.html ---
<!DOCTYPE html>
<html>
<head><title>Todo App</title></head>
<body><div id="root"></div></body>
</html>

--- src/App.js ---
import React, {{ useState }} from 'react';

function App() {{
  const [todos, setTodos] = useState([]);
  // ... complete implementation
  return <div>...</div>;
}}

export default App;

--- src/index.js ---
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);

STRUCTURE:
todo-app/
├── package.json
├── public/
│   └── index.html
└── src/
    ├── App.js
    └── index.js

SETUP:
npm install

RUN:
npm start

PORT:
5555

Example 2 - Flask API:
PROJECT_TYPE: flask
PROJECT_NAME: api-server
DESCRIPTION: REST API with authentication

FILES:
--- requirements.txt ---
flask==3.0.0
flask-cors==4.0.0
python-dotenv==1.0.0

--- app.py ---
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/')
def home():
    return jsonify({{"message": "API is running"}})

@app.route('/api/data')
def get_data():
    return jsonify({{"data": [1, 2, 3]}})

if __name__ == '__main__':
    app.run(debug=True, port=5000)

--- config.py ---
import os

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key')
    DEBUG = True

STRUCTURE:
api-server/
├── requirements.txt
├── app.py
└── config.py

SETUP:
pip install -r requirements.txt

RUN:
python app.py

PORT:
5000

NOW GENERATE THE COMPLETE PROJECT FOR THE USER'S REQUEST ABOVE.
Use the EXACT format shown in examples.
Make it production-ready and complete - no placeholders!"""
    
    def _create_fix_prompt(
        self, 
        description: str, 
        error: str, 
        previous_code: Optional[str]
    ) -> str:
        """Create prompt for fixing code based on error"""
        
        return f"""You are debugging code that failed to run. Fix ALL errors and return the COMPLETE corrected project.

Original Request: "{description}"

Error Encountered:
{error}

Previous Code:
{previous_code[:2000] if previous_code else "Not available"}

INSTRUCTIONS:
1. Identify the root cause of the error
2. Fix ALL issues (imports, syntax, logic, dependencies)
3. Return the COMPLETE fixed project using the same multi-file format
4. Ensure it will run without errors

Use the EXACT format from before:
PROJECT_TYPE: ...
FILES:
--- path/to/file ---
[fixed content]

Make sure the fixed code is PRODUCTION-READY and ERROR-FREE."""
    
    def _parse_multi_file_output(self, output: str) -> Dict[str, Any]:
        """
        Parse multi-file code output
        
        Expected format:
        FILES:
        --- path/to/file ---
        content
        --- another/file ---
        content
        """
        
        files = {}
        structure = {}
        main_file = None
        
        # Extract files section
        files_match = re.search(r'FILES:(.*?)(?:STRUCTURE:|SETUP:|RUN:|$)', output, re.DOTALL | re.IGNORECASE)
        
        if not files_match:
            logger.warning("No FILES section found")
            return {
                "files": {},
                "structure": {},
                "main_file": None
            }
        
        files_section = files_match.group(1)
        
        # Parse individual files
        # Pattern: --- filepath ---
        file_pattern = r'---\s*([^\n]+?)\s*---\n(.*?)(?=---|\Z)'
        matches = re.findall(file_pattern, files_section, re.DOTALL)
        
        for filepath, content in matches:
            filepath = filepath.strip()
            content = content.strip()
            
            # Clean up filepath
            filepath = filepath.replace('\\', '/')
            
            # Store file
            files[filepath] = content
            
            # Determine main file
            if main_file is None:
                if any(name in filepath.lower() for name in ['app.py', 'main.py', 'index.js', 'app.js', 'server.js']):
                    main_file = filepath
        
        # If no main file found, use first file
        if main_file is None and files:
            main_file = list(files.keys())[0]
        
        # Build structure tree
        structure = self._build_file_tree(list(files.keys()))
        
        logger.info(f"📁 Parsed {len(files)} files")
        return {
            "files": files,
            "structure": structure,
            "main_file": main_file
        }
    
    def _build_file_tree(self, filepaths: List[str]) -> Dict:
        """Build tree structure from file paths"""
        tree = {}
        
        for filepath in filepaths:
            parts = filepath.split('/')
            current = tree
            
            for i, part in enumerate(parts):
                if i == len(parts) - 1:
                    # File
                    current[part] = "file"
                else:
                    # Directory
                    if part not in current:
                        current[part] = {}
                    current = current[part]
        
        return tree
    
    def _detect_project_config(self, files: Dict[str, str]) -> Dict[str, Any]:
        """
        Detect project type and configuration from files
        """
        
        filenames = set(files.keys())
        
        # React
        if 'package.json' in filenames:
            package_json = files['package.json']
            
            if 'react' in package_json.lower():
                return {
                    "project_type": "react",
                    "language": "javascript",
                    "is_server": True,
                    "start_command": "npm start",
                    "install_command": "npm install",
                    "port": 5555,
                    "dependencies": ["react", "react-dom"]
                }
            
            if 'express' in package_json.lower():
                return {
                    "project_type": "express",
                    "language": "javascript",
                    "is_server": True,
                    "start_command": "node index.js",
                    "install_command": "npm install",
                    "port": 5555,
                    "dependencies": ["express"]
                }
            
            # Default Node.js
            return {
                "project_type": "node",
                "language": "javascript",
                "is_server": False,
                "start_command": "node index.js",
                "install_command": "npm install",
                "port": None,
                "dependencies": []
            }
        
        # Flask
        if any('flask' in files[f].lower() for f in files):
            return {
                "project_type": "flask",
                "language": "python",
                "is_server": True,
                "start_command": "python app.py",
                "install_command": "pip install -r requirements.txt",
                "port": 5000,
                "dependencies": ["flask"]
            }
        
        # FastAPI
        if any('fastapi' in files[f].lower() for f in files):
            return {
                "project_type": "fastapi",
                "language": "python",
                "is_server": True,
                "start_command": "uvicorn main:app --port 8100",
                "install_command": "pip install -r requirements.txt",
                "port": 8100,
                "dependencies": ["fastapi", "uvicorn"]
            }
        
        # Python script
        if any(f.endswith('.py') for f in filenames):
            main_file = next((f for f in filenames if f in ['main.py', 'app.py']), list(filenames)[0])
            return {
                "project_type": "python",
                "language": "python",
                "is_server": False,
                "start_command": f"python {main_file}",
                "install_command": None,
                "port": None,
                "dependencies": []
            }
        
        # JavaScript
        if any(f.endswith('.js') for f in filenames):
            return {
                "project_type": "javascript",
                "language": "javascript",
                "is_server": False,
                "start_command": "node index.js",
                "install_command": None,
                "port": None,
                "dependencies": []
            }
        
        # Default
        return {
            "project_type": "unknown",
            "language": "unknown",
            "is_server": False,
            "start_command": None,
            "install_command": None,
            "port": None,
            "dependencies": []
        }
    
    def _handle_single_file(self, code_output: str, description: str) -> Dict[str, Any]:
        """Fallback for single-file code generation"""
        
        # Detect language
        language = "python"
        if "```javascript" in code_output or "```js" in code_output:
            language = "javascript"
        elif "```typescript" in code_output:
            language = "typescript"
        elif "```python" in code_output or "```py" in code_output:
            language = "python"
        
        # Extract code from markdown
        code_match = re.search(r'```(?:\w+)?\n(.*?)\n```', code_output, re.DOTALL)
        code = code_match.group(1) if code_match else code_output
        
        # Create single file
        filename = f"main.{language[:2] if language != 'javascript' else 'js'}"
        
        return {
            "success": True,
            "files": {filename: code},
            "structure": {filename: "file"},
            "main_file": filename,
            "project_type": language,
            "language": language,
            "is_server": False,
            "start_command": f"{'python' if language == 'python' else 'node'} {filename}",
            "install_command": None,
            "port": None,
            "dependencies": [],
            "raw_output": code_output
        }


# Global instance
code_specialist = CodeSpecialistAgent()