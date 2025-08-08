#!/usr/bin/env python3
"""
PDF splitting utilities for large document processing.
Creates smaller PDF files that can be processed independently by Gemini 2.5 Pro.
"""

import os
import math
from pathlib import Path
from typing import List, Tuple, Dict, Any
import logging
import tempfile
from datetime import datetime
import pdfplumber
from pypdf import PdfReader, PdfWriter

logger = logging.getLogger(__name__)


class PDFSplitter:
    """Handles splitting large PDFs into smaller chunks for processing."""
    
    def __init__(self, max_tokens_per_chunk: int = 100_000):
        """
        Initialize PDF splitter.
        
        Args:
            max_tokens_per_chunk: Maximum tokens per chunk (default: 100K for OpenRouter compatibility)
        """
        self.max_tokens_per_chunk = max_tokens_per_chunk
        self.tokens_per_page = 530  # Based on Sutter specs analysis
        self.temp_dir = None
        
    def get_pdf_info(self, pdf_path: str) -> Dict[str, Any]:
        """Get basic information about the PDF."""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)
                
            estimated_tokens = total_pages * self.tokens_per_page
            
            return {
                "total_pages": total_pages,
                "estimated_tokens": estimated_tokens,
                "file_size": Path(pdf_path).stat().st_size,
                "needs_splitting": estimated_tokens > self.max_tokens_per_chunk
            }
            
        except Exception as e:
            logger.error(f"Failed to analyze PDF: {e}")
            raise
    
    def calculate_optimal_chunks(self, total_pages: int) -> List[Tuple[int, int]]:
        """
        Calculate optimal page ranges for splitting.
        
        Args:
            total_pages: Total number of pages in PDF
            
        Returns:
            List of (start_page, end_page) tuples (1-based indexing)
        """
        max_pages_per_chunk = self.max_tokens_per_chunk // self.tokens_per_page
        
        # Ensure reasonable minimum chunk size
        min_chunk_size = 200
        if max_pages_per_chunk < min_chunk_size and total_pages > min_chunk_size:
            max_pages_per_chunk = min_chunk_size
        
        chunks = []
        for start_page in range(1, total_pages + 1, max_pages_per_chunk):
            end_page = min(start_page + max_pages_per_chunk - 1, total_pages)
            chunks.append((start_page, end_page))
        
        return chunks
    
    def create_temp_directory(self) -> str:
        """Create temporary directory for PDF chunks."""
        if self.temp_dir is None:
            # Create a permanent directory for debugging
            permanent_dir = Path("pdf_chunks")
            permanent_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.temp_dir = str(permanent_dir / f"split_{timestamp}")
            Path(self.temp_dir).mkdir(exist_ok=True)
            logger.info(f"📁 Created chunk directory: {self.temp_dir}")
        return self.temp_dir
    
    def split_pdf(self, pdf_path: str, chunks: List[Tuple[int, int]]) -> List[str]:
        """
        Split PDF into smaller files based on page ranges.
        
        Args:
            pdf_path: Path to original PDF
            chunks: List of (start_page, end_page) tuples
            
        Returns:
            List of paths to created chunk PDF files
        """
        pdf_path = Path(pdf_path)
        temp_dir = self.create_temp_directory()
        chunk_files = []
        
        logger.info(f"📄 Splitting {pdf_path.name} into {len(chunks)} chunks...")
        
        try:
            reader = PdfReader(str(pdf_path))
            
            for i, (start_page, end_page) in enumerate(chunks, 1):
                # Create writer for this chunk
                writer = PdfWriter()
                
                # Add pages to this chunk (convert to 0-based indexing)
                for page_num in range(start_page - 1, end_page):
                    if page_num < len(reader.pages):
                        writer.add_page(reader.pages[page_num])
                
                # Save chunk file
                chunk_filename = f"{pdf_path.stem}_chunk_{i:02d}_pages_{start_page}-{end_page}.pdf"
                chunk_path = Path(temp_dir) / chunk_filename
                
                with open(chunk_path, 'wb') as output_file:
                    writer.write(output_file)
                
                chunk_files.append(str(chunk_path))
                
                pages_in_chunk = end_page - start_page + 1
                file_size = chunk_path.stat().st_size / (1024 * 1024)  # MB
                
                logger.info(f"   ✅ Chunk {i}: {chunk_filename} ({pages_in_chunk} pages, {file_size:.1f}MB)")
        
        except Exception as e:
            logger.error(f"❌ PDF splitting failed: {e}")
            self.cleanup_temp_files()
            raise
        
        logger.info(f"✅ PDF splitting completed: {len(chunk_files)} files created")
        return chunk_files
    
    def get_splitting_plan(self, pdf_path: str) -> Dict[str, Any]:
        """
        Create a comprehensive splitting plan for a PDF.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Dictionary with analysis and splitting plan
        """
        pdf_info = self.get_pdf_info(pdf_path)
        
        if not pdf_info["needs_splitting"]:
            return {
                "pdf_path": str(pdf_path),
                "total_pages": pdf_info["total_pages"],
                "estimated_tokens": pdf_info["estimated_tokens"],
                "needs_splitting": False,
                "chunks": [(1, pdf_info["total_pages"])],
                "num_chunks": 1,
                "estimated_cost": self._estimate_cost(1)
            }
        
        chunks = self.calculate_optimal_chunks(pdf_info["total_pages"])
        
        return {
            "pdf_path": str(pdf_path),
            "total_pages": pdf_info["total_pages"], 
            "estimated_tokens": pdf_info["estimated_tokens"],
            "max_tokens_per_chunk": self.max_tokens_per_chunk,
            "needs_splitting": True,
            "chunks": chunks,
            "num_chunks": len(chunks),
            "estimated_cost": self._estimate_cost(len(chunks))
        }
    
    def _estimate_cost(self, num_chunks: int) -> float:
        """Estimate total processing cost for all chunks."""
        # Based on OpenRouter Gemini 2.5 Pro pricing
        input_cost_per_1m = 1.25
        output_cost_per_1m = 10.00
        
        # Conservative estimates per chunk
        avg_input_tokens = self.max_tokens_per_chunk * 0.7  # 70% of max
        avg_output_tokens = 25_000  # Based on smaller document tests
        
        cost_per_chunk = (
            (avg_input_tokens / 1_000_000) * input_cost_per_1m +
            (avg_output_tokens / 1_000_000) * output_cost_per_1m
        )
        
        return round(cost_per_chunk * num_chunks, 6)
    
    def cleanup_temp_files(self):
        """Clean up temporary PDF chunk files."""
        if self.temp_dir and Path(self.temp_dir).exists():
            # Don't actually delete for debugging - just log
            logger.info(f"📁 Chunk files preserved in: {self.temp_dir}")
            logger.info(f"💡 Manual cleanup: delete 'pdf_chunks' folder when done")
            # try:
            #     import shutil
            #     shutil.rmtree(self.temp_dir)
            #     logger.info(f"🗑️  Cleaned up temp directory: {self.temp_dir}")
            #     self.temp_dir = None
            # except Exception as e:
            #     logger.warning(f"⚠️ Failed to cleanup temp files: {e}")


