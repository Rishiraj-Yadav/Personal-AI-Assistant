#!/usr/bin/env python3
"""
Code Generator Skill
Generates code using LLM based on description
"""
import os
import json
import sys


def main():
    """Generate code from user description"""
    try:
        params_json = os.environ.get("SKILL_PARAMS", "{}")
        params = json.loads(params_json)
        
        description = params.get("description", "")
        language = params.get("language", "python")
        
        if not description:
            print(json.dumps({
                "success": False,
                "error": "No description provided"
            }))
            sys.exit(1)
        
        # Note: The actual LLM code generation happens in the agent orchestrator
        # This skill just validates parameters and prepares the request
        
        output = {
            "success": True,
            "description": description,
            "language": language,
            "message": f"Ready to generate {language} code for: {description}",
            "next_step": "LLM will generate code based on this description"
        }
        
        print(json.dumps(output, indent=2))
    
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": str(e)
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()








# """
# Code Generator Skill
# Generates code using LLM based on user description
# """
# import os
# import json
# import sys
# import asyncio
# from typing import Dict, Any

# sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))


# async def main():
#     """Generate code from user description"""
#     try:
#         # Get parameters
#         params_json = os.environ.get("SKILL_PARAMS", "{}")
#         params = json.loads(params_json)
        
#         description = params.get("description", "")
#         language = params.get("language", "python")
#         framework = params.get("framework", "")
#         include_tests = params.get("include_tests", False)
        
#         if not description:
#             print(json.dumps({
#                 "success": False,
#                 "error": "No description provided"
#             }))
#             sys.exit(1)
        
#         # Build detailed prompt for code generation
#         prompt = build_code_generation_prompt(
#             description, language, framework, include_tests
#         )
        
#         # Note: The actual LLM call happens in the agent orchestrator
#         # This skill prepares the prompt and validates parameters
        
#         output = {
#             "success": True,
#             "prompt": prompt,
#             "language": language,
#             "framework": framework,
#             "description": description,
#             "message": "Code generation prompt prepared. LLM will generate code."
#         }
        
#         print(json.dumps(output, indent=2))
    
#     except Exception as e:
#         print(json.dumps({
#             "success": False,
#             "error": str(e)
#         }))
#         sys.exit(1)


# def build_code_generation_prompt(
#     description: str,
#     language: str,
#     framework: str,
#     include_tests: bool
# ) -> str:
#     """Build detailed prompt for code generation"""
    
#     base_prompt = f"""Generate production-ready {language} code based on this description:

# {description}

# Requirements:
# - Language: {language}
# """
    
#     if framework:
#         base_prompt += f"- Framework: {framework}\n"
    
#     base_prompt += """- Clean, well-documented code
# - Follow best practices and conventions
# - Include error handling
# - Add docstrings/comments
# """
    
#     if include_tests:
#         base_prompt += "- Include unit tests\n"
    
#     base_prompt += """
# Return ONLY the code, no explanations.
# Format: Provide complete, runnable code.
# """
    
#     return base_prompt


# if __name__ == "__main__":
#     asyncio.run(main())