"""
Project Creator Skill
Creates complete project structures with templates
"""
import os
import json
import sys
import asyncio
from pathlib import Path
from typing import Dict, Any, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))


# Project templates
FLASK_API_TEMPLATE = {
    "app.py": '''"""
Flask REST API
"""
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"}), 200

@app.route('/api/hello', methods=['GET'])
def hello():
    name = request.args.get('name', 'World')
    return jsonify({"message": f"Hello, {name}!"}), 200

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
''',
    "requirements.txt": '''Flask==3.0.0
Flask-CORS==4.0.0
python-dotenv==1.0.0
''',
    ".env.example": '''FLASK_ENV=development
SECRET_KEY=your-secret-key-here
''',
    "README.md": '''# Flask REST API

## Setup
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\\Scripts\\activate
pip install -r requirements.txt
```

## Run
```bash
python app.py
```

## Test
```bash
curl http://localhost:5000/health
curl http://localhost:5000/api/hello?name=OpenClaw
```
''',
    ".gitignore": '''venv/
__pycache__/
*.pyc
.env
.DS_Store
'''
}

FASTAPI_TEMPLATE = {
    "main.py": '''"""
FastAPI Application
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="FastAPI Service")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Item(BaseModel):
    name: str
    description: str = None

@app.get("/")
def read_root():
    return {"message": "Welcome to FastAPI"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.post("/items/")
def create_item(item: Item):
    return {"item": item, "status": "created"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
''',
    "requirements.txt": '''fastapi==0.109.0
uvicorn[standard]==0.27.0
pydantic==2.5.3
python-dotenv==1.0.0
''',
    "README.md": '''# FastAPI Service

## Setup
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run
```bash
uvicorn main:app --reload
```

## Docs
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
''',
    ".gitignore": '''venv/
__pycache__/
*.pyc
.env
'''
}

REACT_APP_TEMPLATE = {
    "package.json": '''{
  "name": "react-app",
  "version": "0.1.0",
  "private": true,
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-scripts": "5.0.1"
  },
  "scripts": {
    "start": "react-scripts start",
    "build": "react-scripts build",
    "test": "react-scripts test"
  }
}''',
    "src/App.js": '''import React, { useState } from 'react';
import './App.css';

function App() {
  const [count, setCount] = useState(0);

  return (
    <div className="App">
      <header className="App-header">
        <h1>React App</h1>
        <p>Count: {count}</p>
        <button onClick={() => setCount(count + 1)}>
          Increment
        </button>
      </header>
    </div>
  );
}

export default App;
''',
    "src/index.js": '''import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
''',
    "public/index.html": '''<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>React App</title>
  </head>
  <body>
    <div id="root"></div>
  </body>
</html>
''',
    "README.md": '''# React Application

## Setup
```bash
npm install
```

## Run
```bash
npm start
```

App will open at http://localhost:3000
'''
}


async def main():
    """Create complete project structure"""
    try:
        params_json = os.environ.get("SKILL_PARAMS", "{}")
        params = json.loads(params_json)
        
        project_type = params.get("project_type", "")
        project_name = params.get("project_name", "my-project")
        project_path = params.get("project_path", "/workspace")
        
        # Get template
        template = get_template(project_type)
        
        if not template:
            print(json.dumps({
                "success": False,
                "error": f"Unknown project type: {project_type}"
            }))
            sys.exit(1)
        
        # Create project structure
        full_path = os.path.join(project_path, project_name)
        files_created = []
        
        for filepath, content in template.items():
            file_full_path = os.path.join(full_path, filepath)
            
            # Create directories if needed
            os.makedirs(os.path.dirname(file_full_path), exist_ok=True)
            
            # Write file
            with open(file_full_path, 'w') as f:
                f.write(content)
            
            files_created.append(filepath)
        
        output = {
            "success": True,
            "project_name": project_name,
            "project_path": full_path,
            "project_type": project_type,
            "files_created": files_created,
            "next_steps": get_next_steps(project_type, project_name)
        }
        
        print(json.dumps(output, indent=2))
    
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": str(e)
        }))
        sys.exit(1)


def get_template(project_type: str) -> Dict[str, str]:
    """Get project template by type"""
    templates = {
        "flask": FLASK_API_TEMPLATE,
        "flask-api": FLASK_API_TEMPLATE,
        "fastapi": FASTAPI_TEMPLATE,
        "fastapi-service": FASTAPI_TEMPLATE,
        "react": REACT_APP_TEMPLATE,
        "react-app": REACT_APP_TEMPLATE
    }
    return templates.get(project_type.lower(), None)


def get_next_steps(project_type: str, project_name: str) -> List[str]:
    """Get next steps for the user"""
    
    if "flask" in project_type.lower():
        return [
            f"cd {project_name}",
            "python -m venv venv",
            "source venv/bin/activate  # Windows: venv\\Scripts\\activate",
            "pip install -r requirements.txt",
            "python app.py",
            "Open http://localhost:5000/health"
        ]
    
    elif "fastapi" in project_type.lower():
        return [
            f"cd {project_name}",
            "python -m venv venv",
            "source venv/bin/activate",
            "pip install -r requirements.txt",
            "uvicorn main:app --reload",
            "Open http://localhost:8000/docs"
        ]
    
    elif "react" in project_type.lower():
        return [
            f"cd {project_name}",
            "npm install",
            "npm start",
            "Open http://localhost:3000"
        ]
    
    return [f"cd {project_name}", "Check README.md for instructions"]


if __name__ == "__main__":
    asyncio.run(main())