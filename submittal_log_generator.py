"""
Submittal log generator that converts JSON extraction results to Excel format.
Matches the exact structure of the Sutter submittal log.
"""
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging
import re

# from config import get_config  # Removed dependency for Gemini version

logger = logging.getLogger(__name__)

class SubmittalLogGenerator:
    """Converts extraction results to submittal log format matching Sutter log structure."""
    
    def __init__(self):
        """Initialize the generator."""
        # self.config = get_config()  # Removed - using direct configuration
    
    def generate_log(self, extraction_results: Dict, output_path: Optional[str] = None) -> pd.DataFrame:
        """
        Convert extraction results to submittal log format.
        
        Args:
            extraction_results: JSON results from LlamaCloud extraction
            output_path: Optional path to save Excel file
        
        Returns:
            DataFrame with submittal log entries
        """
        # Extract data from nested structure if needed
        data = extraction_results.get("data", extraction_results)
        
        bullets = data.get("bullets", [])
        
        logger.info(f"📊 Processing {len(bullets)} bullets")
        
        if not bullets:
            logger.warning("⚠️ No bullets found in extraction results")
            return self._create_empty_dataframe()
        
        # Convert bullets to submittal log entries
        submittal_items = []
        
        for bullet in bullets:
            try:
                # Only process level 1 bullets (main submittal items)
                if bullet.get("level", 0) != 1:
                    continue
                    
                # Skip if no submittal_title (these are just descriptions)
                if not bullet.get("submittal_title", "").strip():
                    continue
                
                # Generate submittal log entry
                item = self._create_submittal_item(bullet)
                if item:
                    submittal_items.append(item)
                
            except Exception as e:
                logger.error(f"❌ Error processing bullet {bullet.get('id', 'unknown')}: {e}")
                continue
        
        if not submittal_items:
            logger.warning("⚠️ No valid submittal items created")
            return self._create_empty_dataframe()
        
        # Create DataFrame with exact Sutter log structure
        df = pd.DataFrame(submittal_items)
        
        # Ensure columns are in the exact order from Sutter log
        df = df[["Spec Section", "Package #", "Rev.", "Title", "Type"]]
        
        logger.info(f"✅ Generated {len(df)} submittal log entries")
        
        # Save to Excel if path provided
        if output_path:
            self.save_to_excel(df, output_path)
        
        return df
    
    def _create_submittal_item(self, bullet: Dict) -> Optional[Dict]:
        """Create a submittal log entry from bullet data."""
        try:
            spec_section = bullet.get("spec_section", "")
            section_title = bullet.get("section_title", "")
            article_number = bullet.get("article_number", "")
            submittal_title = bullet.get("submittal_title", "").strip()
            submittal_type = bullet.get("submittal_type", "")
            bullet_id = bullet.get("id", "")
            
            # Skip if missing essential data
            if not all([spec_section, submittal_title]):
                return None
            
            # Generate package number: "12 24 13-1.2A"
            package_number = self._generate_package_number(spec_section, article_number, bullet_id)
            
            # Format spec section with title: "12 24 13 - ROLLER WINDOW SHADES"
            spec_section_full = f"{spec_section} - {section_title}" if section_title else spec_section
            
            # Map submittal type to readable format
            type_name = self._map_submittal_type(submittal_type)
            
            return {
                "Spec Section": spec_section_full,
                "Package #": package_number,
                "Rev.": 0.0,  # Default revision
                "Title": submittal_title,
                "Type": type_name
            }
            
        except Exception as e:
            logger.error(f"❌ Error creating submittal item: {e}")
            return None
    
    def _generate_package_number(self, spec_section: str, article_number: str, bullet_id: str) -> str:
        """Generate package number in format: 12 24 13-1.2A"""
        try:
            # Clean spec section (remove extra spaces/dashes)
            spec_clean = re.sub(r'\s+', ' ', spec_section.strip())
            
            # Basic format: spec_section-article_number+bullet_id
            if article_number and bullet_id:
                return f"{spec_clean}-{article_number}{bullet_id}"
            elif article_number:
                return f"{spec_clean}-{article_number}"
            else:
                return spec_clean
                
        except Exception:
            return spec_section or "UNKNOWN"
    
    def _map_submittal_type(self, submittal_type: str) -> str:
        """Map submittal type to readable format."""
        type_mapping = {
            "ACTION SUBMITTALS": "Material Submittal",
            "INFORMATIONAL SUBMITTALS": "Information Submittal", 
            "CLOSEOUT SUBMITTALS": "Closeout Submittals",
            "QUALITY ASSURANCE": "Quality Assurance"
        }
        
        return type_mapping.get(submittal_type, "Material Submittal")
    
    def _create_empty_dataframe(self) -> pd.DataFrame:
        """Create empty DataFrame with Sutter log structure."""
        return pd.DataFrame(columns=["Spec Section", "Package #", "Rev.", "Title", "Type"])
    
    def save_to_excel(self, df: pd.DataFrame, output_path: str):
        """Save DataFrame to Excel file."""
        try:
            # Ensure output directory exists
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            
            # Save to Excel
            with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Submittal Log', index=False)
                
                # Auto-adjust column widths
                worksheet = writer.sheets['Submittal Log']
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = min(max_length + 2, 50)
                    worksheet.column_dimensions[column_letter].width = adjusted_width
            
            logger.info(f"💾 Excel file saved to: {output_path}")
            
        except Exception as e:
            logger.error(f"❌ Error saving Excel file: {e}")
            raise 