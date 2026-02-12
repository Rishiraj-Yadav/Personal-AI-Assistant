"""
Git Manager Skill
Handles git operations for projects
"""
import os
import json
import sys
import subprocess
from pathlib import Path


def main():
    """Execute git operations"""
    try:
        params_json = os.environ.get("SKILL_PARAMS", "{}")
        params = json.loads(params_json)
        
        action = params.get("action", "")
        repo_path = params.get("repository_path", "")
        message = params.get("message", "")
        branch = params.get("branch", "main")
        
        if not action:
            print(json.dumps({
                "success": False,
                "error": "No action specified"
            }))
            sys.exit(1)
        
        if not repo_path:
            print(json.dumps({
                "success": False,
                "error": "No repository path specified"
            }))
            sys.exit(1)
        
        # Ensure path exists
        repo_path = Path(repo_path)
        if not repo_path.exists():
            repo_path.mkdir(parents=True, exist_ok=True)
        
        # Execute git command based on action
        result = execute_git_action(action, repo_path, message, branch)
        
        print(json.dumps(result, indent=2))
    
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": str(e)
        }))
        sys.exit(1)


def execute_git_action(action: str, repo_path: Path, message: str, branch: str):
    """Execute specific git action"""
    
    try:
        os.chdir(repo_path)
        
        if action == "init":
            # Initialize git repository
            subprocess.run(["git", "init"], check=True, capture_output=True)
            subprocess.run(["git", "branch", "-M", branch], check=True, capture_output=True)
            
            return {
                "success": True,
                "action": "init",
                "message": f"Initialized git repository with branch '{branch}'",
                "repository_path": str(repo_path)
            }
        
        elif action == "status":
            # Get git status
            result = subprocess.run(
                ["git", "status", "--short"],
                check=True,
                capture_output=True,
                text=True
            )
            
            return {
                "success": True,
                "action": "status",
                "status": result.stdout,
                "repository_path": str(repo_path)
            }
        
        elif action == "add":
            # Stage all changes
            subprocess.run(["git", "add", "."], check=True, capture_output=True)
            
            return {
                "success": True,
                "action": "add",
                "message": "Staged all changes",
                "repository_path": str(repo_path)
            }
        
        elif action == "commit":
            # Commit changes
            if not message:
                message = "Auto-commit by OpenClaw Agent"
            
            subprocess.run(
                ["git", "commit", "-m", message],
                check=True,
                capture_output=True
            )
            
            return {
                "success": True,
                "action": "commit",
                "message": f"Committed with message: {message}",
                "repository_path": str(repo_path)
            }
        
        elif action == "branch":
            # Create new branch
            if not branch:
                return {
                    "success": False,
                    "error": "No branch name specified"
                }
            
            subprocess.run(
                ["git", "checkout", "-b", branch],
                check=True,
                capture_output=True
            )
            
            return {
                "success": True,
                "action": "branch",
                "message": f"Created and switched to branch '{branch}'",
                "repository_path": str(repo_path)
            }
        
        elif action == "log":
            # Get commit history
            result = subprocess.run(
                ["git", "log", "--oneline", "-10"],
                check=True,
                capture_output=True,
                text=True
            )
            
            return {
                "success": True,
                "action": "log",
                "commits": result.stdout,
                "repository_path": str(repo_path)
            }
        
        else:
            return {
                "success": False,
                "error": f"Unknown action: {action}"
            }
    
    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "error": f"Git command failed: {e.stderr.decode() if e.stderr else str(e)}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


if __name__ == "__main__":
    main()