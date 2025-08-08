"""
Main submittal extractor using Gemini 2.5 Pro via OpenRouter API.
Replaces LlamaCloud's document extraction service.
"""
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging

from gemini_extractor import GeminiExtractor, ExtractionError
from pdf_splitter import PDFSplitter, merge_extraction_results
from parallel_processor import ParallelChunkProcessor

# Set up logging
logger = logging.getLogger(__name__)

# Simple config class for Gemini extractor
class SimpleConfig:
    """Simplified configuration for Gemini extractor."""
    def __init__(self):
        self.processing = self.ProcessingConfig()
        self.output = self.OutputConfig()
    
    class ProcessingConfig:
        enable_validation = True
        save_intermediate_results = True
        log_level = "INFO"
    
    class OutputConfig:
        output_dir = "output"
        json_backup = True
        timestamp_files = True

class SubmittalExtractor:
    """Main class for extracting submittal requirements from PDFs using Gemini 2.5 Pro."""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize the extractor with OpenRouter API credentials."""
        self.config = SimpleConfig()
        
        # Configure logging
        logging.basicConfig(level=getattr(logging, self.config.processing.log_level))
        
        # Initialize Gemini extractor (replaces LlamaExtract)
        try:
            self.extractor = GeminiExtractor(api_key=api_key)
            self.pdf_splitter = PDFSplitter(max_tokens_per_chunk=100_000)
            self.parallel_processor = ParallelChunkProcessor(self.extractor, max_retries=3)
            logger.info("✅ GeminiExtractor initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize GeminiExtractor: {e}")
            raise ExtractionError(f"Failed to initialize Gemini extractor: {e}")
    
    def extract_submittals(self, pdf_path: str, pages: Optional[str] = None) -> Dict:
        """
        Extract submittal requirements from a PDF using Gemini 2.5 Pro with automatic PDF splitting.
        
        Args:
            pdf_path: Path to the PDF file
            pages: Optional page range (ignored - full document processed)
            
        Returns:
            Dict containing extracted submittal data
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        logger.info(f"🚀 Starting Gemini extraction for: {pdf_path}")
        
        if pages:
            logger.info(f"ℹ️ Page range '{pages}' specified but ignored - processing full document")
        
        try:
            # Check if document needs splitting
            splitting_plan = self.pdf_splitter.get_splitting_plan(str(pdf_path))
            
            if splitting_plan["needs_splitting"]:
                return self._extract_with_pdf_splitting(pdf_path, splitting_plan)
            else:
                return self._extract_single_pdf(pdf_path)
                
        except Exception as e:
            logger.error(f"❌ Extraction failed: {e}")
            raise ExtractionError(f"Failed to extract submittals: {e}")
        finally:
            # Always cleanup temporary files
            self.pdf_splitter.cleanup_temp_files()
    
    def _extract_single_pdf(self, pdf_path: Path) -> Dict:
        """Process PDF that fits within token limits."""
        logger.info("📄 Processing PDF in single extraction...")
        
        result = self.extractor.extract(pdf_path)
        
        # Convert to legacy format
        results = result.data
        results["metadata"] = {
            "model_used": result.model_used,
            "processing_time_seconds": result.processing_time,
            "timestamp": result.timestamp,
            "token_usage": result.token_usage.dict(),
            "extractor_type": "gemini_2_5_pro_single"
        }
        
        bullets_count = len(results.get('bullets', []))
        cost = result.token_usage.total_cost
        
        logger.info(f"✅ Single PDF extraction completed")
        logger.info(f"📊 Found {bullets_count} submittal items")
        logger.info(f"💰 Cost: ${cost:.6f}")
        
        return results
    
    def _extract_with_pdf_splitting(self, pdf_path: Path, splitting_plan: Dict) -> Dict:
        """Process large PDF using parallel splitting approach."""
        chunks = splitting_plan["chunks"]
        
        logger.info(f"📊 Large PDF detected - using PARALLEL splitting strategy:")
        logger.info(f"   • Total pages: {splitting_plan['total_pages']}")
        logger.info(f"   • Estimated tokens: {splitting_plan['estimated_tokens']:,}")
        logger.info(f"   • Number of chunks: {splitting_plan['num_chunks']}")
        logger.info(f"   • Estimated cost: ${splitting_plan['estimated_cost']:.6f}")
        logger.info(f"   🚀 Processing ALL chunks simultaneously!")
        
        # Split PDF into smaller files
        chunk_files = self.pdf_splitter.split_pdf(str(pdf_path), chunks)
        
        # Process all chunks in parallel with smart retry
        parallel_result = self.parallel_processor.process_with_smart_retry(chunk_files)
        
        # Check if any chunks permanently failed
        if parallel_result.failed_chunks:
            failed_count = len(parallel_result.failed_chunks)
            total_count = parallel_result.total_chunks
            logger.warning(f"⚠️ {failed_count}/{total_count} chunks permanently failed after {self.parallel_processor.max_retries} retries")
            logger.warning(f"   Failed chunks: {parallel_result.failed_chunks}")
            logger.info(f"   Proceeding with {len(parallel_result.successful_results)} successful chunks")
        
        if not parallel_result.successful_results:
            raise ExtractionError("All PDF chunks failed to process")
        
        # Convert parallel results to the format expected by merge function
        chunk_results = [result.data for result in parallel_result.successful_results]
        
        # Merge all chunk results
        logger.info(f"🔗 Merging results from {len(chunk_results)} successful chunks...")
        merged_results = merge_extraction_results(chunk_results)
        
        # Add parallel processing statistics to metadata
        merged_metadata = merged_results.get('metadata', {})
        merged_metadata.update({
            "parallel_processing": {
                "total_chunks": parallel_result.total_chunks,
                "successful_chunks": len(parallel_result.successful_results),
                "failed_chunks": len(parallel_result.failed_chunks),
                "total_retries": parallel_result.total_retries,
                "parallel_processing_time": parallel_result.total_processing_time
            }
        })
        merged_results['metadata'] = merged_metadata
        
        total_bullets = len(merged_results.get('bullets', []))
        total_cost = merged_results.get('metadata', {}).get('token_usage', {}).get('total_cost', 0)
        parallel_time = parallel_result.total_processing_time
        
        logger.info(f"✅ Parallel PDF splitting extraction completed in {parallel_time:.1f}s")
        logger.info(f"📊 Final result: {total_bullets} unique submittal items")
        logger.info(f"💰 Total cost: ${total_cost:.6f}")
        logger.info(f"🔄 Total retry operations: {parallel_result.total_retries}")
        
        return merged_results
    
    def validate_results(self, results: Dict) -> bool:
        """
        Validate extraction results against expected structure.
        Updated for Gemini 2.5 Pro output format.
        """
        try:
            # Use the validation from GeminiExtractor
            return self.extractor.validate_results(results)
            
        except Exception as e:
            logger.error(f"❌ Validation error: {e}")
            return False
    
    def save_intermediate_results(self, results: Dict, filename_base: str):
        """Save intermediate JSON results for debugging."""
        if not self.config.output.json_backup:
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        if self.config.output.timestamp_files:
            json_filename = f"{filename_base}_gemini_extraction_{timestamp}.json"
        else:
            json_filename = f"{filename_base}_gemini_extraction.json"
        
        json_path = Path(self.config.output.output_dir) / json_filename
        json_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        logger.info(f"💾 Intermediate results saved to: {json_path}")
    
    def extract_with_retry(self, pdf_path: str, pages: Optional[str] = None, max_retries: int = 3) -> Dict:
        """Extract with automatic retry on failures."""
        for attempt in range(max_retries):
            try:
                return self.extract_submittals(pdf_path, pages)
            except Exception as e:
                logger.error(f"❌ Attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    raise ExtractionError(f"Failed after {max_retries} attempts: {e}")
                
                # Exponential backoff
                wait_time = 60 * (attempt + 1)
                logger.info(f"⏳ Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
    
    def get_session_stats(self) -> Dict[str, Any]:
        """Get current session statistics from Gemini extractor."""
        return self.extractor.get_session_stats()

# Convenience function for direct usage
def extract_from_pdf(pdf_path: str, pages: Optional[str] = None, api_key: Optional[str] = None) -> Dict:
    """Convenience function to extract submittals from a PDF using Gemini 2.5 Pro."""
    extractor = SubmittalExtractor(api_key=api_key)
    return extractor.extract_submittals(pdf_path, pages)

if __name__ == "__main__":
    # Example usage
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python submittal_extractor_gemini_fixed.py <pdf_path> [pages]")
        sys.exit(1)
    
    pdf_file = sys.argv[1]
    page_range = sys.argv[2] if len(sys.argv) > 2 else None
    
    try:
        results = extract_from_pdf(pdf_file, page_range)
        bullets_count = len(results.get('bullets', []))
        cost = results.get('extraction_metadata', {}).get('token_usage', {}).get('total_cost', 0)
        print(f"✅ Extraction completed. Found {bullets_count} submittal items.")
        print(f"💰 Cost: ${cost:.6f}")
    except Exception as e:
        print(f"❌ Extraction failed: {e}")
        sys.exit(1)