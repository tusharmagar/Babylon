#!/usr/bin/env python3
"""
Backend API Testing for Pangolin BEYOND Control App
Tests all API endpoints for the laser control system
"""

import requests
import sys
import json
from datetime import datetime
from typing import Dict, Any, List

class BeyondAPITester:
    def __init__(self, base_url="https://pangolin-ai-builder.preview.emergentagent.com"):
        self.base_url = base_url
        self.api_url = f"{base_url}/api"
        self.tests_run = 0
        self.tests_passed = 0
        self.test_results = []
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})

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
                 data: Dict = None, expected_fields: List[str] = None) -> bool:
        """Run a single API test"""
        url = f"{self.api_url}/{endpoint}"
        
        try:
            if method == 'GET':
                response = self.session.get(url)
            elif method == 'POST':
                response = self.session.post(url, json=data)
            elif method == 'DELETE':
                response = self.session.delete(url)
            else:
                self.log_test(name, False, f"Unsupported method: {method}")
                return False

            success = response.status_code == expected_status
            
            if success:
                try:
                    response_json = response.json()
                    
                    # Check for expected fields if provided
                    if expected_fields:
                        missing_fields = [field for field in expected_fields if field not in response_json]
                        if missing_fields:
                            self.log_test(name, False, f"Missing fields: {missing_fields}", response_json)
                            return False
                    
                    self.log_test(name, True, f"Status: {response.status_code}", response_json)
                    return True
                except json.JSONDecodeError:
                    self.log_test(name, False, f"Invalid JSON response, Status: {response.status_code}", response.text)
                    return False
            else:
                try:
                    error_data = response.json()
                except:
                    error_data = response.text
                self.log_test(name, False, f"Expected {expected_status}, got {response.status_code}", error_data)
                return False

        except requests.exceptions.RequestException as e:
            self.log_test(name, False, f"Request failed: {str(e)}")
            return False

    def test_root_endpoint(self):
        """Test the root API endpoint"""
        return self.run_test(
            "Root API Endpoint",
            "GET", 
            "",
            200,
            expected_fields=["message"]
        )

    def test_status_endpoint(self):
        """Test connection status endpoint"""
        return self.run_test(
            "Status Endpoint",
            "GET",
            "status",
            200,
            expected_fields=["connected", "host", "port", "echo_mode"]
        )

    def test_config_get(self):
        """Test get configuration endpoint"""
        return self.run_test(
            "Get Config Endpoint",
            "GET",
            "config",
            200,
            expected_fields=["host", "port", "timeout"]
        )

    def test_config_save(self):
        """Test save configuration endpoint"""
        config_data = {
            "host": "test.ngrok.io",
            "port": 16063,
            "timeout": 5.0
        }
        return self.run_test(
            "Save Config Endpoint",
            "POST",
            "config",
            200,
            data=config_data,
            expected_fields=["success", "config"]
        )

    def test_connect_endpoint(self):
        """Test connection endpoint (will fail due to no real server)"""
        connect_data = {
            "host": "fake.ngrok.io",
            "port": 16063,
            "timeout": 2.0
        }
        # This should return 503 since no real BEYOND server exists
        return self.run_test(
            "Connect Endpoint (Expected Failure)",
            "POST",
            "connect",
            503,  # Expected to fail
            data=connect_data
        )

    def test_disconnect_endpoint(self):
        """Test disconnect endpoint"""
        return self.run_test(
            "Disconnect Endpoint",
            "POST",
            "disconnect",
            200,
            expected_fields=["success", "message"]
        )

    def test_cue_start_endpoint(self):
        """Test start cue endpoint (will fail if not connected)"""
        cue_data = {
            "page": 1,
            "cue": 5
        }
        return self.run_test(
            "Start Cue Endpoint",
            "POST",
            "cue/start",
            200,
            data=cue_data,
            expected_fields=["success"]
        )

    def test_stop_all_endpoint(self):
        """Test stop all endpoint"""
        return self.run_test(
            "Stop All Endpoint",
            "POST",
            "stop-all",
            200,
            expected_fields=["success"]
        )

    def test_blackout_on_endpoint(self):
        """Test blackout on endpoint"""
        return self.run_test(
            "Blackout On Endpoint",
            "POST",
            "blackout/on",
            200,
            expected_fields=["success"]
        )

    def test_blackout_off_endpoint(self):
        """Test blackout off endpoint"""
        return self.run_test(
            "Blackout Off Endpoint",
            "POST",
            "blackout/off",
            200,
            expected_fields=["success"]
        )

    def test_logs_endpoint(self):
        """Test logs endpoint"""
        return self.run_test(
            "Logs Endpoint",
            "GET",
            "logs",
            200,
            expected_fields=["logs"]
        )

    def test_clear_logs_endpoint(self):
        """Test clear logs endpoint"""
        return self.run_test(
            "Clear Logs Endpoint",
            "DELETE",
            "logs",
            200,
            expected_fields=["success", "message"]
        )

    def run_all_tests(self):
        """Run all API tests"""
        print(f"🚀 Starting BEYOND Control API Tests")
        print(f"📡 Testing against: {self.api_url}")
        print("=" * 60)

        # Basic endpoints
        self.test_root_endpoint()
        self.test_status_endpoint()
        
        # Configuration endpoints
        self.test_config_get()
        self.test_config_save()
        
        # Connection endpoints
        self.test_connect_endpoint()  # Expected to fail
        self.test_disconnect_endpoint()
        
        # Command endpoints
        self.test_cue_start_endpoint()
        self.test_stop_all_endpoint()
        
        # Blackout endpoints
        self.test_blackout_on_endpoint()
        self.test_blackout_off_endpoint()
        
        # Logs endpoints
        self.test_logs_endpoint()
        self.test_clear_logs_endpoint()

        print("=" * 60)
        print(f"📊 Test Results: {self.tests_passed}/{self.tests_run} passed")
        
        if self.tests_passed == self.tests_run:
            print("🎉 All tests passed!")
            return 0
        else:
            print("⚠️  Some tests failed - see details above")
            return 1

    def get_test_summary(self):
        """Get summary of test results"""
        failed_tests = [test for test in self.test_results if not test["success"]]
        passed_tests = [test for test in self.test_results if test["success"]]
        
        return {
            "total_tests": self.tests_run,
            "passed_tests": self.tests_passed,
            "failed_tests": len(failed_tests),
            "success_rate": (self.tests_passed / self.tests_run * 100) if self.tests_run > 0 else 0,
            "passed_test_names": [test["test_name"] for test in passed_tests],
            "failed_test_names": [test["test_name"] for test in failed_tests],
            "detailed_results": self.test_results
        }


def main():
    """Main test execution"""
    tester = BeyondAPITester()
    exit_code = tester.run_all_tests()
    
    # Save detailed results for analysis
    summary = tester.get_test_summary()
    with open('/tmp/backend_test_results.json', 'w') as f:
        json.dump(summary, f, indent=2)
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())