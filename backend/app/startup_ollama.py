#!/usr/bin/env python3
"""
OLLAMA Startup Manager
Ensures OLLAMA is running before the backend starts
"""
import subprocess
import time
import requests
import logging
import os
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ollama_startup")

class OllamaManager:
    def __init__(self):
        self.ollama_url = os.getenv('OLLAMA_URL', 'http://localhost:11434')
        self.model = os.getenv('OLLAMA_MODEL', 'llama2')
        self.max_retries = 30  # 30 seconds max wait
        
    def is_ollama_running(self):
        """Check if Ollama is responding"""
        try:
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=2)
            return response.status_code == 200
        except:
            return False
    
    def start_ollama(self):
        """Start Ollama service"""
        try:
            # Check if ollama is installed
            result = subprocess.run(['which', 'ollama'], capture_output=True, text=True)
            if result.returncode != 0:
                logger.error("Ollama is not installed. Please install it first.")
                logger.info("Install with: curl -fsSL https://ollama.ai/install.sh | sh")
                return False
            
            # Try to start ollama serve in background
            logger.info("Starting Ollama service...")
            subprocess.Popen(['ollama', 'serve'], 
                           stdout=subprocess.DEVNULL, 
                           stderr=subprocess.DEVNULL)
            
            # Give it a moment to start
            time.sleep(2)
            
            # Check if it started
            if self.is_ollama_running():
                logger.info("✅ Ollama service started successfully")
                return True
            else:
                logger.warning("Ollama service started but not responding yet")
                return False
                
        except Exception as e:
            logger.error(f"Failed to start Ollama: {e}")
            return False
    
    def ensure_model_exists(self):
        """Ensure the required model is available"""
        try:
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            if response.status_code == 200:
                models = response.json().get('models', [])
                model_names = [m.get('name', '').split(':')[0] for m in models]
                
                if self.model not in model_names:
                    logger.info(f"Model {self.model} not found. Pulling it...")
                    # Pull the model
                    response = requests.post(
                        f"{self.ollama_url}/api/pull",
                        json={"name": self.model},
                        stream=True,
                        timeout=None
                    )
                    
                    for line in response.iter_lines():
                        if line:
                            logger.info(f"Pulling model: {line.decode('utf-8')}")
                    
                    logger.info(f"✅ Model {self.model} pulled successfully")
                else:
                    logger.info(f"✅ Model {self.model} is available")
                return True
        except Exception as e:
            logger.error(f"Failed to ensure model exists: {e}")
            return False
    
    def wait_for_ollama(self):
        """Wait for Ollama to be ready"""
        for i in range(self.max_retries):
            if self.is_ollama_running():
                logger.info(f"✅ Ollama is running at {self.ollama_url}")
                return True
            
            if i == 0:
                logger.info("Waiting for Ollama to start...")
            elif i % 5 == 0:
                logger.info(f"Still waiting for Ollama... ({i} seconds)")
            
            time.sleep(1)
        
        logger.error(f"❌ Ollama did not start after {self.max_retries} seconds")
        return False
    
    def ensure_ollama_ready(self):
        """Main function to ensure Ollama is ready"""
        logger.info("=" * 60)
        logger.info("OLLAMA STARTUP CHECK")
        logger.info("=" * 60)
        
        # Check if already running
        if self.is_ollama_running():
            logger.info("✅ Ollama is already running")
            self.ensure_model_exists()
            return True
        
        # Try to start it
        logger.info("Ollama is not running. Attempting to start...")
        if self.start_ollama():
            # Wait for it to be ready
            if self.wait_for_ollama():
                self.ensure_model_exists()
                return True
        
        # If we can't start it, provide fallback mode info
        logger.warning("=" * 60)
        logger.warning("⚠️  OLLAMA NOT AVAILABLE - FALLBACK MODE ACTIVE")
        logger.warning("The app will work with limited AI capabilities")
        logger.warning("To enable full AI features:")
        logger.warning("1. Install Ollama: curl -fsSL https://ollama.ai/install.sh | sh")
        logger.warning("2. Start Ollama: ollama serve")
        logger.warning("3. Pull a model: ollama pull llama2")
        logger.warning("=" * 60)
        return False

def main():
    """Main entry point"""
    manager = OllamaManager()
    success = manager.ensure_ollama_ready()
    
    # Return appropriate exit code
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()