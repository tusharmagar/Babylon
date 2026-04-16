#!/usr/bin/env python3
"""
Comprehensive backend test for Pangolin BEYOND laser control system.
Tests all laser control and chat endpoints as specified in the review request.
"""

import requests
import json
import time
import sys
import logging
from typing import Dict, Any, Optional

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Backend URL from frontend .env
BACKEND_URL = "https://youtube-to-laser.preview.emergentagent.com/api"

class BeyondAPITester:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.timeout = 120  # 120 second timeout for LLM calls
        self.test_results = []
        
    def log_test(self, test_name: str, success: bool, details: str = "", response_data: Any = None):
        """Log test result"""
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"{status} {test_name}: {details}")
        self.test_results.append({
            "test": test_name,
            "success": success,
            "details": details,
            "response_data": response_data
        })
        
    def make_request(self, method: str, endpoint: str, data: Dict = None, timeout: int = 30) -> tuple[bool, Dict]:
        """Make HTTP request and return (success, response_data)"""
        url = f"{self.base_url}{endpoint}"
        try:
            if method.upper() == "GET":
                response = self.session.get(url, timeout=timeout)
            elif method.upper() == "POST":
                response = self.session.post(url, json=data, timeout=timeout)
            elif method.upper() == "DELETE":
                response = self.session.delete(url, timeout=timeout)
            else:
                return False, {"error": f"Unsupported method: {method}"}
                
            response.raise_for_status()
            return True, response.json()
            
        except requests.exceptions.Timeout:
            return False, {"error": "Request timeout"}
        except requests.exceptions.RequestException as e:
            return False, {"error": str(e), "status_code": getattr(e.response, 'status_code', None)}
        except json.JSONDecodeError:
            return False, {"error": "Invalid JSON response", "text": response.text[:500]}
        except Exception as e:
            return False, {"error": f"Unexpected error: {str(e)}"}

    def test_laser_status_initial(self):
        """Test 1: GET /api/laser/status - Initial status check"""
        success, data = self.make_request("GET", "/laser/status")
        
        if not success:
            self.log_test("Laser Status (Initial)", False, f"Request failed: {data.get('error', 'Unknown error')}")
            return None
            
        # Check required fields
        required_fields = ["initialized", "simulation_mode", "streaming", "point_count", 
                          "current_pattern", "frames_sent", "fps", "scan_rate", "last_error"]
        missing_fields = [field for field in required_fields if field not in data]
        
        if missing_fields:
            self.log_test("Laser Status (Initial)", False, f"Missing fields: {missing_fields}", data)
            return None
            
        self.log_test("Laser Status (Initial)", True, 
                     f"initialized={data['initialized']}, simulation_mode={data['simulation_mode']}, "
                     f"streaming={data['streaming']}, point_count={data['point_count']}", data)
        return data

    def test_laser_send(self):
        """Test 2: POST /api/laser/send - Send point data"""
        test_data = {
            "point_data": [
                {"x": 0, "y": 0, "color": "0x00FFFFFF", "rep_count": 0},
                {"x": 10000, "y": 10000, "color": "0x000000FF", "rep_count": 2}
            ],
            "pattern_name": "Test"
        }
        
        success, data = self.make_request("POST", "/laser/send", test_data)
        
        if not success:
            self.log_test("Laser Send", False, f"Request failed: {data.get('error', 'Unknown error')}")
            return None
            
        # Check required response fields
        required_fields = ["success", "point_count", "simulation_mode"]
        missing_fields = [field for field in required_fields if field not in data]
        
        if missing_fields:
            self.log_test("Laser Send", False, f"Missing fields: {missing_fields}", data)
            return None
            
        if not data.get("success"):
            self.log_test("Laser Send", False, f"Success=false in response", data)
            return None
            
        expected_count = len(test_data["point_data"])
        if data.get("point_count") != expected_count:
            self.log_test("Laser Send", False, 
                         f"Point count mismatch: expected {expected_count}, got {data.get('point_count')}", data)
            return None
            
        self.log_test("Laser Send", True, 
                     f"success={data['success']}, point_count={data['point_count']}, "
                     f"simulation_mode={data['simulation_mode']}", data)
        return data

    def test_laser_status_after_send(self):
        """Test 3: GET /api/laser/status - Status after sending points"""
        success, data = self.make_request("GET", "/laser/status")
        
        if not success:
            self.log_test("Laser Status (After Send)", False, f"Request failed: {data.get('error', 'Unknown error')}")
            return None
            
        # Should now show streaming=true, point_count=2, current_pattern="Test"
        expected_streaming = True
        expected_count = 2
        expected_pattern = "Test"
        
        issues = []
        if data.get("streaming") != expected_streaming:
            issues.append(f"streaming={data.get('streaming')}, expected {expected_streaming}")
        if data.get("point_count") != expected_count:
            issues.append(f"point_count={data.get('point_count')}, expected {expected_count}")
        if data.get("current_pattern") != expected_pattern:
            issues.append(f"current_pattern='{data.get('current_pattern')}', expected '{expected_pattern}'")
            
        if issues:
            self.log_test("Laser Status (After Send)", False, "; ".join(issues), data)
            return None
            
        self.log_test("Laser Status (After Send)", True, 
                     f"streaming={data['streaming']}, point_count={data['point_count']}, "
                     f"current_pattern='{data['current_pattern']}'", data)
        return data

    def test_laser_blackout(self):
        """Test 4: POST /api/laser/blackout - Clear laser"""
        success, data = self.make_request("POST", "/laser/blackout")
        
        if not success:
            self.log_test("Laser Blackout", False, f"Request failed: {data.get('error', 'Unknown error')}")
            return None
            
        if not data.get("success"):
            self.log_test("Laser Blackout", False, f"Success=false in response", data)
            return None
            
        self.log_test("Laser Blackout", True, f"success={data['success']}", data)
        return data

    def test_laser_status_after_blackout(self):
        """Test 5: GET /api/laser/status - Status after blackout"""
        success, data = self.make_request("GET", "/laser/status")
        
        if not success:
            self.log_test("Laser Status (After Blackout)", False, f"Request failed: {data.get('error', 'Unknown error')}")
            return None
            
        # Should now show streaming=false, point_count=0
        expected_streaming = False
        expected_count = 0
        
        issues = []
        if data.get("streaming") != expected_streaming:
            issues.append(f"streaming={data.get('streaming')}, expected {expected_streaming}")
        if data.get("point_count") != expected_count:
            issues.append(f"point_count={data.get('point_count')}, expected {expected_count}")
            
        if issues:
            self.log_test("Laser Status (After Blackout)", False, "; ".join(issues), data)
            return None
            
        self.log_test("Laser Status (After Blackout)", True, 
                     f"streaming={data['streaming']}, point_count={data['point_count']}", data)
        return data

    def test_chat_new_session(self):
        """Test 6: POST /api/chat/new - Create new chat session"""
        success, data = self.make_request("POST", "/chat/new")
        
        if not success:
            self.log_test("Chat New Session", False, f"Request failed: {data.get('error', 'Unknown error')}")
            return None
            
        # Check required fields
        required_fields = ["id", "title", "created_at"]
        missing_fields = [field for field in required_fields if field not in data]
        
        if missing_fields:
            self.log_test("Chat New Session", False, f"Missing fields: {missing_fields}", data)
            return None
            
        session_id = data.get("id")
        if not session_id:
            self.log_test("Chat New Session", False, "No session ID returned", data)
            return None
            
        self.log_test("Chat New Session", True, 
                     f"id={session_id}, title='{data.get('title')}'", data)
        return data

    def test_chat_list_sessions(self):
        """Test 7: GET /api/chat/sessions - List chat sessions"""
        success, data = self.make_request("GET", "/chat/sessions")
        
        if not success:
            self.log_test("Chat List Sessions", False, f"Request failed: {data.get('error', 'Unknown error')}")
            return None
            
        if "sessions" not in data:
            self.log_test("Chat List Sessions", False, "No 'sessions' field in response", data)
            return None
            
        sessions = data["sessions"]
        if not isinstance(sessions, list):
            self.log_test("Chat List Sessions", False, "'sessions' is not a list", data)
            return None
            
        self.log_test("Chat List Sessions", True, f"Found {len(sessions)} sessions", data)
        return data

    def test_chat_send_message(self):
        """Test 8: POST /api/chat/send - Send message to AI (120s timeout)"""
        test_data = {
            "message": "Draw a simple line",
            "session_id": None  # Will create new session
        }
        
        logger.info("Sending chat message - this may take 30-60 seconds for LLM processing...")
        success, data = self.make_request("POST", "/chat/send", test_data, timeout=120)
        
        if not success:
            self.log_test("Chat Send Message", False, f"Request failed: {data.get('error', 'Unknown error')}")
            return None
            
        # Check required response fields
        required_fields = ["session_id", "message", "pattern_name", "point_data", "python_code", "message_id"]
        missing_fields = [field for field in required_fields if field not in data]
        
        if missing_fields:
            self.log_test("Chat Send Message", False, f"Missing fields: {missing_fields}", data)
            return None
            
        session_id = data.get("session_id")
        point_data = data.get("point_data", [])
        
        if not session_id:
            self.log_test("Chat Send Message", False, "No session_id returned", data)
            return None
            
        if not isinstance(point_data, list):
            self.log_test("Chat Send Message", False, "point_data is not a list", data)
            return None
            
        self.log_test("Chat Send Message", True, 
                     f"session_id={session_id}, pattern='{data.get('pattern_name')}', "
                     f"points={len(point_data)}, message_id={data.get('message_id')}", data)
        return data

    def test_chat_get_messages(self, session_id: str):
        """Test 9: GET /api/chat/{session_id}/messages - Get session messages"""
        success, data = self.make_request("GET", f"/chat/{session_id}/messages")
        
        if not success:
            self.log_test("Chat Get Messages", False, f"Request failed: {data.get('error', 'Unknown error')}")
            return None
            
        if "messages" not in data:
            self.log_test("Chat Get Messages", False, "No 'messages' field in response", data)
            return None
            
        messages = data["messages"]
        if not isinstance(messages, list):
            self.log_test("Chat Get Messages", False, "'messages' is not a list", data)
            return None
            
        self.log_test("Chat Get Messages", True, f"Found {len(messages)} messages for session {session_id}", data)
        return data

    def test_chat_delete_session(self, session_id: str):
        """Test 10: DELETE /api/chat/{session_id} - Delete session"""
        success, data = self.make_request("DELETE", f"/chat/{session_id}")
        
        if not success:
            self.log_test("Chat Delete Session", False, f"Request failed: {data.get('error', 'Unknown error')}")
            return None
            
        if not data.get("success"):
            self.log_test("Chat Delete Session", False, f"Success=false in response", data)
            return None
            
        self.log_test("Chat Delete Session", True, f"Deleted session {session_id}", data)
        return data

    def test_laser_stop(self):
        """Test 11: POST /api/laser/stop - Stop streaming"""
        success, data = self.make_request("POST", "/laser/stop")
        
        if not success:
            self.log_test("Laser Stop", False, f"Request failed: {data.get('error', 'Unknown error')}")
            return None
            
        if not data.get("success"):
            self.log_test("Laser Stop", False, f"Success=false in response", data)
            return None
            
        self.log_test("Laser Stop", True, f"success={data['success']}", data)
        return data

    def run_full_test_sequence(self):
        """Run the complete test sequence as specified in the review request"""
        logger.info(f"Starting comprehensive backend test for {self.base_url}")
        logger.info("=" * 80)
        
        # Test sequence as specified in review request
        session_id = None
        
        # 1. Initial laser status
        self.test_laser_status_initial()
        
        # 2. Send laser data
        self.test_laser_send()
        
        # 3. Check status after send
        self.test_laser_status_after_send()
        
        # 4. Blackout laser
        self.test_laser_blackout()
        
        # 5. Check status after blackout
        self.test_laser_status_after_blackout()
        
        # 6. Create new chat session
        session_data = self.test_chat_new_session()
        if session_data:
            session_id = session_data.get("id")
        
        # 7. List chat sessions
        self.test_chat_list_sessions()
        
        # 8. Send chat message (120s timeout for LLM)
        chat_response = self.test_chat_send_message()
        if chat_response and not session_id:
            session_id = chat_response.get("session_id")
        
        # 9. Get messages for session
        if session_id:
            self.test_chat_get_messages(session_id)
        else:
            self.log_test("Chat Get Messages", False, "No session_id available from previous tests")
        
        # 10. Delete session
        if session_id:
            self.test_chat_delete_session(session_id)
        else:
            self.log_test("Chat Delete Session", False, "No session_id available from previous tests")
        
        # 11. Stop laser streaming
        self.test_laser_stop()
        
        # Summary
        self.print_summary()

    def print_summary(self):
        """Print test summary"""
        logger.info("=" * 80)
        logger.info("TEST SUMMARY")
        logger.info("=" * 80)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results if result["success"])
        failed_tests = total_tests - passed_tests
        
        logger.info(f"Total Tests: {total_tests}")
        logger.info(f"Passed: {passed_tests}")
        logger.info(f"Failed: {failed_tests}")
        logger.info("")
        
        if failed_tests > 0:
            logger.info("FAILED TESTS:")
            for result in self.test_results:
                if not result["success"]:
                    logger.info(f"❌ {result['test']}: {result['details']}")
            logger.info("")
        
        logger.info("ALL TESTS:")
        for result in self.test_results:
            status = "✅" if result["success"] else "❌"
            logger.info(f"{status} {result['test']}")
        
        return passed_tests, failed_tests


def main():
    """Main test execution"""
    tester = BeyondAPITester(BACKEND_URL)
    tester.run_full_test_sequence()
    
    passed, failed = tester.print_summary()
    
    # Exit with error code if any tests failed
    if failed > 0:
        sys.exit(1)
    else:
        logger.info("🎉 All tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()