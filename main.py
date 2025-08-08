#!/usr/bin/env python3
"""
Main script for the Gemini 2.5 Pro Submittal Extractor.
Complete workflow: PDF → Gemini 2.5 Pro → JSON → Excel Submittal Log
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime
import logging
import os

from config import GeminiConfig
from submittal_extractor import SubmittalExtractor, ExtractionError
from submittal_log_generator import SubmittalLogGenerator

def setup_logging(level: str = "INFO"):
    """Set up logging configuration."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

def validate_environment():
    """Validate that the environment is properly configured for Gemini 2.5 Pro."""
    try:
        # Check for OpenRouter API key
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            print("❌ OPENROUTER_API_KEY not found in environment variables!")
            print("\nPlease ensure:")
            print("1. Sign up at https://openrouter.ai/")
            print("2. Generate an API key")
            print("3. Copy .env.template to .env")
            print("4. Add your OPENROUTER_API_KEY to .env")
            return False
        
        # Check for required files
        required_files = [
            "submittal_extraction_schema.json",
            "system_prompt_for_llama_agent.md"
        ]
        
        for file_path in required_files:
            if not Path(file_path).exists():
                print(f"❌ Required file not found: {file_path}")
                return False
        
        print("✅ Environment validation passed")
        return True
        
    except Exception as e:
        print(f"❌ Environment validation failed: {e}")
        return False

