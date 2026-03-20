"""
End-to-End Integration Test - Phase 4

Tests the complete ecosystem:
- Frontend → Gateway → Backend → Desktop Agent

Run this after starting all services:
1. Backend: python -m uvicorn app.main:app --reload
2. Desktop Agent: python desktop-agent/gateway_client.py
3. Frontend: npm start

Then run this test:
    python test_phase4_integration.py
"""

import asyncio
import websockets
import json
import time
from datetime import datetime


async def test_websocket_connection():
    """Test 1: WebSocket Connection"""
    print("\n[TEST 1] WebSocket Connection")
    print("-" * 50)

    uri = "ws://localhost:8000/ws/chat?session_id=test_session&user_id=test_user"

    try:
        async with websockets.connect(uri) as websocket:
            print("✓ Connected to WebSocket")

            # Wait for ACK
            response = await asyncio.wait_for(websocket.recv(), timeout=5)
            data = json.loads(response)

            print(f"✓ Received: {data.get('type')}")
            assert data.get('type') == 'ack', "Expected ACK message"

            print("[PASS] WebSocket connection test passed")
            return True

    except Exception as e:
        print(f"[FAIL] WebSocket connection test failed: {e}")
        return False


async def test_fast_path_message():
    """Test 2: Fast Path Message"""
    print("\n[TEST 2] Fast Path Message")
    print("-" * 50)

    uri = "ws://localhost:8000/ws/chat?session_id=test_fast&user_id=test_user"

    try:
        async with websockets.connect(uri) as websocket:
            # Wait for ACK
            await websocket.recv()

            # Send greeting (fast path)
            message = {
                "type": "user_message",
                "message": "hello",
                "session_id": "test_fast",
                "user_id": "test_user"
            }

            print("→ Sending: 'hello'")
            await websocket.send(json.dumps(message))

            # Collect responses
            messages_received = []
            start_time = time.time()

            while True:
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=2)
                    data = json.loads(response)
                    messages_received.append(data)

                    msg_type = data.get('type')
                    print(f"← Received: {msg_type}")

                    if msg_type == 'complete':
                        break

                except asyncio.TimeoutError:
                    break

            elapsed = (time.time() - start_time) * 1000

            # Verify fast path
            complete_msg = messages_received[-1] if messages_received else {}
            is_fast = complete_msg.get('is_fast_path', False)

            print(f"\n✓ Response time: {elapsed:.0f}ms")
            print(f"✓ Fast path: {is_fast}")
            print(f"✓ Messages received: {len(messages_received)}")

            assert is_fast, "Expected fast path routing"
            assert elapsed < 1000, f"Too slow: {elapsed}ms"

            print("[PASS] Fast path message test passed")
            return True

    except Exception as e:
        print(f"[FAIL] Fast path message test failed: {e}")
        return False


async def test_thinking_and_streaming():
    """Test 3: Thinking and Streaming"""
    print("\n[TEST 3] Thinking and Streaming")
    print("-" * 50)

    uri = "ws://localhost:8000/ws/chat?session_id=test_stream&user_id=test_user"

    try:
        async with websockets.connect(uri) as websocket:
            # Wait for ACK
            await websocket.recv()

            # Send message
            message = {
                "type": "user_message",
                "message": "tell me a joke",
                "session_id": "test_stream",
                "user_id": "test_user"
            }

            await websocket.send(json.dumps(message))

            # Check for thinking message
            has_thinking = False
            has_streaming = False
            chunks = []

            while True:
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=3)
                    data = json.loads(response)
                    msg_type = data.get('type')

                    if msg_type == 'thinking':
                        has_thinking = True
                        print("✓ Thinking message received")

                    elif msg_type == 'stream_chunk':
                        has_streaming = True
                        content = data.get('content', '')
                        chunks.append(content)

                    elif msg_type == 'complete':
                        break

                except asyncio.TimeoutError:
                    break

            full_response = ''.join(chunks)

            print(f"✓ Thinking: {has_thinking}")
            print(f"✓ Streaming: {has_streaming}")
            print(f"✓ Chunks received: {len(chunks)}")
            print(f"✓ Response length: {len(full_response)} chars")

            assert has_thinking, "Expected thinking message"
            assert len(chunks) > 0, "Expected streaming chunks"

            print("[PASS] Thinking and streaming test passed")
            return True

    except Exception as e:
        print(f"[FAIL] Thinking and streaming test failed: {e}")
        return False


