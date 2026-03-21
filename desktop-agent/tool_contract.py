"""
Canonical desktop tool contract helpers.

All host-side desktop tools should normalize into this structure so the backend
can plan, verify, and recover consistently without guessing per-tool payloads.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


def _infer_error_code(error: str) -> str:
    normalized = (error or "").lower()
    if not normalized:
        return "unknown_error"
    if "timeout" in normalized:
        return "timeout"
    if "connect" in normalized or "refused" in normalized or "unreachable" in normalized:
        return "connection_failed"
    if "not found" in normalized:
        return "not_found"
    if "permission" in normalized or "denied" in normalized:
        return "permission_denied"
    if "blocked" in normalized:
        return "blocked"
    if "validation" in normalized or "invalid" in normalized:
        return "validation_failed"
    if "verification" in normalized:
        return "verification_failed"
    return "execution_failed"


def _infer_retryable(error_code: str, error: str) -> bool:
    normalized = (error or "").lower()
    return error_code in {
        "timeout",
        "connection_failed",
        "verification_failed",
    } or any(keyword in normalized for keyword in ("busy", "temporarily", "retry"))


def _observation_source(result: Any, response: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(result, dict):
        return result
    payload = response.get("output")
    return payload if isinstance(payload, dict) else {}


def _default_observed_state(result: Any, response: Dict[str, Any]) -> Dict[str, Any]:
    source = _observation_source(result, response)
    if not source:
        return {}

    excluded = {
        "content",
        "text",
        "stdout",
        "stderr",
        "image_base64",
        "words",
        "windows",
        "processes",
        "matches",
    }
    return {
        key: value
        for key, value in source.items()
        if key not in excluded and value not in (None, "", [], {})
    }


def _default_evidence(result: Any, response: Dict[str, Any]) -> List[Dict[str, Any]]:
    source = _observation_source(result, response)
    evidence: List[Dict[str, Any]] = []

    if not isinstance(source, dict):
        return evidence

    if source.get("image_base64"):
        evidence.append(
            {
                "type": "screenshot",
                "summary": "Screenshot evidence captured.",
                "image_base64": source.get("image_base64"),
            }
        )

    if source.get("text"):
        text = str(source.get("text", ""))
        evidence.append(
            {
                "type": "ocr_text",
                "summary": text[:200],
                "text_excerpt": text[:1000],
            }
        )

    windows = source.get("windows")
    if isinstance(windows, list) and windows:
        evidence.append(
            {
                "type": "window_list",
                "count": len(windows),
                "titles": [str(window.get("title", ""))[:120] for window in windows[:10] if isinstance(window, dict)],
            }
        )

    processes = source.get("processes")
    if isinstance(processes, list) and processes:
        evidence.append(
            {
                "type": "process_list",
                "count": len(processes),
                "names": [str(process.get("name", ""))[:80] for process in processes[:10] if isinstance(process, dict)],
            }
        )

    matches = source.get("matches")
    if isinstance(matches, list):
        evidence.append(
            {
                "type": "search_results",
                "count": len(matches),
                "paths": [
                    str(match.get("path", ""))[:240]
                    for match in matches[:10]
                    if isinstance(match, dict)
                ],
            }
        )

    if source.get("path") or source.get("filepath"):
        evidence.append(
            {
                "type": "path",
                "path": source.get("path") or source.get("filepath"),
            }
        )

    if source.get("stdout"):
        evidence.append(
            {
                "type": "stdout",
                "summary": str(source.get("stdout", ""))[:500],
            }
        )

    if source.get("stderr"):
        evidence.append(
            {
                "type": "stderr",
                "summary": str(source.get("stderr", ""))[:500],
            }
        )

    return evidence


def normalize_tool_response(tool_name: str, response: Any) -> Dict[str, Any]:
    """Normalize legacy or ad-hoc tool responses into the canonical contract."""
    if not isinstance(response, dict):
        response = {
            "success": response is not None,
            "result": response,
            "message": "",
            "error": None if response is not None else "Tool returned no result",
        }

    success = bool(response.get("success", False))
    result = response.get("result")
    message = response.get("message", "") or ""
    error = response.get("error")

    error_code = response.get("error_code")
    if not error_code:
        error_code = "ok" if success else _infer_error_code(error or message)

    retryable = bool(
        response.get("retryable", False if success else _infer_retryable(error_code, error or message))
    )

    observed_state = response.get("observed_state")
    if not isinstance(observed_state, dict):
        observed_state = _default_observed_state(result, response)

    evidence = response.get("evidence")
    if isinstance(evidence, dict):
        evidence = [evidence]
    if not isinstance(evidence, list):
        evidence = _default_evidence(result, response)

    canonical = {
        "tool_name": tool_name,
        "success": success,
        "result": result,
        "message": message,
        "error": error,
        "error_code": error_code,
        "retryable": retryable,
        "observed_state": observed_state,
        "evidence": evidence,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return canonical

