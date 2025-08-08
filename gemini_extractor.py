"""
Gemini 2.5 Pro extractor for submittal requirements using OpenRouter API.
Replaces LlamaCloud's document extraction service.
"""
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
import logging
import time

import openai
import pdfplumber
from tenacity import retry, stop_after_attempt, wait_exponential
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up logging
logger = logging.getLogger(__name__)

class ExtractionError(Exception):
    """Custom exception for extraction errors."""
    pass

class TokenUsage(BaseModel):
    """Model for tracking token usage and costs."""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    input_cost: float
    output_cost: float
    total_cost: float

class ExtractionResult(BaseModel):
    """Model for extraction results."""
    data: Dict[str, Any]
    token_usage: TokenUsage
    processing_time: float
    model_used: str
    timestamp: str

class GeminiExtractor:
    """
    Gemini 2.5 Pro extractor for submittal requirements.
    Replaces LlamaCloud's LlamaExtract with OpenRouter API.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize the Gemini extractor with OpenRouter API."""
        
        # Load configuration
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        self.model_name = os.getenv("GEMINI_MODEL_NAME", "google/gemini-2.5-pro")
        
        # Model parameters
        self.temperature = float(os.getenv("TEMPERATURE", "0.1"))
        self.max_tokens = int(os.getenv("MAX_TOKENS_PER_REQUEST", "100000"))
        self.max_context_tokens = int(os.getenv("MAX_CONTEXT_TOKENS", "2000000"))
        self.max_retries = int(os.getenv("MAX_RETRIES", "3"))
        self.request_timeout = int(os.getenv("REQUEST_TIMEOUT", "300"))
        
        # Cost settings
        self.cost_alert_threshold = float(os.getenv("COST_ALERT_THRESHOLD", "10.00"))
        self.daily_cost_limit = float(os.getenv("DAILY_COST_LIMIT", "50.00"))
        
        # Pricing (per 1M tokens)
        self.input_cost_per_1m = 1.25
        self.output_cost_per_1m = 10.0
        
        if not self.api_key:
            raise ValueError(
                "OpenRouter API key is required. "
                "Set OPENROUTER_API_KEY environment variable or pass api_key parameter."
            )
        
        # Initialize OpenAI client with OpenRouter
        self.client = openai.OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
        
        # Load schema and system prompt
        self.schema = self.load_schema()
        self.system_prompt = self.load_system_prompt()
        
        # Session tracking
        self.session_cost = 0.0
        self.session_start = datetime.now()
        
        logger.info(f"✅ GeminiExtractor initialized")
        logger.info(f"🎯 Model: {self.model_name}")
        logger.info(f"🌐 Base URL: {self.base_url}")
        logger.info(f"📊 Max context: {self.max_context_tokens:,} tokens")
    
    def load_schema(self) -> Dict:
        """Load the JSON schema for structured output."""
        schema_file = os.getenv("SCHEMA_FILE", "submittal_extraction_schema.json")
        schema_path = Path(schema_file)
        
        if not schema_path.exists():
            raise FileNotFoundError(
                f"Schema file {schema_path} not found. "
                f"Please ensure {schema_file} is in the current directory."
            )
        
        with open(schema_path, "r") as f:
            schema = json.load(f)
        
        logger.info(f"📋 Schema loaded from {schema_path}")
        return schema
    
    def load_system_prompt(self) -> str:
        """Load the system prompt for Gemini."""
        prompt_file = "system_prompt_for_llama_agent.md"
        prompt_path = Path(prompt_file)
        
        if not prompt_path.exists():
            raise FileNotFoundError(
                f"System prompt file {prompt_path} not found. "
                f"Please ensure {prompt_file} is in the current directory."
            )
        
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt = f.read()
        
        logger.info(f"📝 System prompt loaded from {prompt_path} ({len(prompt)} chars)")
        return prompt
    
    def extract_text_from_pdf(self, pdf_path: Union[str, Path]) -> str:
        """Extract text from PDF using pdfplumber."""
        pdf_path = Path(pdf_path)
        
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        logger.info(f"📄 Extracting text from {pdf_path}")
        start_time = time.time()
        
        try:
            text_content = []
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)
                logger.info(f"📖 Processing {total_pages} pages...")
                
                for i, page in enumerate(pdf.pages):
                    if i % 100 == 0:  # Progress logging every 100 pages
                        logger.info(f"📄 Processing page {i+1}/{total_pages}")
                    
                    page_text = page.extract_text()
                    if page_text:
                        text_content.append(f"\\n--- PAGE {i+1} ---\\n{page_text}")
                
                full_text = "\\n".join(text_content)
                
                # Estimate token count
                estimated_tokens = len(full_text) // 4  # Rough estimate: 4 chars per token
                
                extraction_time = time.time() - start_time
                logger.info(f"✅ Text extraction completed in {extraction_time:.2f}s")
                logger.info(f"📊 Extracted {len(full_text):,} characters (~{estimated_tokens:,} tokens)")
                
                # Check if within context limits
                if estimated_tokens > self.max_context_tokens * 0.8:  # Leave margin for system prompt
                    logger.warning(
                        f"⚠️ Document may be too large ({estimated_tokens:,} tokens). "
                        f"Consider chunking strategy for documents > {self.max_context_tokens:,} tokens."
                    )
                
                return full_text
                
        except Exception as e:
            logger.error(f"❌ PDF text extraction failed: {e}")
            raise ExtractionError(f"Failed to extract text from PDF: {e}")
    
    def calculate_cost(self, usage) -> TokenUsage:
        """Calculate cost based on token usage."""
        input_cost = (usage.prompt_tokens / 1_000_000) * self.input_cost_per_1m
        output_cost = (usage.completion_tokens / 1_000_000) * self.output_cost_per_1m
        total_cost = input_cost + output_cost
        
        return TokenUsage(
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            input_cost=round(input_cost, 6),
            output_cost=round(output_cost, 6),
            total_cost=round(total_cost, 6)
        )
    
    # @retry(
    #     stop=stop_after_attempt(3),
    #     wait=wait_exponential(multiplier=1, min=4, max=10),
    #     reraise=True
    # )
    def call_gemini_api(self, document_text: str) -> Dict[str, Any]:
        """Make API call to Gemini 2.5 Pro via OpenRouter with retry logic."""
        
        logger.info("🔄 Calling Gemini 2.5 Pro API...")
        start_time = time.time()
        
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": self.system_prompt
                    },
                    {
                        "role": "user",
                        "content": f"Extract submittal requirements from this construction specification document:\\n\\n{document_text}"
                    }
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "submittal_extraction",
                        "strict": True,
                        "schema": self.schema
                    }
                },
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                timeout=self.request_timeout
            )
            
            api_time = time.time() - start_time
            logger.info(f"✅ API call completed in {api_time:.2f}s")
            
            # Calculate costs
            token_usage = self.calculate_cost(response.usage)
            self.session_cost += token_usage.total_cost
            
            # Log usage and costs
            logger.info(f"📊 Token usage: {response.usage.total_tokens:,} total")
            logger.info(f"💰 Cost: ${token_usage.total_cost:.6f} (Session: ${self.session_cost:.6f})")
            
            # Check cost alerts
            if token_usage.total_cost > self.cost_alert_threshold:
                logger.warning(f"⚠️ High cost alert: ${token_usage.total_cost:.6f}")
            
            if self.session_cost > self.daily_cost_limit:
                logger.error(f"🚨 Daily cost limit exceeded: ${self.session_cost:.6f}")
            
            # Save raw response first (before parsing)
            raw_response = response.choices[0].message.content
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Save to file for debugging and recovery
            raw_response_file = f"raw_response_{timestamp}.json"
            try:
                with open(raw_response_file, 'w', encoding='utf-8') as f:
                    f.write(raw_response)
                logger.info(f"💾 Raw response saved to: {raw_response_file}")
            except Exception as save_error:
                logger.warning(f"⚠️ Could not save raw response: {save_error}")
            
            # Parse JSON response
            try:
                extracted_data = json.loads(raw_response)
                logger.info("✅ JSON parsing successful")
                
                # Keep raw response file for inspection (disabled cleanup)
                logger.info(f"💾 Raw response preserved: {raw_response_file}")
                # Clean up disabled for debugging
                # try:
                #     Path(raw_response_file).unlink()
                #     logger.debug("🗑️ Raw response file cleaned up")
                # except:
                #     pass  # Keep file if cleanup fails
                
                return {
                    "data": extracted_data,
                    "token_usage": token_usage,
                    "model_used": response.model,
                    "api_time": api_time
                }
                
            except json.JSONDecodeError as e:
                # Try simple JSON repair for common issues
                logger.warning("🔧 Attempting JSON repair...")
                repaired_response = self._attempt_json_repair(raw_response)
                
                if repaired_response:
                    try:
                        extracted_data = json.loads(repaired_response)
                        logger.info("✅ JSON repair successful!")
                        
                        # Save repaired version for reference
                        repaired_file = f"repaired_response_{timestamp}.json"
                        with open(repaired_file, 'w', encoding='utf-8') as f:
                            f.write(repaired_response)
                        logger.info(f"💾 Repaired response saved to: {repaired_file}")
                        
                        return {
                            "data": extracted_data,
                            "token_usage": token_usage,
                            "model_used": response.model,
                            "api_time": api_time
                        }
                    except json.JSONDecodeError:
                        logger.error("❌ JSON repair failed")
                
                # Original error handling if repair fails
                logger.error(f"❌ JSON parsing failed: {e}")
                logger.error(f"📁 Full response saved to: {raw_response_file}")
                logger.error(f"📊 Response length: {len(raw_response):,} characters")
                logger.error(f"🔍 Error location: line {e.lineno}, column {e.colno}")
                
                # Show context around the error
                if hasattr(e, 'pos') and e.pos < len(raw_response):
                    start = max(0, e.pos - 100)
                    end = min(len(raw_response), e.pos + 100)
                    context = raw_response[start:end]
                    logger.error(f"📝 Error context: ...{context}...")
                
                raise ExtractionError(
                    f"Failed to parse JSON response: {e}. "
                    f"Full response saved to {raw_response_file} for debugging."
                )
            
        except Exception as e:
            logger.error(f"❌ Gemini API call failed: {e}")
            raise ExtractionError(f"API call failed: {e}")
    
    def extract(self, pdf_path: Union[str, Path]) -> ExtractionResult:
        """
        Main extraction method that replaces LlamaExtract.extract().
        
        Args:
            pdf_path: Path to the PDF file to extract submittals from
            
        Returns:
            ExtractionResult with extracted data and metadata
        """
        pdf_path = Path(pdf_path)
        logger.info(f"🚀 Starting Gemini extraction for: {pdf_path}")
        start_time = datetime.now()
        
        try:
            # 1. Extract text from PDF
            document_text = self.extract_text_from_pdf(pdf_path)
            
            # 2. Call Gemini API for extraction
            api_result = self.call_gemini_api(document_text)
            
            # 3. Create result object
            processing_time = (datetime.now() - start_time).total_seconds()
            
            result = ExtractionResult(
                data=api_result["data"],
                token_usage=api_result["token_usage"],
                processing_time=processing_time,
                model_used=api_result["model_used"],
                timestamp=datetime.now().isoformat()
            )
            
            logger.info(f"✅ Extraction completed in {processing_time:.2f}s")
            logger.info(f"📊 Extracted {len(result.data.get('bullets', []))} submittal items")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Extraction failed: {e}")
            raise ExtractionError(f"Failed to extract submittals from {pdf_path}: {e}")
    
    def validate_results(self, results: Dict[str, Any]) -> bool:
        """
        Validate extraction results against expected structure.
        Compatible with existing SubmittalExtractor.validate_results().
        """
        try:
            required_fields = ["bullets"]
            validation_results = {
                "has_bullets": len(results.get("bullets", [])) > 0,
                "bullets_have_required_fields": all(
                    all(field in bullet for field in ["spec_section", "section_title", "article_number", "submittal_type"])
                    for bullet in results.get("bullets", [])
                ),
                "bullets_have_titles_and_text": all(
                    ("submittal_title" in bullet and "text" in bullet)
                    for bullet in results.get("bullets", [])
                ),
                "bullets_have_hierarchy": all(
                    all(field in bullet for field in ["id", "level"])
                    for bullet in results.get("bullets", [])
                )
            }
            
            # Check all validations pass
            all_valid = all(validation_results.values())
            
            if all_valid:
                logger.info("✅ Results validation passed")
            else:
                logger.warning(f"⚠️ Results validation issues: {validation_results}")
            
            return all_valid
            
        except Exception as e:
            logger.error(f"❌ Results validation failed: {e}")
            return False
    
    def get_session_stats(self) -> Dict[str, Any]:
        """Get current session statistics."""
        session_duration = (datetime.now() - self.session_start).total_seconds()
        
        return {
            "session_duration_seconds": session_duration,
            "total_cost": round(self.session_cost, 6),
            "model_used": self.model_name,
            "extractions_count": getattr(self, '_extraction_count', 0)
        }
    
    def _attempt_json_repair(self, raw_response: str) -> Optional[str]:
        """
        Attempt to repair common JSON formatting issues.
        
        Args:
            raw_response: The raw JSON string from API
            
        Returns:
            Repaired JSON string or None if repair fails
        """
        try:
            # Common repairs for Gemini responses
            repaired = raw_response
            
            # 1. Remove trailing commas before closing braces/brackets
            import re
            repaired = re.sub(r',(\s*[}\]])', r'\1', repaired)
            
            # 2. Fix unescaped quotes in strings
            # This is complex and risky, so we'll be conservative
            
            # 3. Ensure JSON starts and ends properly
            repaired = repaired.strip()
            if not repaired.startswith('{'):
                # Try to find the start of JSON
                start = repaired.find('{')
                if start > 0:
                    repaired = repaired[start:]
            
            # 4. Ensure JSON ends properly  
            if not repaired.endswith('}'):
                # Try to find the last complete closing brace
                last_brace = repaired.rfind('}')
                if last_brace > 0:
                    repaired = repaired[:last_brace + 1]
            
            # 5. Handle truncated responses - try to close incomplete JSON
            if repaired.count('{') > repaired.count('}'):
                missing_braces = repaired.count('{') - repaired.count('}')
                repaired += '}' * missing_braces
                
            if repaired.count('[') > repaired.count(']'):
                missing_brackets = repaired.count('[') - repaired.count(']')
                repaired += ']' * missing_brackets
            
            return repaired
            
        except Exception as e:
            logger.error(f"❌ JSON repair attempt failed: {e}")
            return None