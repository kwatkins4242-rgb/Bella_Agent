"""
MCP Client - Wrapper for all MCP API calls
Handles authentication and HTTP communication with MCP server
"""
import os
import requests
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)

class MCPClient:
    """Client for interacting with MCP server endpoints"""
    
    def __init__(self):
        self.base_url = os.getenv("MCP_URL", os.getenv("MCP_HOST", "http://localhost:8099"))
        self.api_key = os.getenv("MCP_API_KEY", os.getenv("MCP_KEY", ""))
        self.headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json"
        }
    
    def call_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call any MCP tool by name with parameters
        
        Args:
            tool_name: One of: memory_read, memory_write, file_read, file_write, 
                      shell_run, web_search, vision_analyze
            params: Tool-specific parameters
        
        Returns:
            Tool result as dictionary
        """
        endpoint = f"{self.base_url}/tools/{tool_name}"
        
        try:
            response = requests.post(
                endpoint,
                headers=self.headers,
                json=params,
                timeout=60
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"MCP tool {tool_name} HTTP error: {e}")
            return {"status": "error", "error": f"HTTP {response.status_code}: {response.text}"}
        except Exception as e:
            logger.error(f"MCP tool {tool_name} failed: {e}")
            return {"status": "error", "error": str(e)}
    
    def memory_read(self, session_id: str, limit: int = 10) -> Dict[str, Any]:
        """Read from MongoDB memory via MCP"""
        return self.call_tool("memory_read", {"session_id": session_id, "limit": limit})
    
    def memory_write(self, content: str, session_id: str, importance: int = 5) -> Dict[str, Any]:
        """Write to MongoDB memory via MCP"""
        return self.call_tool("memory_write", {
            "content": content,
            "session_id": session_id,
            "importance": importance
        })
    
    def file_read(self, path: str) -> Dict[str, Any]:
        """Read file via MCP"""
        return self.call_tool("file_read", {"path": path})
    
    def file_write(self, path: str, content: str) -> Dict[str, Any]:
        """Write file via MCP"""
        return self.call_tool("file_write", {"path": path, "content": content})
    
    def shell_run(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        """Execute shell command via MCP"""
        return self.call_tool("shell_run", {"command": command, "timeout": timeout})
    
    def web_search(self, query: str) -> Dict[str, Any]:
        """Search web via MCP"""
        return self.call_tool("web_search", {"query": query})
    
    def vision_analyze(self, image_path: str, prompt: str = "Describe this image") -> Dict[str, Any]:
        """Analyze image via MCP vision"""
        return self.call_tool("vision_analyze", {"image_path": image_path, "prompt": prompt})
    
    def list_tools(self) -> List[Dict[str, str]]:
        """List all available tools"""
        try:
            response = requests.get(
                f"{self.base_url}/tools",
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json().get("tools", [])
        except Exception as e:
            logger.error(f"List tools failed: {e}")
            return []