async def test_session_persistence():
    """Test 4: Session Persistence"""
    print("\n[TEST 4] Session Persistence")
    print("-" * 50)

    session_id = "test_persist"
    uri = f"ws://localhost:8000/ws/chat?session_id={session_id}&user_id=test_user"

    try:
        # First connection
        print("→ First connection")
        async with websockets.connect(uri) as websocket:
            await websocket.recv()  # ACK
            print("✓ Connected")

        # Wait a bit
        await asyncio.sleep(0.5)

        # Second connection with same session_id
        print("\n→ Second connection (same session)")
        async with websockets.connect(uri) as websocket:
            response = await websocket.recv()
            data = json.loads(response)

            session_from_server = data.get('session_id')
            print(f"✓ Session ID: {session_from_server}")

            assert session_from_server == session_id, "Session ID mismatch"

        print("[PASS] Session persistence test passed")
        return True

    except Exception as e:
        print(f"[FAIL] Session persistence test failed: {e}")
        return False


async def test_error_handling():
    """Test 5: Error Handling"""
    print("\n[TEST 5] Error Handling")
    print("-" * 50)

    uri = "ws://localhost:8000/ws/chat?session_id=test_error&user_id=test_user"

    try:
        async with websockets.connect(uri) as websocket:
            # Wait for ACK
            await websocket.recv()

            # Send invalid message
            invalid_message = {
                "type": "invalid_type",
                "session_id": "test_error"
            }

            print("→ Sending invalid message")
            await websocket.send(json.dumps(invalid_message))

            # Should still work (not crash)
            await asyncio.sleep(1)

            # Send valid message
            valid_message = {
                "type": "user_message",
                "message": "hi",
                "session_id": "test_error"
            }

            print("→ Sending valid message")
            await websocket.send(json.dumps(valid_message))

            # Should receive response
            has_response = False
            while True:
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=2)
                    data = json.loads(response)

                    if data.get('type') == 'complete':
                        has_response = True
                        break
                except asyncio.TimeoutError:
                    break

            print(f"✓ Recovery after error: {has_response}")
            assert has_response, "Expected recovery after invalid message"

            print("[PASS] Error handling test passed")
            return True

    except Exception as e:
        print(f"[FAIL] Error handling test failed: {e}")
        return False


async def main():
    """Run all integration tests"""
    print("=" * 60)
    print("Phase 4: End-to-End Integration Tests")
    print("=" * 60)

    print("\n⚠️  Ensure these services are running:")
    print("  1. Backend: uvicorn app.main:app --reload")
    print("  2. Desktop Agent: python gateway_client.py")
    print("  3. Frontend: npm start")
    print("\nStarting tests in 3 seconds...\n")

    await asyncio.sleep(3)

    tests = [
        ("WebSocket Connection", test_websocket_connection),
        ("Fast Path Message", test_fast_path_message),
        ("Thinking and Streaming", test_thinking_and_streaming),
        ("Session Persistence", test_session_persistence),
        ("Error Handling", test_error_handling),
    ]

    results = []

    for name, test_func in tests:
        try:
            result = await test_func()
            results.append((name, result))
        except Exception as e:
            print(f"[FAIL] {name} crashed: {e}")
            results.append((name, False))

        await asyncio.sleep(1)  # Pause between tests

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status} {name}")

    print(f"\nResults: {passed}/{total} tests passed")

    if passed == total:
        print("\n✅ All integration tests passed!")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
