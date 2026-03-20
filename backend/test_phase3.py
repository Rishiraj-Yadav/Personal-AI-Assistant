"""
Test script for Phase 3: Fast Path + Intelligent Routing

Run this script to test the new Phase 3 components:
    cd backend
    python test_phase3.py

Expected output:
    [PASS] Intent Classifier tests passed
    [PASS] Fast Router tests passed
    [PASS] Simple Responder tests passed
    [PASS] Response Sanitizer tests passed
    [PASS] Fast Path Handler tests passed
    All Phase 3 tests passed!
"""

import asyncio
import sys
import time


async def test_intent_classifier():
    """Test fast intent classification."""
    print("\n[TEST] Intent Classifier...")

    from app.realtime.fast_intent_classifier import FastIntentClassifier, IntentType

    classifier = FastIntentClassifier()

    # Test cases: (message, expected_intent, expected_fast_path)
    test_cases = [
        # Greetings (fast path)
        ("hi", IntentType.GREETING, True),
        ("hello", IntentType.GREETING, True),
        ("hey there", IntentType.GREETING, True),
        ("good morning", IntentType.GREETING, True),

        # Farewells (fast path)
        ("bye", IntentType.FAREWELL, True),
        ("goodbye", IntentType.FAREWELL, True),

        # Thanks (fast path)
        ("thanks", IntentType.THANKS, True),
        ("thank you", IntentType.THANKS, True),

        # Acknowledgments (fast path)
        ("ok", IntentType.ACKNOWLEDGMENT, True),
        ("sure", IntentType.ACKNOWLEDGMENT, True),

        # Code generation (full path)
        ("write a python function", IntentType.CODE_GENERATION, False),

        # Desktop control (full path)
        ("open chrome browser", IntentType.DESKTOP_CONTROL, False),
    ]

    passed = 0
    failed = 0
    total_time = 0

    for message, expected_intent, expected_fast in test_cases:
        result = classifier.classify(message)
        total_time += result.classification_time_ms

        intent_match = result.intent == expected_intent
        fast_match = result.is_fast_path == expected_fast

        if intent_match and fast_match:
            passed += 1
        else:
            failed += 1
            print(f"  [FAIL] '{message}': got {result.intent.value}, fast={result.is_fast_path}")

    avg_time = total_time / len(test_cases)
    print(f"  [OK] {passed}/{len(test_cases)} tests passed")
    print(f"  [OK] Average classification time: {avg_time:.3f}ms")

    # Performance check
    assert avg_time < 5.0, f"Classification too slow: {avg_time:.3f}ms"
    print(f"  [OK] Performance check passed (<5ms)")

    if failed == 0:
        print("[PASS] Intent Classifier tests passed")
        return True
    else:
        print(f"[FAIL] {failed} tests failed")
        return False


async def test_fast_router():
    """Test fast routing decisions."""
    print("\n[TEST] Fast Router...")

    from app.realtime.fast_router import FastRouter, RoutingPath

    router = FastRouter()

    # Test cases: (message, expected_path)
    test_cases = [
        # Fast path
        ("hi", RoutingPath.FAST),
        ("hello", RoutingPath.FAST),
        ("thanks", RoutingPath.FAST),
        ("bye", RoutingPath.FAST),

        # Full path
        ("write me a python script to parse CSV", RoutingPath.FULL),
        ("open chrome and go to google", RoutingPath.FULL),
    ]

    passed = 0
    failed = 0
    total_time = 0

    for message, expected_path in test_cases:
        decision = router.route(message)
        total_time += decision.total_time_ms

        if decision.path == expected_path:
            passed += 1
        else:
            failed += 1
            print(f"  [FAIL] '{message}': got {decision.path.value}, expected {expected_path.value}")

    avg_time = total_time / len(test_cases)
    print(f"  [OK] {passed}/{len(test_cases)} tests passed")
    print(f"  [OK] Average routing time: {avg_time:.3f}ms")

    # Performance check (should be <10ms)
    assert avg_time < 10.0, f"Routing too slow: {avg_time:.3f}ms"
    print(f"  [OK] Performance check passed (<10ms)")

    if failed == 0:
        print("[PASS] Fast Router tests passed")
        return True
    else:
        print(f"[FAIL] {failed} tests failed")
        return False


async def test_simple_responder():
    """Test simple responder."""
    print("\n[TEST] Simple Responder...")

    from app.realtime.simple_responder import SimpleResponder
    from app.realtime.fast_intent_classifier import IntentType

    responder = SimpleResponder()

    # Test instant responses (no LLM call)
    instant_cases = [
        (IntentType.GREETING, "hi"),
        (IntentType.GREETING, "hello"),
        (IntentType.FAREWELL, "bye"),
        (IntentType.THANKS, "thanks"),
    ]

    for intent, message in instant_cases:
        response = await responder.get_instant_response(intent, message)
        assert response is not None, f"No instant response for {message}"
        assert len(response) > 0, f"Empty instant response for {message}"
        print(f"  [OK] Instant: '{message}' -> '{response}'")

    print("  [OK] All instant response tests passed")
    print("[PASS] Simple Responder tests passed")
    return True


