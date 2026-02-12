"""
Content Search Skill
Search for text content inside files (grep-like functionality)
"""
from typing import Dict, Any, List
from pathlib import Path
import re
from loguru import logger


class ContentSearcherSkill:
    """Search file contents"""
    
    def __init__(self):
        """Initialize content searcher"""
        self.max_file_size = 10 * 1024 * 1024  # 10MB
        self.safe_extensions = {
            '.txt', '.py', '.js', '.json', '.md', '.html', '.css', '.xml',
            '.yaml', '.yml', '.csv', '.log', '.sh', '.sql', '.java', '.cpp',
            '.c', '.h', '.rs', '.go', '.rb', '.php', '.ts', '.jsx', '.vue'
        }
        logger.info("ContentSearcherSkill initialized")
    
    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Search file contents
        
        Args:
            search_term: Text to search for
            location: Directory to search in
            file_pattern: File pattern (*.py, *.txt, etc.)
            case_sensitive: Case-sensitive search
            regex: Treat search_term as regex
            max_results: Maximum files to return
            
        Returns:
            Files containing the search term with context
        """
        try:
            search_term = args.get("search_term", "")
            location = args.get("location", str(Path.home() / "Documents"))
            file_pattern = args.get("file_pattern", "*")
            case_sensitive = args.get("case_sensitive", False)
            use_regex = args.get("regex", False)
            max_results = args.get("max_results", 50)
            
            if not search_term:
                return {"success": False, "error": "No search term provided"}
            
            search_path = Path(location).expanduser()
            if not search_path.exists():
                return {"success": False, "error": f"Location not found: {location}"}
            
            # Compile search pattern
            if use_regex:
                flags = 0 if case_sensitive else re.IGNORECASE
                pattern = re.compile(search_term, flags)
            else:
                search_lower = search_term if case_sensitive else search_term.lower()
            
            results = []
            for file_path in search_path.rglob(file_pattern):
                if not file_path.is_file():
                    continue
                
                if file_path.suffix.lower() not in self.safe_extensions:
                    continue
                
                if file_path.stat().st_size > self.max_file_size:
                    continue
                
                try:
                    content = file_path.read_text(encoding='utf-8', errors='ignore')
                    lines = content.splitlines()
                    
                    matches = []
                    for line_num, line in enumerate(lines, 1):
                        line_to_search = line if case_sensitive else line.lower()
                        
                        if use_regex:
                            if pattern.search(line):
                                matches.append({
                                    "line": line_num,
                                    "content": line.strip(),
                                    "context_before": lines[max(0, line_num-2):line_num-1],
                                    "context_after": lines[line_num:min(len(lines), line_num+2)]
                                })
                        else:
                            if search_lower in line_to_search:
                                matches.append({
                                    "line": line_num,
                                    "content": line.strip()
                                })
                        
                        if len(matches) >= 10:  # Limit matches per file
                            break
                    
                    if matches:
                        results.append({
                            "file": str(file_path),
                            "name": file_path.name,
                            "matches": matches,
                            "match_count": len(matches)
                        })
                    
                    if len(results) >= max_results:
                        break
                
                except (UnicodeDecodeError, PermissionError):
                    continue
            
            return {
                "success": True,
                "action": "content_search",
                "search_term": search_term,
                "results": results,
                "files_matched": len(results)
            }
        
        except Exception as e:
            logger.error(f"Content search error: {str(e)}")
            return {"success": False, "error": str(e)}


# Global instance
content_searcher_skill = ContentSearcherSkill()