"""
Path Validator

Prevents access to sensitive system paths.
Protects against directory traversal and system damage.

Part of Phase 2: SafeExecutor Security
"""

import re
import os
from typing import Dict, Any, List, Optional
from pathlib import Path
from dataclasses import dataclass
from loguru import logger


@dataclass
class PathValidationResult:
    """Result of path validation"""
    allowed: bool
    reason: str
    normalized_path: Optional[str] = None
    matched_rule: Optional[str] = None


class PathValidator:
    """
    Validates file paths for safety.

    Blocks access to sensitive system directories.
    Prevents directory traversal attacks.
    """

    # Paths that should never be accessed
    BLOCKED_PATHS_WINDOWS = [
        r"^[C-Z]:\\Windows",
        r"^[C-Z]:\\Program Files",
        r"^[C-Z]:\\Program Files \(x86\)",
        r"^[C-Z]:\\ProgramData\\Microsoft",
        r"^[C-Z]:\\System32",
        r"^[C-Z]:\\SysWOW64",
        r"^[C-Z]:\\Recovery",
        r"^[C-Z]:\\Boot",
        r"^[C-Z]:\\\$Recycle\.Bin",
    ]

    BLOCKED_PATHS_UNIX = [
        r"^/etc",
        r"^/sys",
        r"^/proc",
        r"^/boot",
        r"^/dev",
        r"^/root",
        r"^/var/log",
        r"^/usr/bin",
        r"^/usr/sbin",
        r"^/sbin",
        r"^/bin",
    ]

    BLOCKED_PATHS_MACOS = [
        r"^/Library/System",
        r"^/System",
        r"^/private/var/db",
        r"^/Volumes/.*/(System|Library)",
    ]

    # User-sensitive directories (blocked on all platforms)
    BLOCKED_USER_PATHS = [
        r".*[/\\]\.ssh",
        r".*[/\\]\.aws",
        r".*[/\\]\.kube",
        r".*[/\\]\.gnupg",
        r".*[/\\]\.config[/\\]gcloud",
        r".*[/\\]\.azure",
        r".*\.env$",
        r".*\.pem$",
        r".*\.key$",
        r".*credentials.*",
        r".*secrets.*",
    ]

    def __init__(
        self,
        allowed_base_paths: Optional[List[str]] = None,
        platform: Optional[str] = None,
        strict_mode: bool = True
    ):
        """
        Initialize validator.

        Args:
            allowed_base_paths: Whitelist of paths where operations are allowed
                               (defaults to user home and temp directories)
            platform: Operating system ('windows', 'linux', 'darwin')
                     Auto-detected if None
            strict_mode: If True, only allow paths within allowed_base_paths
        """
        self.platform = platform or self._detect_platform()
        self.strict_mode = strict_mode

        # Build blocked paths list based on platform
        self.blocked_patterns = self._build_blocked_patterns()

        # Set allowed base paths
        if allowed_base_paths:
            self.allowed_base_paths = [str(Path(p).resolve()) for p in allowed_base_paths]
        else:
            self.allowed_base_paths = self._default_allowed_paths()

    def _detect_platform(self) -> str:
        """Detect current platform"""
        import platform
        system = platform.system().lower()
        if system == "windows":
            return "windows"
        elif system == "darwin":
            return "darwin"
        else:
            return "linux"

    def _build_blocked_patterns(self) -> List[str]:
        """Build list of blocked path patterns"""
        patterns = list(self.BLOCKED_USER_PATHS)

        if self.platform == "windows":
            patterns.extend(self.BLOCKED_PATHS_WINDOWS)
        elif self.platform == "darwin":
            patterns.extend(self.BLOCKED_PATHS_UNIX)
            patterns.extend(self.BLOCKED_PATHS_MACOS)
        else:  # linux
            patterns.extend(self.BLOCKED_PATHS_UNIX)

        return patterns

    def _default_allowed_paths(self) -> List[str]:
        """Get default allowed paths based on platform"""
        paths = []

        # User home directory
        home = str(Path.home().resolve())
        paths.append(home)

        # Temp directories
        import tempfile
        temp = tempfile.gettempdir()
        paths.append(str(Path(temp).resolve()))

        # Current working directory
        cwd = os.getcwd()
        paths.append(str(Path(cwd).resolve()))

        return paths

    def validate(
        self,
        path: str,
        operation: str = "read"
    ) -> PathValidationResult:
        """
        Validate a file path.

        Args:
            path: File path to validate
            operation: Type of operation ('read', 'write', 'delete', 'execute')

        Returns:
            PathValidationResult with validation outcome
        """
        try:
            # Normalize path
            try:
                normalized = str(Path(path).resolve())
            except Exception:
                return PathValidationResult(
                    allowed=False,
                    reason=f"Invalid path format: {path}"
                )

            # Check for directory traversal
            if ".." in path:
                logger.warning(f"🚫 Directory traversal detected: {path}")
                return PathValidationResult(
                    allowed=False,
                    reason="Directory traversal (..) not allowed",
                    normalized_path=normalized,
                    matched_rule="directory_traversal"
                )

            # Check against blocked patterns
            for pattern in self.blocked_patterns:
                if re.search(pattern, normalized, re.IGNORECASE):
                    logger.warning(f"🚫 Blocked path pattern: {normalized} (matches {pattern})")
                    return PathValidationResult(
                        allowed=False,
                        reason=f"Access to this path is blocked for security",
                        normalized_path=normalized,
                        matched_rule=pattern
                    )

            # Strict mode: check if within allowed base paths
            if self.strict_mode:
                in_allowed = False
                for allowed_base in self.allowed_base_paths:
                    if normalized.startswith(allowed_base):
                        in_allowed = True
                        break

                if not in_allowed:
                    logger.warning(f"⚠️ Path outside allowed directories: {normalized}")
                    return PathValidationResult(
                        allowed=False,
                        reason=f"Path is outside allowed directories",
                        normalized_path=normalized,
                        matched_rule="outside_allowed_base"
                    )

            # Additional checks for write/delete operations
            if operation in ["write", "delete"]:
                # Check for system file extensions
                dangerous_extensions = [".exe", ".dll", ".sys", ".bat", ".cmd", ".ps1", ".vbs"]
                ext = Path(normalized).suffix.lower()
                if ext in dangerous_extensions:
                    logger.warning(f"⚠️ Dangerous file extension: {ext}")
                    return PathValidationResult(
                        allowed=False,
                        reason=f"Cannot {operation} files with {ext} extension",
                        normalized_path=normalized,
                        matched_rule="dangerous_extension"
                    )

            # All checks passed
            return PathValidationResult(
                allowed=True,
                reason=f"Path '{path}' is safe for {operation}",
                normalized_path=normalized
            )

        except Exception as e:
            logger.error(f"❌ Error validating path: {e}")
            return PathValidationResult(
                allowed=False,
                reason=f"Path validation error: {str(e)}"
            )

    def add_allowed_path(self, path: str):
        """Add a path to the allowed list"""
        normalized = str(Path(path).resolve())
        if normalized not in self.allowed_base_paths:
            self.allowed_base_paths.append(normalized)
            logger.info(f"📝 Added allowed path: {normalized}")

    def add_blocked_pattern(self, pattern: str):
        """Add a pattern to the blocked list"""
        self.blocked_patterns.append(pattern)
        logger.info(f"🚫 Added blocked pattern: {pattern}")


# Global instance
path_validator = PathValidator()