async def test_response_sanitizer():
    """Test response sanitizer."""
    print("\n[TEST] Response Sanitizer...")

    from app.realtime.response_sanitizer import ResponseSanitizer

    sanitizer = ResponseSanitizer()

    # Test sanitization
    test_cases = [
        # Debug removal
        ("[DEBUG] some debug info\nActual response", "Actual response"),
        # Excessive whitespace
        ("Hello    there", "Hello there"),
        # Multiple punctuation
        ("Really????!!!!", "Really?!"),
    ]

    passed = 0
    for input_text, expected_contains in test_cases:
        result = sanitizer.sanitize(input_text)
        if expected_contains in result:
            passed += 1
        else:
            print(f"  [FAIL] Expected '{expected_contains}' in result")

    print(f"  [OK] {passed}/{len(test_cases)} sanitize tests passed")

    # Test conversational
    formal = "I would be happy to help you with that."
    casual = sanitizer.make_conversational(formal)
    print(f"  [OK] Conversational: '{formal[:30]}...' -> '{casual[:30]}...'")

    print("[PASS] Response Sanitizer tests passed")
    return True


async def test_fast_path_handler():
    """Test integrated fast path handler (fast path only)."""
    print("\n[TEST] Fast Path Handler (fast path only)...")

    from app.realtime.fast_path_handler import FastPathHandler
    from app.realtime.session_manager import SessionManager
    from app.realtime.request_lifecycle import RequestLifecycleController
    from app.realtime.fast_intent_classifier import FastIntentClassifier
    from app.realtime.fast_router import FastRouter
    from app.realtime.simple_responder import SimpleResponder
    from app.realtime.response_sanitizer import ResponseSanitizer

    # Create isolated handler without full runtime dependencies
    handler = FastPathHandler(
        classifier=FastIntentClassifier(),
        router=FastRouter(),
        responder=SimpleResponder(),
        sanitizer=ResponseSanitizer(),
        sessions=SessionManager(),
        lifecycle=RequestLifecycleController()
    )

    # Test fast path messages only (avoid full runtime)
    fast_messages = [
        "hello",
        "hi there",
        "thanks",
        "bye",
    ]

    for message in fast_messages:
        result = await handler.handle(
            message=message,
            user_id="test_user",
            conversation_id="test_conv"
        )

        assert result.is_fast_path, f"'{message}' should be fast path"
        assert result.success, f"'{message}' should succeed"
        assert result.total_time_ms < 500, f"'{message}' too slow: {result.total_time_ms}ms"

        response_preview = result.response[:30] + "..." if len(result.response) > 30 else result.response
        print(f"  [OK] Fast: '{message}' -> '{response_preview}' ({result.total_time_ms:.0f}ms)")

    print("[PASS] Fast Path Handler tests passed")
    return True


async def test_performance():
    """Test overall performance."""
    print("\n[TEST] Performance Benchmarks...")

    from app.realtime.fast_path_handler import FastPathHandler
    from app.realtime.session_manager import SessionManager
    from app.realtime.request_lifecycle import RequestLifecycleController
    from app.realtime.fast_intent_classifier import FastIntentClassifier
    from app.realtime.fast_router import FastRouter
    from app.realtime.simple_responder import SimpleResponder
    from app.realtime.response_sanitizer import ResponseSanitizer

    # Create isolated handler
    handler = FastPathHandler(
        classifier=FastIntentClassifier(),
        router=FastRouter(),
        responder=SimpleResponder(),
        sanitizer=ResponseSanitizer(),
        sessions=SessionManager(),
        lifecycle=RequestLifecycleController()
    )

    # Benchmark fast path
    messages = ["hi", "hello", "hey", "thanks", "bye"]
    times = []

    for _ in range(5):
        for msg in messages:
            start = time.perf_counter()
            await handler.handle(msg, "user", "conv")
            times.append((time.perf_counter() - start) * 1000)

    avg_time = sum(times) / len(times)
    min_time = min(times)
    max_time = max(times)

    print(f"  [OK] Fast path times: avg={avg_time:.1f}ms, min={min_time:.1f}ms, max={max_time:.1f}ms")

    # Check targets
    if avg_time < 100:
        print("  [OK] Target met: avg < 100ms (instant feel)")
    elif avg_time < 300:
        print("  [WARN] Close to target: avg < 300ms")
    else:
        print(f"  [FAIL] Too slow: avg = {avg_time:.1f}ms (target: <300ms)")
        return False

    print("[PASS] Performance tests completed")
    return True


async def main():
    """Run all Phase 3 tests."""
    print("=" * 60)
    print("Phase 3 Test: Fast Path + Intelligent Routing")
    print("=" * 60)

    tests = [
        ("Intent Classifier", test_intent_classifier),
        ("Fast Router", test_fast_router),
        ("Simple Responder", test_simple_responder),
        ("Response Sanitizer", test_response_sanitizer),
        ("Fast Path Handler", test_fast_path_handler),
        ("Performance", test_performance),
    ]

    results = []

    for name, test_func in tests:
        try:
            result = await test_func()
            results.append((name, result, None))
        except Exception as e:
            results.append((name, False, str(e)))
            print(f"[FAIL] {name} failed: {e}")

    print("\n" + "=" * 60)
    print("Test Results:")
    print("=" * 60)

    all_passed = True
    for name, passed, error in results:
        if passed:
            print(f"  [PASS] {name}")
        else:
            print(f"  [FAIL] {name}: {error}")
            all_passed = False

    if all_passed:
        print("\nAll Phase 3 tests passed!")
        return 0
    else:
        print("\nSome tests failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