def process_pdf(pdf_path: str, pages: str = None, output_dir: str = None) -> bool:
    """
    Process a PDF file and generate submittal log using Gemini 2.5 Pro.
    
    Args:
        pdf_path: Path to the PDF file
        pages: Optional page range (ignored - Gemini processes full document)
        output_dir: Optional output directory
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Validate inputs
        pdf_file = Path(pdf_path)
        if not pdf_file.exists():
            print(f"❌ PDF file not found: {pdf_path}")
            return False
        
        print(f"🚀 Processing: {pdf_file.name}")
        if pages:
            print(f"ℹ️ Page range '{pages}' specified but ignored - Gemini processes full document")
        
        # Initialize components
        print("🤖 Initializing Gemini 2.5 Pro extractor...")
        extractor = SubmittalExtractor()
        generator = SubmittalLogGenerator()
        
        # Extract submittals from PDF
        print("\n📤 Starting Gemini 2.5 Pro extraction...")
        print("⏳ This may take 30-60 seconds for large documents...")
        extraction_results = extractor.extract_submittals(str(pdf_file), pages)
        
        # Get extraction metadata
        metadata = extraction_results.get('extraction_metadata', {})
        token_usage = metadata.get('token_usage', {})
        
        # Generate output filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        excel_filename = f"{pdf_file.stem}_gemini_submittal_log_{timestamp}.xlsx"
        
        if output_dir:
            excel_path = Path(output_dir) / excel_filename
        else:
            excel_path = Path("output") / excel_filename
        
        # Ensure output directory exists
        excel_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Generate Excel submittal log
        print("\n📊 Generating Excel submittal log...")
        df = generator.generate_log(extraction_results, str(excel_path))
        
        # Print summary
        print(f"\n✅ Success! Generated {len(df)} submittal entries")
        print(f"📁 Output saved to: {excel_path}")
        
        # Print extraction statistics
        print(f"\n🔍 Extraction Details:")
        print(f"   • Model: {metadata.get('model_used', 'gemini-2.5-pro')}")
        print(f"   • Processing time: {metadata.get('processing_time_seconds', 0):.1f}s")
        print(f"   • Tokens used: {token_usage.get('total_tokens', 0):,}")
        print(f"   • Cost: ${token_usage.get('total_cost', 0):.6f}")
        
        # Print basic statistics
        if len(df) > 0:
            unique_sections = df['Spec Section'].nunique()
            action_count = len(df[df['Type'].str.contains('Action|ACTION', na=False)])
            info_count = len(df[df['Type'].str.contains('Informational|INFORMATIONAL', na=False)])
            material_count = len(df[df['Type'].str.contains('Material', na=False)])
            
            print(f"\n📈 Submittal Summary:")
            print(f"   • {unique_sections} unique specification sections")
            print(f"   • {action_count} action submittals")
            print(f"   • {info_count} informational submittals") 
            print(f"   • {material_count} material submittals")
        
        # Show session stats
        session_stats = extractor.get_session_stats()
        print(f"\n💰 Session Stats:")
        print(f"   • Total cost: ${session_stats.get('total_cost', 0):.6f}")
        print(f"   • Session duration: {session_stats.get('session_duration_seconds', 0):.1f}s")
        
        return True
        
    except ExtractionError as e:
        print(f"\n❌ Extraction failed: {e}")
        print("\nPossible solutions:")
        print("• Check your OpenRouter API key")
        print("• Verify PDF file is not corrupted")
        print("• Check internet connection")
        print("• Try again (temporary API issues)")
        return False
        
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        return False

def convert_existing_json(json_path: str, output_dir: str = None) -> bool:
    """
    Convert existing JSON extraction results to Excel format.
    
    Args:
        json_path: Path to existing JSON file
        output_dir: Optional output directory
    
    Returns:
        True if successful, False otherwise
    """
    try:
        json_file = Path(json_path)
        if not json_file.exists():
            print(f"❌ JSON file not found: {json_path}")
            return False
        
        print(f"🔄 Converting existing JSON: {json_file.name}")
        
        # Load existing results
        import json
        with open(json_file, 'r', encoding='utf-8') as f:
            extraction_results = json.load(f)
        
        # Initialize generator
        generator = SubmittalLogGenerator()
        
        # Generate output filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        excel_filename = f"{json_file.stem}_converted_to_excel_{timestamp}.xlsx"
        
        if output_dir:
            excel_path = Path(output_dir) / excel_filename
        else:
            excel_path = Path("output") / excel_filename
        
        # Ensure output directory exists
        excel_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Generate Excel submittal log
        print("📊 Generating Excel submittal log...")
        df = generator.generate_log(extraction_results, str(excel_path))
        
        print(f"\n✅ Success! Converted {len(df)} submittal entries")
        print(f"📁 Output saved to: {excel_path}")
        
        return True
        
    except Exception as e:
        print(f"❌ Conversion failed: {e}")
        return False

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Gemini 2.5 Pro Submittal Extractor - Extract submittals from construction specifications",
        epilog="Examples:\n"
               "  python main_gemini.py extract document.pdf\n"
               "  python main_gemini.py extract document.pdf --output ./results\n"
               "  python main_gemini.py convert results.json\n",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Extract command
    extract_parser = subparsers.add_parser('extract', help='Extract submittals from PDF')
    extract_parser.add_argument('pdf_path', help='Path to the PDF file')
    extract_parser.add_argument('--pages', help='Page range (ignored - full document processed)')
    extract_parser.add_argument('--output', help='Output directory')
    extract_parser.add_argument('--log-level', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    
    # Convert command
    convert_parser = subparsers.add_parser('convert', help='Convert existing JSON to Excel')
    convert_parser.add_argument('json_path', help='Path to the JSON file')
    convert_parser.add_argument('--output', help='Output directory')
    convert_parser.add_argument('--log-level', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    
    # Validate command
    validate_parser = subparsers.add_parser('validate', help='Validate environment setup')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Set up logging
    setup_logging(getattr(args, 'log_level', 'INFO'))
    
    # Handle commands
    if args.command == 'validate':
        success = validate_environment()
        return 0 if success else 1
    
    elif args.command == 'extract':
        # Validate environment first
        if not validate_environment():
            return 1
        
        success = process_pdf(args.pdf_path, getattr(args, 'pages', None), getattr(args, 'output', None))
        return 0 if success else 1
    
    elif args.command == 'convert':
        success = convert_existing_json(args.json_path, getattr(args, 'output', None))
        return 0 if success else 1
    
    else:
        parser.print_help()
        return 1

if __name__ == "__main__":
    sys.exit(main())