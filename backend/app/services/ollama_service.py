"""
Ollama Service Integration
Handles communication with the local Ollama instance
"""
import aiohttp
import json
import logging
from typing import AsyncGenerator, Optional, Dict, Any

logger = logging.getLogger(__name__)

class OllamaService:
    """
    Service for interacting with Ollama API.
    """
    
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama2"):
        """
        Initialize Ollama service.
        
        Args:
            base_url: The base URL for Ollama API
            model: The default model to use
        """
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.session = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def generate(self, prompt: str, context: Optional[str] = None, 
                      stream: bool = True, **kwargs) -> AsyncGenerator[str, None]:
        """
        Generate a response from Ollama.
        
        Args:
            prompt: The user's prompt
            context: Optional context to include
            stream: Whether to stream the response
            **kwargs: Additional parameters for Ollama
            
        Yields:
            Response chunks if streaming, otherwise returns full response
        """
        session = await self._get_session()
        
        # Prepare the request payload
        payload = {
            "model": kwargs.get("model", self.model),
            "prompt": prompt,
            "stream": stream
        }
        
        # Add context if provided
        if context:
            payload["context"] = context
        
        # Add any additional parameters
        for key in ["temperature", "top_p", "top_k", "num_predict", "stop"]:
            if key in kwargs:
                payload[key] = kwargs[key]
        
        try:
            url = f"{self.base_url}/api/generate"
            logger.info(f"Sending request to Ollama: {url}")
            
            async with session.post(url, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Ollama API error: {response.status} - {error_text}")
                    yield f"Error: Ollama returned status {response.status}"
                    return
                
                if stream:
                    async for line in response.content:
                        if line:
                            try:
                                data = json.loads(line)
                                if "response" in data:
                                    yield data["response"]
                                if data.get("done", False):
                                    break
                            except json.JSONDecodeError:
                                logger.warning(f"Failed to decode JSON: {line}")
                else:
                    text = await response.text()
                    data = json.loads(text)
                    yield data.get("response", "")
                    
        except aiohttp.ClientError as e:
            logger.error(f"Connection error with Ollama: {e}")
            yield f"Error: Could not connect to Ollama at {self.base_url}. Is Ollama running?"
        except Exception as e:
            logger.error(f"Unexpected error with Ollama: {e}")
            yield f"Error: {str(e)}"
    
    async def chat(self, messages: list, stream: bool = True, **kwargs) -> AsyncGenerator[str, None]:
        """
        Chat with Ollama using conversation history.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content'
            stream: Whether to stream the response
            **kwargs: Additional parameters for Ollama
            
        Yields:
            Response chunks if streaming, otherwise returns full response
        """
        session = await self._get_session()
        
        # Prepare the request payload
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "stream": stream
        }
        
        # Add any additional parameters
        for key in ["temperature", "top_p", "top_k", "num_predict", "stop"]:
            if key in kwargs:
                payload[key] = kwargs[key]
        
        try:
            url = f"{self.base_url}/api/chat"
            logger.info(f"Sending chat request to Ollama: {url}")
            
            async with session.post(url, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Ollama API error: {response.status} - {error_text}")
                    yield f"Error: Ollama returned status {response.status}"
                    return
                
                if stream:
                    async for line in response.content:
                        if line:
                            try:
                                data = json.loads(line)
                                if "message" in data and "content" in data["message"]:
                                    yield data["message"]["content"]
                                if data.get("done", False):
                                    break
                            except json.JSONDecodeError:
                                logger.warning(f"Failed to decode JSON: {line}")
                else:
                    text = await response.text()
                    data = json.loads(text)
                    if "message" in data and "content" in data["message"]:
                        yield data["message"]["content"]
                    
        except aiohttp.ClientError as e:
            logger.error(f"Connection error with Ollama: {e}")
            yield f"Error: Could not connect to Ollama at {self.base_url}. Is Ollama running?"
        except Exception as e:
            logger.error(f"Unexpected error with Ollama: {e}")
            yield f"Error: {str(e)}"
    
    async def list_models(self) -> Dict[str, Any]:
        """
        List available models in Ollama.
        
        Returns:
            Dictionary containing available models
        """
        session = await self._get_session()
        
        try:
            url = f"{self.base_url}/api/tags"
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"Failed to list models: {response.status}")
                    return {"error": f"Failed to list models: {response.status}"}
        except Exception as e:
            logger.error(f"Error listing models: {e}")
            return {"error": str(e)}
    
    async def pull_model(self, model_name: str) -> AsyncGenerator[str, None]:
        """
        Pull a model from Ollama library.
        
        Args:
            model_name: Name of the model to pull
            
        Yields:
            Status updates during model download
        """
        session = await self._get_session()
        
        try:
            url = f"{self.base_url}/api/pull"
            payload = {"name": model_name}
            
            async with session.post(url, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    yield f"Error pulling model: {error_text}"
                    return
                
                async for line in response.content:
                    if line:
                        try:
                            data = json.loads(line)
                            status = data.get("status", "")
                            if status:
                                yield status
                        except json.JSONDecodeError:
                            pass
                            
        except Exception as e:
            logger.error(f"Error pulling model: {e}")
            yield f"Error: {str(e)}"
    
    async def health_check(self) -> bool:
        """
        Check if Ollama service is running and accessible.
        
        Returns:
            True if service is healthy, False otherwise
        """
        session = await self._get_session()
        
        try:
            url = f"{self.base_url}/api/tags"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                return response.status == 200
        except:
            return False
    
    async def close(self):
        """Close the aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()