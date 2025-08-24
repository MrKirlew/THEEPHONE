#!/usr/bin/env python3
"""
Test all features mentioned in BEAUTIFULPLANUI.TXT
"""
import requests
import json
import time
from datetime import datetime, timedelta

# Backend URL from BEAUTIFULPLANUI.TXT
BACKEND_URL = "https://klai-backend-full-843267258954.us-central1.run.app"

# Test locally if backend is running locally
import sys
if len(sys.argv) > 1 and sys.argv[1] == "--local":
    BACKEND_URL = "http://localhost:8080"
    print("Testing with local backend")

class FeatureTester:
    def __init__(self):
        self.backend_url = BACKEND_URL
        self.passed_tests = []
        self.failed_tests = []
        
    def test_health(self):
        """Test backend health endpoint"""
        try:
            response = requests.get(f"{self.backend_url}/health", timeout=5)
            if response.status_code == 200:
                self.passed_tests.append("✅ Backend health check")
                return True
            else:
                self.failed_tests.append("❌ Backend health check")
                return False
        except Exception as e:
            self.failed_tests.append(f"❌ Backend health check: {e}")
            return False
    
    def test_ollama_status(self):
        """Test OLLAMA connection status"""
        try:
            response = requests.get(f"{self.backend_url}/ollama/status", timeout=5)
            data = response.json()
            if data.get('ollama_available'):
                self.passed_tests.append("✅ OLLAMA is connected")
            else:
                self.passed_tests.append("⚠️ OLLAMA not available (fallback mode active)")
            return True
        except Exception as e:
            self.failed_tests.append(f"❌ OLLAMA status check: {e}")
            return False
    
    def test_chat_basic(self):
        """Test basic chat without authentication"""
        try:
            payload = {
                "user_id": "test_user",
                "session_id": "test_session",
                "message": "Hello, how are you?"
            }
            response = requests.post(f"{self.backend_url}/chat", json=payload, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if 'response' in data:
                    self.passed_tests.append("✅ Basic chat (no auth)")
                    return True
            self.failed_tests.append("❌ Basic chat failed")
            return False
        except Exception as e:
            self.failed_tests.append(f"❌ Basic chat: {e}")
            return False
    
    def test_calendar_detection(self):
        """Test calendar query detection"""
        try:
            payload = {
                "user_id": "test_user",
                "session_id": "test_session",
                "message": "What's on my calendar today?"
            }
            response = requests.post(f"{self.backend_url}/chat", json=payload, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # Should either ask for auth or recognize as calendar request
                if 'auth_required' in data or 'calendar' in str(data).lower():
                    self.passed_tests.append("✅ Calendar detection")
                    return True
            self.failed_tests.append("❌ Calendar detection failed")
            return False
        except Exception as e:
            self.failed_tests.append(f"❌ Calendar detection: {e}")
            return False
    
    def test_sms_detection(self):
        """Test SMS command detection"""
        try:
            payload = {
                "user_id": "test_user",
                "session_id": "test_session",
                "message": "Text John saying I'll be late"
            }
            response = requests.post(f"{self.backend_url}/chat", json=payload, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # Should recognize SMS intent
                if 'sms' in str(data).lower() or 'text' in str(data).lower() or 'message' in str(data).lower():
                    self.passed_tests.append("✅ SMS detection")
                    return True
            self.failed_tests.append("❌ SMS detection failed")
            return False
        except Exception as e:
            self.failed_tests.append(f"❌ SMS detection: {e}")
            return False
    
    def test_google_services(self):
        """Test Google services intent classification"""
        services = [
            ("Create a new document", "docs"),
            ("Send an email to someone", "gmail"),
            ("Upload a file to drive", "drive"),
            ("Create a spreadsheet", "sheets"),
            ("Find my contacts named Sarah", "contacts"),
            ("Create a new presentation", "slides"),
            ("Create a feedback form", "forms"),
            ("Add a task to my list", "tasks")
        ]
        
        all_passed = True
        for message, expected_service in services:
            try:
                payload = {
                    "user_id": "test_user",
                    "session_id": "test_session",
                    "message": message
                }
                response = requests.post(f"{self.backend_url}/chat", json=payload, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    response_text = str(data).lower()
                    if expected_service in response_text or 'auth_required' in data:
                        continue  # This service check passed
                    else:
                        all_passed = False
                        self.failed_tests.append(f"❌ {expected_service} detection")
                else:
                    all_passed = False
                    self.failed_tests.append(f"❌ {expected_service} request failed")
            except Exception as e:
                all_passed = False
                self.failed_tests.append(f"❌ {expected_service}: {e}")
        
        if all_passed:
            self.passed_tests.append("✅ All Google services detection")
        return all_passed
    
    def test_fallback_responses(self):
        """Test fallback responses when OLLAMA is unavailable"""
        test_messages = [
            "hello",
            "help",
            "what can you do",
            "thank you",
            "bye"
        ]
        
        all_passed = True
        for message in test_messages:
            try:
                payload = {
                    "user_id": "test_user",
                    "session_id": "test_session",
                    "message": message
                }
                response = requests.post(f"{self.backend_url}/chat", json=payload, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if 'response' in data and len(data['response']) > 0:
                        continue  # Got a response
                    else:
                        all_passed = False
                        self.failed_tests.append(f"❌ No fallback for: {message}")
                else:
                    all_passed = False
            except Exception as e:
                all_passed = False
                self.failed_tests.append(f"❌ Fallback response: {e}")
        
        if all_passed:
            self.passed_tests.append("✅ Fallback responses working")
        return all_passed
    
    def run_all_tests(self):
        """Run all feature tests"""
        print("=" * 60)
        print("TESTING ALL FEATURES FROM BEAUTIFULPLANUI.TXT")
        print("=" * 60)
        print(f"Backend URL: {self.backend_url}")
        print()
        
        # Run tests
        print("Running tests...")
        self.test_health()
        self.test_ollama_status()
        self.test_chat_basic()
        self.test_calendar_detection()
        self.test_sms_detection()
        self.test_google_services()
        self.test_fallback_responses()
        
        # Print results
        print()
        print("=" * 60)
        print("TEST RESULTS")
        print("=" * 60)
        
        if self.passed_tests:
            print("\nPASSED TESTS:")
            for test in self.passed_tests:
                print(f"  {test}")
        
        if self.failed_tests:
            print("\nFAILED TESTS:")
            for test in self.failed_tests:
                print(f"  {test}")
        
        print()
        print("=" * 60)
        total = len(self.passed_tests) + len(self.failed_tests)
        print(f"SUMMARY: {len(self.passed_tests)}/{total} tests passed")
        
        if len(self.failed_tests) == 0:
            print("🎉 ALL TESTS PASSED!")
        elif len(self.passed_tests) > len(self.failed_tests):
            print("⚠️ Most tests passed, but some features need attention")
        else:
            print("❌ Multiple features are not working properly")
        print("=" * 60)

def main():
    tester = FeatureTester()
    tester.run_all_tests()

if __name__ == "__main__":
    main()