"""
Configuration management for Gemini 2.5 Pro submittal extractor.
Replaces the LlamaCloud-specific config.py with OpenRouter/Gemini settings.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

@dataclass
class OpenRouterConfig:
    """Configuration for OpenRouter API integration."""
    api_key: str = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY", ""))
    base_url: str = field(default_factory=lambda: os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"))
    model_name: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL_NAME", "google/gemini-2.5-pro"))
    
    # Model parameters
    temperature: float = field(default_factory=lambda: float(os.getenv("TEMPERATURE", "0.1")))
    max_tokens: int = field(default_factory=lambda: int(os.getenv("MAX_TOKENS_PER_REQUEST", "8192")))
    max_context_tokens: int = field(default_factory=lambda: int(os.getenv("MAX_CONTEXT_TOKENS", "2000000")))
    max_retries: int = field(default_factory=lambda: int(os.getenv("MAX_RETRIES", "3")))
    request_timeout: int = field(default_factory=lambda: int(os.getenv("REQUEST_TIMEOUT", "300")))
    
    # Cost management
    cost_alert_threshold: float = field(default_factory=lambda: float(os.getenv("COST_ALERT_THRESHOLD", "10.00")))
    daily_cost_limit: float = field(default_factory=lambda: float(os.getenv("DAILY_COST_LIMIT", "50.00")))
    
    def __post_init__(self):
        if not self.api_key:
            raise ValueError(
                "OPENROUTER_API_KEY environment variable is required. "
                "Please set it in your .env file or environment."
            )

@dataclass
class OutputConfig:
    """Configuration for output generation."""
    output_dir: str = field(default_factory=lambda: os.getenv("OUTPUT_DIR", "output"))
    json_backup: bool = field(default_factory=lambda: os.getenv("JSON_BACKUP", "true").lower() == "true")
    timestamp_files: bool = field(default_factory=lambda: os.getenv("TIMESTAMP_FILES", "true").lower() == "true")
    excel_template: Optional[str] = field(default_factory=lambda: os.getenv("EXCEL_TEMPLATE"))
    
    def __post_init__(self):
        # Create output directory if it doesn't exist
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

@dataclass
class ProcessingConfig:
    """Configuration for processing options."""
    enable_validation: bool = field(default_factory=lambda: os.getenv("ENABLE_VALIDATION", "true").lower() == "true")
    save_intermediate_results: bool = field(default_factory=lambda: os.getenv("SAVE_INTERMEDIATE", "true").lower() == "true")
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    max_bullets_per_article: int = field(default_factory=lambda: int(os.getenv("MAX_BULLETS", "1000")))

@dataclass
class GeminiConfig:
    """Main configuration class for Gemini 2.5 Pro extractor."""
    openrouter: OpenRouterConfig = field(default_factory=OpenRouterConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    
    # Schema and prompt files
    schema_file: str = field(default_factory=lambda: os.getenv("SCHEMA_FILE", "submittal_extraction_schema.json"))
    system_prompt_file: str = field(default_factory=lambda: os.getenv("SYSTEM_PROMPT_FILE", "system_prompt_for_llama_agent.md"))
    
    def __post_init__(self):
        # Validate required files exist
        schema_path = Path(self.schema_file)
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {self.schema_file}")
        
        prompt_path = Path(self.system_prompt_file)
        if not prompt_path.exists():
            raise FileNotFoundError(f"System prompt file not found: {self.system_prompt_file}")
    
    def validate(self) -> bool:
        """Validate configuration."""
        try:
            # Check OpenRouter configuration
            if not self.openrouter.api_key:
                return False
            
            # Check required files
            if not Path(self.schema_file).exists():
                return False
            
            if not Path(self.system_prompt_file).exists():
                return False
            
            return True
            
        except Exception:
            return False

# Global configuration instance
_config: Optional[GeminiConfig] = None

def get_config() -> GeminiConfig:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = GeminiConfig()
    return _config

def load_config_from_env() -> GeminiConfig:
    """Load configuration from environment variables."""
    return GeminiConfig()

def reset_config():
    """Reset the global configuration (useful for testing)."""
    global _config
    _config = None

if __name__ == "__main__":
    # Test configuration loading
    try:
        config = get_config()
        print("✅ Configuration loaded successfully!")
        print(f"🎯 Model: {config.openrouter.model_name}")
        print(f"🌐 Base URL: {config.openrouter.base_url}")
        print(f"📁 Output dir: {config.output.output_dir}")
        print(f"📋 Schema file: {config.schema_file}")
        print(f"📝 System prompt: {config.system_prompt_file}")
        
        if config.validate():
            print("✅ Configuration validation passed!")
        else:
            print("❌ Configuration validation failed!")
            
    except Exception as e:
        print(f"❌ Configuration loading failed: {e}")