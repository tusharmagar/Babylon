#!/usr/bin/env python3
"""
Backend API Testing for Pangolin BEYOND Control App
Focus on NEW chat/AI endpoints as requested in review
"""

import requests
import sys
import json
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

class BeyondAPITester:
    def __init__(self, base_url="https://pangolin-ai-builder.preview.emergentagent.com"):
        self.base_url = base_url
        self.api_url = f"{base_url}/api"
        self.tests_run = 0
        self.tests_passed = 0
        self.test_results = []
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})
        self.test_session_id = None  # Store session ID for testing

    def log_test(self, name: str, success: bool, details: str = "", response_data: Any = None):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
        
        result = {
            "test_name": name,
            "success": success,
            "details": details,
            "response_data": response_data,
            "timestamp": datetime.now().isoformat()
        }
        self.test_results.append(result)
        
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} - {name}")
        if details:
            print(f"    {details}")
        if not success and response_data:
            print(f"    Response: {response_data}")

    def run_test(self, name: str, method: str, endpoint: str, expected_status: int, 
                 data: Dict = None, expected_fields: List[str] = None, timeout: int = 30) -> Optional[Dict]:
        """Run a single API test and return response data if successful"""
        url = f"{self.api_url}/{endpoint}"
        
        try:
            if method.upper() == "GET":
                response = self.session.get(url, timeout=timeout)
            elif method.upper() == "POST":
                response = self.session.post(url, json=data, timeout=timeout)
            elif method.upper() == "DELETE":
                response = self.session.delete(url, timeout=timeout)
            else:
                self.log_test(name, False, f"Unsupported method: {method}")
                return None
            
            # Check status code
            if response.status_code != expected_status:
                try:
                    error_data = response.json()
                except:
                    error_data = response.text
                self.log_test(name, False, 
                             f"Expected status {expected_status}, got {response.status_code}",
                             error_data)
                return None
            
            # Parse JSON response
            try:
                response_data = response.json()
            except json.JSONDecodeError:
                self.log_test(name, False, "Invalid JSON response", response.text)
                return None
            
            # Check expected fields
            if expected_fields:
                missing_fields = [field for field in expected_fields if field not in response_data]
                if missing_fields:
                    self.log_test(name, False, f"Missing fields: {missing_fields}", response_data)
                    return None
            
            self.log_test(name, True, f"Status: {response.status_code}")
            return response_data
            
        except requests.exceptions.Timeout:
            self.log_test(name, False, f"Request timeout after {timeout}s")
            return None
        except requests.exceptions.RequestException as e:
            self.log_test(name, False, f"Request error: {str(e)}")
            return None
        except Exception as e:
            self.log_test(name, False, f"Unexpected error: {str(e)}")
            return None

    def test_existing_endpoints(self):
        """Test existing endpoints to ensure they still work"""
        print("\n=== Testing Existing Endpoints ===")
        
        # Test status endpoint
        self.run_test("GET /api/status", "GET", "status", 200, 
                     expected_fields=["connected", "host", "port", "echo_mode"])
        
        # Test config endpoint
        self.run_test("GET /api/config", "GET", "config", 200)
        
        # Test logs endpoint
        self.run_test("GET /api/logs", "GET", "logs", 200, 
                     expected_fields=["logs"])

    def test_chat_new(self):
        """Test POST /api/chat/new - Create a new chat session"""
        print("\n=== Testing Chat Session Creation ===")
        
        response_data = self.run_test(
            "POST /api/chat/new", 
            "POST", 
            "chat/new", 
            200,
            expected_fields=["session_id", "title", "created_at"]
        )
        
        if response_data:
            self.test_session_id = response_data["session_id"]
            print(f"    Created session: {self.test_session_id[:8]}...")
            print(f"    Title: '{response_data['title']}'")

    def test_chat_sessions_list(self):
        """Test GET /api/chat/sessions - List all chat sessions"""
        print("\n=== Testing Chat Sessions List ===")
        
        response_data = self.run_test(
            "GET /api/chat/sessions",
            "GET",
            "chat/sessions",
            200,
            expected_fields=["sessions"]
        )
        
        if response_data:
            sessions = response_data["sessions"]
            print(f"    Found {len(sessions)} sessions")
            
            # Verify our test session is in the list if we created one
            if self.test_session_id:
                session_ids = [s.get("id") for s in sessions]
                if self.test_session_id in session_ids:
                    print(f"    ✓ Test session {self.test_session_id[:8]}... found in list")
                else:
                    print(f"    ⚠ Test session {self.test_session_id[:8]}... not found in list")

    def test_chat_send(self):
        """Test POST /api/chat/send - Send a message to AI agent (CRITICAL TEST - 120s timeout)"""
        print("\n=== Testing Chat Send (AI Agent) ===")
        print("⏳ This test calls the LLM and may take 30-60 seconds...")
        
        # Test data with a simple laser pattern request
        test_message = {
            "message": "Draw a simple circle pattern",
            "session_id": self.test_session_id  # Use existing session or None for new
        }
        
        response_data = self.run_test(
            "POST /api/chat/send",
            "POST",
            "chat/send",
            200,
            data=test_message,
            expected_fields=["session_id", "message", "pattern_name", "point_data", "python_code", "message_id"],
            timeout=120  # Extended timeout for LLM call
        )
        
        if response_data:
            # Update test session ID if it was created
            if not self.test_session_id:
                self.test_session_id = response_data["session_id"]
            
            # Validate point_data structure
            point_data = response_data.get("point_data", [])
            if isinstance(point_data, list) and len(point_data) > 0:
                # Check first point has required fields
                first_point = point_data[0]
                point_fields = ["x", "y", "color", "rep_count"]
                missing_point_fields = [field for field in point_fields if field not in first_point]
                
                if missing_point_fields:
                    print(f"    ❌ Point data missing fields: {missing_point_fields}")
                else:
                    print(f"    ✓ AI response generated successfully")
                    print(f"    Pattern: '{response_data['pattern_name']}'")
                    print(f"    Points: {len(point_data)}")
                    print(f"    Code length: {len(response_data.get('python_code', ''))}")
                    print(f"    Sample point: x={first_point['x']}, y={first_point['y']}, color={first_point['color']}")
            else:
                print(f"    ❌ Point data is empty or invalid")

    def test_chat_messages(self):
        """Test GET /api/chat/{session_id}/messages - Get messages for a session"""
        print("\n=== Testing Chat Messages Retrieval ===")
        
        if not self.test_session_id:
            self.log_test("GET /api/chat/{session_id}/messages", False, "No test session ID available")
            return
        
        response_data = self.run_test(
            f"GET /api/chat/{self.test_session_id}/messages",
            "GET",
            f"chat/{self.test_session_id}/messages",
            200,
            expected_fields=["messages"]
        )
        
        if response_data:
            messages = response_data["messages"]
            print(f"    Retrieved {len(messages)} messages for session {self.test_session_id[:8]}...")
            
            # Verify message structure
            if len(messages) > 0:
                first_msg = messages[0]
                required_msg_fields = ["id", "session_id", "role", "content", "created_at"]
                missing_msg_fields = [field for field in required_msg_fields if field not in first_msg]
                
                if missing_msg_fields:
                    print(f"    ⚠ Message missing fields: {missing_msg_fields}")
                else:
                    print(f"    ✓ Message structure valid: role={first_msg['role']}, content_length={len(first_msg['content'])}")

    def test_chat_delete(self):
        """Test DELETE /api/chat/{session_id} - Delete a session"""
        print("\n=== Testing Chat Session Deletion ===")
        
        if not self.test_session_id:
            self.log_test("DELETE /api/chat/{session_id}", False, "No test session ID available")
            return
        
        response_data = self.run_test(
            f"DELETE /api/chat/{self.test_session_id}",
            "DELETE",
            f"chat/{self.test_session_id}",
            200,
            expected_fields=["success"]
        )
        
        if response_data and response_data.get("success"):
            print(f"    ✓ Session {self.test_session_id[:8]}... deleted successfully")
            
            # Verify deletion by trying to get messages (should return empty)
            verify_response = self.run_test(
                f"GET /api/chat/{self.test_session_id}/messages (verify deletion)",
                "GET",
                f"chat/{self.test_session_id}/messages",
                200
            )
            if verify_response and len(verify_response.get("messages", [])) == 0:
                print("    ✓ Deletion verified: no messages found for deleted session")

    def test_chat_send_new_session(self):
        """Test POST /api/chat/send with session_id=null to create new session"""
        print("\n=== Testing Chat Send (New Session Creation) ===")
        
        test_message = {
            "message": "Draw a simple line from left to right",
            "session_id": None  # This should create a new session
        }
        
        response_data = self.run_test(
            "POST /api/chat/send (new session)",
            "POST",
            "chat/send",
            200,
            data=test_message,
            expected_fields=["session_id", "message", "pattern_name", "point_data", "python_code", "message_id"],
            timeout=120
        )
        
        if response_data:
            new_session_id = response_data.get("session_id")
            if new_session_id:
                print(f"    ✓ New session created: {new_session_id[:8]}...")
                
                # Clean up the new session
                cleanup_response = self.run_test(
                    f"DELETE /api/chat/{new_session_id} (cleanup)",
                    "DELETE",
                    f"chat/{new_session_id}",
                    200
                )
                if cleanup_response:
                    print(f"    ✓ Cleanup: deleted test session {new_session_id[:8]}...")

    def run_all_tests(self):
        """Run all tests in the correct order"""
        print("🚀 Starting Pangolin BEYOND Backend API Tests")
        print(f"Backend URL: {self.api_url}")
        print("="*60)
        
        # Test existing endpoints first
        self.test_existing_endpoints()
        
        # Test new chat/AI endpoints in logical order
        self.test_chat_new()
        self.test_chat_sessions_list()
        self.test_chat_send()
        self.test_chat_messages()
        self.test_chat_send_new_session()
        self.test_chat_delete()
        
        # Print summary
        self.print_summary()

    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        
        print(f"Total Tests: {self.tests_run}")
        print(f"Passed: {self.tests_passed}")
        print(f"Failed: {self.tests_run - self.tests_passed}")
        print(f"Success Rate: {(self.tests_passed/self.tests_run)*100:.1f}%")
        
        failed_tests = [result for result in self.test_results if not result["success"]]
        if failed_tests:
            print("\nFAILED TESTS:")
            for result in failed_tests:
                print(f"❌ {result['test_name']}: {result['details']}")
        
        print("\n" + "="*60)
        
        return len(failed_tests) == 0

def main():
    """Main test runner"""
    tester = BeyondAPITester()
    tester.run_all_tests()
    
    # Return exit code based on test results
    all_passed = tester.tests_passed == tester.tests_run
    return 0 if all_passed else 1

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n⚠ Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Test runner error: {e}")
        sys.exit(1)