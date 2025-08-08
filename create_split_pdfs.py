#!/usr/bin/env python3
"""
Script to split the Sutter specs PDF and save the chunks permanently.
This will show you exactly what files are created for processing.
"""

from pdf_splitter import PDFSplitter
from pathlib import Path
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

def split_sutter_specs():
    """Split the Sutter specs PDF and save chunks permanently."""
    
    print("🎯 Creating Split PDFs from Sutter Specs")
    print("=" * 60)
    
    # Initialize splitter with small chunks (100K tokens)
    splitter = PDFSplitter(max_tokens_per_chunk=100_000)
    
    pdf_path = "1123 Sutter Specs.pdf"
    if not Path(pdf_path).exists():
        print(f"❌ PDF not found: {pdf_path}")
        return
    
    # Get the splitting plan
    print("📊 STEP 1: Analyzing PDF")
    plan = splitter.get_splitting_plan(pdf_path)
    
    print(f"   • File: {Path(pdf_path).name}")
    print(f"   • Total pages: {plan['total_pages']:,}")
    print(f"   • Estimated tokens: {plan['estimated_tokens']:,}")
    print(f"   • Number of chunks: {plan['num_chunks']}")
    print(f"   • Estimated cost: ${plan['estimated_cost']:.2f}")
    print()
    
    # Show the chunk plan
    print("📋 STEP 2: Chunk Plan")
    print("-" * 40)
    for i, (start, end) in enumerate(plan['chunks'], 1):
        pages = end - start + 1
        tokens = pages * 530
        print(f"   • Chunk {i}: Pages {start:,}-{end:,} ({pages:,} pages, ~{tokens:,} tokens)")
    print()
    
    # Create the output directory
    output_dir = Path("pdf_chunks")
    output_dir.mkdir(exist_ok=True)
    
    # Actually split the PDF
    print("⚙️  STEP 3: Creating PDF Chunks")
    print("-" * 40)
    
    try:
        chunk_files = splitter.split_pdf(pdf_path, plan['chunks'])
        
        print(f"\n✅ SUCCESS: {len(chunk_files)} PDF chunks created!")
        print(f"📁 Saved in: {splitter.temp_dir}")
        print()
        
        # List all the created files
        print("📄 STEP 4: Created Files")
        print("-" * 40)
        
        total_size = 0
        for i, chunk_file in enumerate(chunk_files, 1):
            chunk_path = Path(chunk_file)
            if chunk_path.exists():
                file_size = chunk_path.stat().st_size / (1024 * 1024)  # MB
                total_size += file_size
                
                # Try to verify the file
                try:
                    import pdfplumber
                    with pdfplumber.open(chunk_file) as pdf:
                        actual_pages = len(pdf.pages)
                        
                    print(f"   ✅ {chunk_path.name}")
                    print(f"      • Size: {file_size:.1f} MB")
                    print(f"      • Pages: {actual_pages}")
                    print(f"      • Path: {chunk_file}")
                    
                except Exception as e:
                    print(f"   ❌ {chunk_path.name} - Verification failed: {e}")
            else:
                print(f"   ❌ File not found: {chunk_file}")
        
        print(f"\n📊 SUMMARY:")
        print(f"   • Total chunks: {len(chunk_files)}")
        print(f"   • Total size: {total_size:.1f} MB")
        print(f"   • Original size: {Path(pdf_path).stat().st_size / (1024*1024):.1f} MB")
        print(f"   • Location: {splitter.temp_dir}")
        
        # Don't cleanup so user can see the files
        print(f"\n💡 Files are saved permanently for inspection")
        print(f"📁 Directory: {splitter.temp_dir}")
        
        return chunk_files
        
    except Exception as e:
        print(f"❌ PDF splitting failed: {e}")
        return None

if __name__ == "__main__":
    split_sutter_specs()