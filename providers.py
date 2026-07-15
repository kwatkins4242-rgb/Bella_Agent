"""
Provider Management System
Handles dynamic switching between AI providers based on providers.json
"""
import os
import json
import logging
from typing import Dict, Any, Optional, List
import anthropic
import openai
from groq import Groq

logger = logging.getLogger(__name__)

class ProviderManager:
    """Manages AI provider routing and configuration"""
    
    def __init__(self, config_path: str = "providers.json"):
        self.config_path = config_path
        self.providers_config = self._load_config()
        self.active_provider = os.getenv("ACTIVE_PROVIDER", self.providers_config.get("default_provider", "openai"))
    
    def _load_config(self) -> Dict[str, Any]:
        """Load providers configuration from JSON file"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    return json.load(f)
            elif os.path.exists("providers_.json"):
                with open("providers_.json", 'r') as f:
                    return json.load(f)
            else:
                logger.error("No providers config found")
                return {"providers": {}, "default_provider": "openai"}
        except Exception as e:
            logger.error(f"Failed to load providers config: {e}")
            return {"providers": {}, "default_provider": "openai"}
    
    def get_provider_config(self, provider_name: Optional[str] = None) -> Dict[str, Any]:
        """Get configuration for specified provider"""
        provider = provider_name or self.active_provider
        return self.providers_config.get("providers", {}).get(provider, {})
    
    def set_active_provider(self, provider_name: str) -> bool:
        """Change active provider"""
        if provider_name in self.providers_config.get("providers", {}):
            self.active_provider = provider_name
            logger.info(f"Switched to provider: {provider_name}")
            return True
        logger.error(f"Provider not found: {provider_name}")
        return False
    
    def get_api_key(self, provider_config: Dict[str, Any]) -> Optional[str]:
        """Extract API key from environment based on provider config"""
        auth = provider_config.get("auth", {})
        env_var = auth.get("env")
        
        if isinstance(env_var, list):
            # AWS Bedrock style with multiple keys
            keys = {var: os.getenv(var) for var in env_var}
            return keys if any(keys.values()) else None
        elif isinstance(env_var, str):
            return os.getenv(env_var)
        return None
    
    def chat(self, messages: List[Dict[str, str]], model: Optional[str] = None, 
             provider: Optional[str] = None, max_tokens: int = 4000, 
             temperature: float = 0.7) -> Dict[str, Any]:
        """
        Send chat completion request to active provider
        Automatically routes to the correct API based on provider configuration
        """
        provider_name = provider or self.active_provider
        config = self.get_provider_config(provider_name)
        
        if not config:
            return {"error": f"Provider {provider_name} not configured"}
        
        provider_type = config.get("type", provider_name)
        api_key = self.get_api_key(config)
        
        if not api_key and config.get("type", provider_name) not in ["ollama"]:
            return {"error": f"API key not found for {provider_name}"}
        
        # Get model from config or use provided
        if not model:
            chat_models = config.get("models", {}).get("chat", [])
            model = chat_models[0] if chat_models else "default"
        
        try:
            # Route to appropriate provider implementation
            if provider_type == "anthropic":
                return self._chat_anthropic(messages, model, api_key, max_tokens, temperature)
            elif provider_type in ["openai", "groq", "deepseek", "moonshot", "openrouter", "ollama", 
                                   "together", "fireworks", "deepinfra", "nvidia", "qwen", "vultr"]:
                return self._chat_openai_compatible(messages, model, api_key, config, max_tokens, temperature)
            elif provider_type == "google":
                return self._chat_google(messages, model, api_key, max_tokens, temperature)
            else:
                # Generic OpenAI-compatible fallback
                return self._chat_openai_compatible(messages, model, api_key, config, max_tokens, temperature)
        
        except Exception as e:
            logger.error(f"Chat failed for {provider_name}: {e}")
            return {"error": str(e)}
    
    def _chat_anthropic(self, messages: List[Dict[str, str]], model: str, 
                       api_key: str, max_tokens: int, temperature: float) -> Dict[str, Any]:
        """Handle Anthropic-specific chat completion"""
        try:
            client = anthropic.Anthropic(api_key=api_key)
            
            # Convert messages format
            system_msg = ""
            converted_messages = []
            for msg in messages:
                if msg.get("role") == "system":
                    system_msg = msg.get("content", "")
                else:
                    converted_messages.append({
                        "role": msg.get("role", "user"),
                        "content": msg.get("content", "")
                    })
            
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_msg if system_msg else anthropic.NOT_GIVEN,
                messages=converted_messages
            )
            
            return {
                "content": response.content[0].text,
                "model": model,
                "provider": "anthropic",
                "usage": {
                    "prompt_tokens": response.usage.input_tokens,
                    "completion_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.input_tokens + response.usage.output_tokens
                }
            }
        except Exception as e:
            logger.error(f"Anthropic chat failed: {e}")
            return {"error": str(e)}
    
    def _chat_openai_compatible(self, messages: List[Dict[str, str]], model: str, 
                                api_key: str, config: Dict[str, Any], 
                                max_tokens: int, temperature: float) -> Dict[str, Any]:
        """Handle OpenAI-compatible chat completion"""
        try:
            base_url = config.get("base_url", "https://api.openai.com/v1")
            
            client = openai.OpenAI(
                api_key=api_key or "ollama",
                base_url=base_url
            )
            
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature
            )
            
            return {
                "content": response.choices[0].message.content,
                "model": model,
                "provider": config.get("label", "unknown"),
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            }
        except Exception as e:
            logger.error(f"OpenAI-compatible chat failed: {e}")
            return {"error": str(e)}
    
    def _chat_google(self, messages: List[Dict[str, str]], model: str, 
                     api_key: str, max_tokens: int, temperature: float) -> Dict[str, Any]:
        """Handle Google Gemini chat completion"""
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            
            # Convert messages to Gemini format
            gemini_messages = []
            for msg in messages:
                role = "user" if msg.get("role") in ["user", "system"] else "model"
                gemini_messages.append({
                    "role": role,
                    "parts": [msg.get("content", "")]
                })
            
            model_obj = genai.GenerativeModel(model)
            response = model_obj.generate_content(
                gemini_messages,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=max_tokens,
                    temperature=temperature
                )
            )
            
            return {
                "content": response.text,
                "model": model,
                "provider": "google",
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                }
            }
        except Exception as e:
            logger.error(f"Google chat failed: {e}")
            return {"error": str(e)}
    
    def list_providers(self) -> List[str]:
        """List all available providers"""
        return list(self.providers_config.get("providers", {}).keys())
    
    def get_provider_capabilities(self, provider_name: Optional[str] = None) -> Dict[str, bool]:
        """Get capabilities of specified provider"""
        config = self.get_provider_config(provider_name)
        return config.get("capabilities", {})
