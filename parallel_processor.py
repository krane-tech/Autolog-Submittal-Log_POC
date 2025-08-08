#!/usr/bin/env python3
"""
Parallel processing module for handling multiple PDF chunks simultaneously.
Implements smart retry strategy for failed chunks.
"""

import asyncio
import concurrent.futures
import logging
import time
from typing import List, Dict, Any, Tuple, Optional
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class ChunkResult:
    """Result from processing a single chunk."""
    chunk_id: int
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    processing_time: float = 0.0
    retry_count: int = 0

@dataclass
class ParallelProcessingResult:
    """Result from parallel processing with retry information."""
    successful_results: List[ChunkResult]
    failed_chunks: List[int]
    total_processing_time: float
    total_retries: int
    total_chunks: int

class ParallelChunkProcessor:
    """
    Processes PDF chunks in parallel with smart retry strategy.
    
    Features:
    - Simultaneous processing of all chunks
    - Smart retry of only failed chunks
    - Progress tracking and logging
    - Configurable retry limits and timeouts
    """
    
    def __init__(self, extractor, max_retries: int = 3, max_workers: Optional[int] = None):
        """
        Initialize parallel processor.
        
        Args:
            extractor: GeminiExtractor instance
            max_retries: Maximum number of retry attempts per chunk
            max_workers: Maximum number of concurrent workers (None = auto)
        """
        self.extractor = extractor
        self.max_retries = max_retries
        self.max_workers = max_workers or 12  # Support up to 12 chunks simultaneously
        
    def process_chunk(self, chunk_file: str, chunk_id: int) -> ChunkResult:
        """
        Process a single PDF chunk.
        
        Args:
            chunk_file: Path to the chunk PDF file
            chunk_id: Unique identifier for this chunk
            
        Returns:
            ChunkResult with success/failure information
        """
        start_time = time.time()
        
        try:
            logger.info(f"🔄 Processing chunk {chunk_id}: {Path(chunk_file).name}")
            
            # Extract from this chunk PDF
            result = self.extractor.extract(chunk_file)
            
            processing_time = time.time() - start_time
            bullets_count = len(result.data.get("bullets", []))
            cost = result.token_usage.total_cost
            
            logger.info(f"✅ Chunk {chunk_id} completed: {bullets_count} bullets, ${cost:.6f}, {processing_time:.1f}s")
            
            # Convert to dict format for merging
            chunk_data = {
                "bullets": result.data.get("bullets", []),
                "metadata": {
                    "model_used": result.model_used,
                    "processing_time_seconds": result.processing_time,
                    "timestamp": result.timestamp,
                    "token_usage": result.token_usage.dict(),
                    "chunk_info": {
                        "chunk_number": chunk_id,
                        "chunk_file": Path(chunk_file).name
                    }
                }
            }
            
            return ChunkResult(
                chunk_id=chunk_id,
                success=True,
                data=chunk_data,
                processing_time=processing_time
            )
            
        except Exception as e:
            processing_time = time.time() - start_time
            error_msg = str(e)
            logger.error(f"❌ Chunk {chunk_id} failed after {processing_time:.1f}s: {error_msg}")
            
            return ChunkResult(
                chunk_id=chunk_id,
                success=False,
                error=error_msg,
                processing_time=processing_time
            )
    
    def process_chunks_parallel(self, chunk_files: List[str]) -> Tuple[List[ChunkResult], List[int]]:
        """
        Process multiple chunks in parallel.
        
        Args:
            chunk_files: List of chunk PDF file paths
            
        Returns:
            Tuple of (successful_results, failed_chunk_ids)
        """
        if not chunk_files:
            return [], []
        
        logger.info(f"🚀 Starting parallel processing of {len(chunk_files)} chunks...")
        start_time = time.time()
        
        successful_results = []
        failed_chunk_ids = []
        
        # Process all chunks simultaneously
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all chunks for processing
            future_to_chunk = {
                executor.submit(self.process_chunk, chunk_file, i + 1): (chunk_file, i + 1)
                for i, chunk_file in enumerate(chunk_files)
            }
            
            # Collect results as they complete
            for future in concurrent.futures.as_completed(future_to_chunk):
                chunk_file, chunk_id = future_to_chunk[future]
                
                try:
                    result = future.result()
                    
                    if result.success:
                        successful_results.append(result)
                    else:
                        failed_chunk_ids.append(chunk_id)
                        
                except Exception as e:
                    logger.error(f"❌ Chunk {chunk_id} executor error: {e}")
                    failed_chunk_ids.append(chunk_id)
        
        processing_time = time.time() - start_time
        success_count = len(successful_results)
        failure_count = len(failed_chunk_ids)
        
        logger.info(f"📊 Parallel processing completed in {processing_time:.1f}s")
        logger.info(f"   ✅ Successful: {success_count}/{len(chunk_files)} chunks")
        
        if failure_count > 0:
            logger.warning(f"   ❌ Failed: {failure_count} chunks: {failed_chunk_ids}")
        
        return successful_results, failed_chunk_ids
    
    def retry_failed_chunks(self, chunk_files: List[str], failed_chunk_ids: List[int], retry_attempt: int) -> Tuple[List[ChunkResult], List[int]]:
        """
        Retry only the chunks that failed.
        
        Args:
            chunk_files: All chunk file paths
            failed_chunk_ids: List of chunk IDs that failed
            retry_attempt: Current retry attempt number
            
        Returns:
            Tuple of (newly_successful_results, still_failed_chunk_ids)
        """
        if not failed_chunk_ids:
            return [], []
        
        logger.info(f"🔄 Retry attempt {retry_attempt}: Processing {len(failed_chunk_ids)} failed chunks...")
        
        # Get the chunk files that need retrying
        retry_files = [chunk_files[chunk_id - 1] for chunk_id in failed_chunk_ids]
        
        successful_results = []
        still_failed_ids = []
        
        # Process failed chunks in parallel again
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_chunk = {
                executor.submit(self.process_chunk, chunk_file, chunk_id): (chunk_file, chunk_id)
                for chunk_file, chunk_id in zip(retry_files, failed_chunk_ids)
            }
            
            for future in concurrent.futures.as_completed(future_to_chunk):
                chunk_file, chunk_id = future_to_chunk[future]
                
                try:
                    result = future.result()
                    result.retry_count = retry_attempt
                    
                    if result.success:
                        successful_results.append(result)
                        logger.info(f"✅ Chunk {chunk_id} succeeded on retry {retry_attempt}")
                    else:
                        still_failed_ids.append(chunk_id)
                        
                except Exception as e:
                    logger.error(f"❌ Chunk {chunk_id} retry error: {e}")
                    still_failed_ids.append(chunk_id)
        
        return successful_results, still_failed_ids
    
    def process_with_smart_retry(self, chunk_files: List[str]) -> ParallelProcessingResult:
        """
        Process chunks with smart retry strategy.
        
        Main entry point that handles:
        1. Initial parallel processing of all chunks
        2. Smart retry of only failed chunks
        3. Comprehensive result tracking
        
        Args:
            chunk_files: List of PDF chunk file paths
            
        Returns:
            ParallelProcessingResult with all results and statistics
        """
        if not chunk_files:
            return ParallelProcessingResult([], [], 0.0, 0, 0)
        
        total_start_time = time.time()
        total_retries = 0
        
        logger.info(f"🎯 Starting smart retry processing for {len(chunk_files)} chunks")
        logger.info(f"📋 Max retries per chunk: {self.max_retries}")
        logger.info(f"⚙️  Max concurrent workers: {self.max_workers}")
        
        # Phase 1: Initial parallel processing
        successful_results, failed_chunk_ids = self.process_chunks_parallel(chunk_files)
        
        # Phase 2: Smart retry loop
        for retry_attempt in range(1, self.max_retries + 1):
            if not failed_chunk_ids:
                logger.info("🎉 All chunks processed successfully!")
                break
            
            total_retries += len(failed_chunk_ids)
            logger.info(f"🔄 Retry round {retry_attempt}/{self.max_retries}")
            
            # Retry only failed chunks
            new_successes, still_failed = self.retry_failed_chunks(
                chunk_files, failed_chunk_ids, retry_attempt
            )
            
            # Update results
            successful_results.extend(new_successes)
            failed_chunk_ids = still_failed
            
            if not failed_chunk_ids:
                logger.info(f"🎉 All chunks recovered after {retry_attempt} retry attempts!")
                break
        
        # Final statistics
        total_processing_time = time.time() - total_start_time
        final_success_count = len(successful_results)
        final_failure_count = len(failed_chunk_ids)
        
        logger.info(f"📊 Smart retry processing completed in {total_processing_time:.1f}s")
        logger.info(f"   ✅ Final successful: {final_success_count}/{len(chunk_files)} chunks")
        logger.info(f"   🔄 Total retry operations: {total_retries}")
        
        if failed_chunk_ids:
            logger.error(f"   ❌ Permanently failed chunks: {failed_chunk_ids}")
            logger.error(f"   💡 These chunks exceeded {self.max_retries} retry attempts")
        
        return ParallelProcessingResult(
            successful_results=successful_results,
            failed_chunks=failed_chunk_ids,
            total_processing_time=total_processing_time,
            total_retries=total_retries,
            total_chunks=len(chunk_files)
        )