def merge_extraction_results(chunk_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Merge extraction results from multiple PDF chunks.
    
    Args:
        chunk_results: List of extraction results from individual chunks
        
    Returns:
        Merged extraction result
    """
    if not chunk_results:
        return {"bullets": [], "metadata": {"extractor_type": "gemini_2_5_pro_split"}}
    
    if len(chunk_results) == 1:
        # Add split indicator to metadata
        result = chunk_results[0]
        result["metadata"]["extractor_type"] = "gemini_2_5_pro_split"
        return result
    
    logger.info(f"🔗 Merging results from {len(chunk_results)} PDF chunks...")
    
    # Collect all bullets and statistics
    all_bullets = []
    total_cost = 0.0
    total_time = 0.0
    total_tokens = 0
    
    for i, result in enumerate(chunk_results, 1):
        bullets = result.get("bullets", [])
        metadata = result.get("metadata", {})
        token_usage = metadata.get("token_usage", {})
        
        all_bullets.extend(bullets)
        
        # Accumulate stats
        total_cost += token_usage.get("total_cost", 0)
        total_time += metadata.get("processing_time_seconds", 0)
        total_tokens += token_usage.get("total_tokens", 0)
        
        logger.info(f"   • Chunk {i}: {len(bullets)} bullets, ${token_usage.get('total_cost', 0):.6f}")
    
    # Remove duplicates based on spec_section + article_number + submittal_title
    seen = set()
    unique_bullets = []
    
    for bullet in all_bullets:
        # Create unique key for deduplication
        key = (
            bullet.get("spec_section", ""),
            bullet.get("article_number", ""),
            bullet.get("submittal_title", ""),
            bullet.get("text", "")[:50]  # First 50 chars of text
        )
        
        if key not in seen:
            seen.add(key)
            unique_bullets.append(bullet)
    
    duplicates_removed = len(all_bullets) - len(unique_bullets)
    if duplicates_removed > 0:
        logger.info(f"🔄 Removed {duplicates_removed} duplicate bullets across chunks")
    
    # Create merged result
    merged_result = {
        "bullets": unique_bullets,
        "metadata": {
            "extractor_type": "gemini_2_5_pro_split",
            "num_chunks": len(chunk_results),
            "processing_time_seconds": total_time,
            "token_usage": {
                "total_tokens": total_tokens,
                "total_cost": total_cost
            },
            "total_bullets_before_dedup": len(all_bullets),
            "total_bullets_after_dedup": len(unique_bullets),
            "duplicates_removed": duplicates_removed,
            "timestamp": chunk_results[-1].get("metadata", {}).get("timestamp")
        }
    }
    
    logger.info(f"✅ Merge complete: {len(unique_bullets)} unique bullets, ${total_cost:.6f} total")
    
    return merged_result