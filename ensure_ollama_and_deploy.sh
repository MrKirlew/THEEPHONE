#!/bin/bash

echo "========================================"
echo "KIRLEW AI DEPLOYMENT WITH OLLAMA CHECK"
echo "========================================"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to check if OLLAMA is running
check_ollama() {
    echo -e "${YELLOW}Checking OLLAMA status...${NC}"
    
    if ! command_exists ollama; then
        echo -e "${RED}❌ OLLAMA is not installed${NC}"
        echo "To install OLLAMA, run:"
        echo "curl -fsSL https://ollama.ai/install.sh | sh"
        return 1
    fi
    
    # Check if ollama is running
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo -e "${GREEN}✅ OLLAMA is running${NC}"
        
        # Check if llama2 model exists
        if ollama list | grep -q "llama2"; then
            echo -e "${GREEN}✅ llama2 model is available${NC}"
        else
            echo -e "${YELLOW}⚠️ llama2 model not found. Pulling it now...${NC}"
            ollama pull llama2
            echo -e "${GREEN}✅ llama2 model pulled successfully${NC}"
        fi
        return 0
    else
        echo -e "${YELLOW}⚠️ OLLAMA is not running. Starting it...${NC}"
        # Start ollama in background
        nohup ollama serve > /dev/null 2>&1 &
        sleep 3
        
        # Check again
        if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
            echo -e "${GREEN}✅ OLLAMA started successfully${NC}"
            
            # Pull llama2 if needed
            if ! ollama list | grep -q "llama2"; then
                echo -e "${YELLOW}Pulling llama2 model...${NC}"
                ollama pull llama2
                echo -e "${GREEN}✅ llama2 model ready${NC}"
            fi
            return 0
        else
            echo -e "${RED}❌ Failed to start OLLAMA${NC}"
            return 1
        fi
    fi
}

# Function to start backend
start_backend() {
    echo -e "${YELLOW}Starting backend...${NC}"
    
    cd backend/app
    
    # Check if virtual environment exists
    if [ ! -d "../venv" ]; then
        echo "Creating virtual environment..."
        python3 -m venv ../venv
        source ../venv/bin/activate
        pip install -r requirements.txt
    else
        source ../venv/bin/activate
    fi
    
    # Kill any existing backend process
    pkill -f "python.*main.py" || true
    
    # Start backend with OLLAMA configuration
    export OLLAMA_URL="http://localhost:11434"
    export OLLAMA_MODEL="llama2"
    export PORT=8080
    
    echo -e "${YELLOW}Starting backend on port 8080...${NC}"
    nohup python main.py > ../backend.log 2>&1 &
    
    sleep 3
    
    # Check if backend is running
    if curl -s http://localhost:8080/health > /dev/null 2>&1; then
        echo -e "${GREEN}✅ Backend is running${NC}"
        
        # Check OLLAMA connection from backend
        OLLAMA_STATUS=$(curl -s http://localhost:8080/ollama/status | grep -o '"ollama_available":[^,}]*' | cut -d':' -f2)
        if [ "$OLLAMA_STATUS" = "true" ]; then
            echo -e "${GREEN}✅ Backend connected to OLLAMA${NC}"
        else
            echo -e "${YELLOW}⚠️ Backend running in fallback mode (OLLAMA not connected)${NC}"
        fi
    else
        echo -e "${RED}❌ Failed to start backend${NC}"
        echo "Check backend/backend.log for errors"
        return 1
    fi
    
    cd ../..
}

# Function to deploy mobile app
deploy_mobile() {
    echo -e "${YELLOW}Deploying mobile app...${NC}"
    
    cd adk_mobile_app
    
    # Get dependencies
    echo "Getting Flutter dependencies..."
    flutter pub get
    
    # Check if device is connected
    if ! flutter devices | grep -q "connected"; then
        echo -e "${RED}❌ No device connected${NC}"
        echo "Please connect your Android device with USB debugging enabled"
        return 1
    fi
    
    # Build and install
    echo -e "${YELLOW}Building and installing app...${NC}"
    flutter run --release
    
    cd ..
}

# Main execution
main() {
    echo ""
    echo "Starting deployment process..."
    echo ""
    
    # Step 1: Check and start OLLAMA
    if ! check_ollama; then
        echo -e "${YELLOW}⚠️ Continuing without OLLAMA (limited AI features)${NC}"
    fi
    
    echo ""
    
    # Step 2: Start backend
    if ! start_backend; then
        echo -e "${RED}❌ Backend deployment failed${NC}"
        exit 1
    fi
    
    echo ""
    
    # Step 3: Deploy mobile app
    echo "Do you want to deploy the mobile app now? (y/n)"
    read -r response
    if [[ "$response" == "y" ]]; then
        deploy_mobile
    else
        echo -e "${YELLOW}Skipping mobile deployment${NC}"
        echo "Backend is running at: http://localhost:8080"
        echo "To deploy mobile app later, run: cd adk_mobile_app && flutter run"
    fi
    
    echo ""
    echo "========================================"
    echo -e "${GREEN}DEPLOYMENT COMPLETE${NC}"
    echo "========================================"
    echo ""
    echo "Backend URL: http://localhost:8080"
    echo "Backend logs: tail -f backend/backend.log"
    echo ""
    
    if curl -s http://localhost:8080/ollama/status | grep -q '"ollama_available":true'; then
        echo -e "${GREEN}✅ All features are active (OLLAMA connected)${NC}"
    else
        echo -e "${YELLOW}⚠️ Running in fallback mode (basic features only)${NC}"
        echo "To enable AI features:"
        echo "1. Install OLLAMA: curl -fsSL https://ollama.ai/install.sh | sh"
        echo "2. Start OLLAMA: ollama serve"
        echo "3. Pull model: ollama pull llama2"
    fi
}

# Run main function
main