#!/usr/bin/env python3
"""
Bittensor Subnet Auto-Populator
Fetches subnets from Taostats, enriches with GitHub/Docs data, uses Gemini AI to describe.
Automatically populates or updates Notion database.
"""

import os
import sys
import json
import requests
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# API Keys from environment
TAOSTATS_API_KEY = os.getenv('TAOSTATS_API_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
NOTION_API_KEY = os.getenv('NOTION_API_KEY')
NOTION_DATABASE_ID = 'bf5ac6c5-72e8-453e-90b4-2ffee1714e43'

# API Endpoints
TAOSTATS_API = 'https://api.taostats.io/api/v1'
GEMINI_API = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent'
NOTION_API = 'https://api.notion.com/v1'

class SubnetEnricher:
    """Enriches subnet data with GitHub info and AI-generated descriptions."""
    
    def __init__(self, gemini_key: str):
        self.gemini_key = gemini_key
    
    def fetch_github_data(self, repo_url: str) -> Dict[str, Any]:
        """Fetch GitHub repo data (stars, last commit, README)."""
        if not repo_url or 'github.com' not in repo_url:
            return {}
        
        try:
            # Extract owner/repo from URL
            parts = repo_url.rstrip('/').split('/')
            owner, repo = parts[-2], parts[-1]
            repo = repo.replace('.git', '')
            
            headers = {'Accept': 'application/vnd.github.v3+json'}
            repo_data = requests.get(f'https://api.github.com/repos/{owner}/{repo}', headers=headers, timeout=5).json()
            
            readme_data = requests.get(f'https://api.github.com/repos/{owner}/{repo}/readme', headers=headers, timeout=5).json()
            readme = readme_data.get('content', '') if 'content' in readme_data else ''
            
            return {
                'stars': repo_data.get('stargazers_count', 0),
                'last_updated': repo_data.get('pushed_at', ''),
                'language': repo_data.get('language', ''),
                'readme_exists': len(readme) > 0,
            }
        except Exception as e:
            logger.warning(f"Failed to fetch GitHub data for {repo_url}: {e}")
            return {}
    
    def generate_description_with_gemini(self, subnet_data: Dict[str, Any]) -> Dict[str, str]:
        """Use Gemini AI to analyze subnet and generate category/difficulty/ROI estimate."""
        try:
            prompt = f"""
You are a Bittensor subnet analyst. Analyze this subnet and provide:
1. Category (choose ONE): Mining, Development, Creator, Validator, or Data
2. Difficulty (choose ONE): Beginner, Intermediate, or Advanced
3. Short mining criteria description (2-3 sentences max)
4. Estimated ROI (brief, e.g., "~0.5-1.0 TAO/day" or "Dev opportunity - potential partnerships")

Subnet Info:
- Name: {subnet_data.get('name', 'Unknown')}
- Description: {subnet_data.get('description', 'No description')}
- GPU Required: {subnet_data.get('gpu_required', 'Unknown')}
- Estimated Difficulty: {subnet_data.get('estimated_difficulty', 'Unknown')}
- Emission per Block: {subnet_data.get('emission', 'Unknown')} TAO

GitHub Info (if available):
- Stars: {subnet_data.get('github_stars', 'N/A')}
- Language: {subnet_data.get('github_language', 'N/A')}
- Has README: {subnet_data.get('github_readme', False)}

Respond in JSON format only:
{{
  "category": "Mining|Development|Creator|Validator|Data",
  "difficulty": "Beginner|Intermediate|Advanced",
  "mining_criteria": "2-3 sentence description",
  "estimated_roi": "ROI estimate or opportunity description"
}}
"""
            
            response = requests.post(
                GEMINI_API,
                params={'key': self.gemini_key},
                json={
                    'contents': [{'parts': [{'text': prompt}]}],
                    'generationConfig': {'temperature': 0.3, 'maxOutputTokens': 300}
                },
                timeout=10
            )
            
            if response.status_code != 200:
                logger.error(f"Gemini API error: {response.text}")
                return self._default_analysis()
            
            result = response.json()
            text_response = result['candidates'][0]['content']['parts'][0]['text']
            
            # Parse JSON from response
            import json as json_module
            data = json_module.loads(text_response)
            
            return {
                'category': data.get('category', 'Mining'),
                'difficulty': data.get('difficulty', 'Intermediate'),
                'mining_criteria': data.get('mining_criteria', 'Mining opportunity'),
                'estimated_roi': data.get('estimated_roi', 'ROI varies'),
            }
        
        except Exception as e:
            logger.error(f"Gemini AI error: {e}")
            return self._default_analysis()
    
    def _default_analysis(self) -> Dict[str, str]:
        """Fallback analysis if Gemini fails."""
        return {
            'category': 'Mining',
            'difficulty': 'Intermediate',
            'mining_criteria': 'Mining opportunity - see documentation for details',
            'estimated_roi': 'ROI varies - check current Taostats data',
        }


class TaostatsClient:
    """Fetches subnet data from Taostats API."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {'Authorization': f'Bearer {api_key}'}
    
    def get_all_subnets(self) -> List[Dict[str, Any]]:
        """Fetch all active subnets from Taostats."""
        try:
            response = requests.get(
                f'{TAOSTATS_API}/subnets',
                headers=self.headers,
                timeout=15
            )
            response.raise_for_status()
            
            subnets = response.json()
            logger.info(f"Fetched {len(subnets)} subnets from Taostats")
            return subnets
        
        except Exception as e:
            logger.error(f"Failed to fetch subnets from Taostats: {e}")
            return []
    
    def get_subnet_details(self, subnet_id: int) -> Optional[Dict[str, Any]]:
        """Fetch detailed info for a specific subnet."""
        try:
            response = requests.get(
                f'{TAOSTATS_API}/subnets/{subnet_id}',
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"Failed to fetch details for subnet {subnet_id}: {e}")
            return None


class NotionClient:
    """Manages Notion database operations."""
    
    def __init__(self, api_key: str, database_id: str):
        self.api_key = api_key
        self.database_id = database_id
        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Notion-Version': '2022-06-28',
            'Content-Type': 'application/json',
        }
    
    def find_subnet(self, subnet_id: int) -> Optional[str]:
        """Find subnet by ID in Notion database. Returns page ID if found."""
        try:
            query = {
                'filter': {
                    'property': 'Subnet ID',
                    'number': {'equals': subnet_id}
                }
            }
            
            response = requests.post(
                f'{NOTION_API}/databases/{self.database_id}/query',
                headers=self.headers,
                json=query,
                timeout=10
            )
            response.raise_for_status()
            
            results = response.json()['results']
            return results[0]['id'] if results else None
        
        except Exception as e:
            logger.warning(f"Error searching for subnet {subnet_id}: {e}")
            return None
    
    def create_subnet_page(self, subnet_data: Dict[str, Any]) -> bool:
        """Create a new subnet page in Notion."""
        try:
            page = {
                'parent': {'database_id': self.database_id},
                'properties': {
                    'Subnet Name': {
                        'title': [{'text': {'content': subnet_data['name']}}]
                    },
                    'Subnet ID': {
                        'number': subnet_data['id']
                    },
                    'Categories': {
                        'multi_select': [{'name': subnet_data['category']}]
                    },
                    'Difficulty': {
                        'multi_select': [{'name': subnet_data['difficulty']}]
                    },
                    'Status': {
                        'select': {'name': subnet_data['status']}
                    },
                    'GPU Required': {
                        'checkbox': subnet_data.get('gpu_required', False)
                    },
                    'Hardware Specs': {
                        'rich_text': [{'text': {'content': subnet_data.get('hardware_specs', 'See documentation')}}]
                    },
                    'Estimated ROI': {
                        'rich_text': [{'text': {'content': subnet_data['estimated_roi']}}]
                    },
                    'Validators': {
                        'number': subnet_data.get('validators', 0)
                    },
                    'Emissions per Block': {
                        'rich_text': [{'text': {'content': str(subnet_data.get('emission', 'N/A'))}}]
                    },
                    'GitHub Link': {
                        'url': subnet_data.get('github_link', '')
                    },
                    'Documentation Link': {
                        'url': subnet_data.get('docs_link', '')
                    },
                    'Taostats Link': {
                        'url': subnet_data.get('taostats_link', '')
                    },
                    'Website Link': {
                        'url': subnet_data.get('website_link', '')
                    },
                    'Discord Link': {
                        'url': subnet_data.get('discord_link', '')
                    },
                    'Notes': {
                        'rich_text': [{'text': {'content': subnet_data.get('mining_criteria', '')}}]
                    },
                }
            }
            
            response = requests.post(
                f'{NOTION_API}/pages',
                headers=self.headers,
                json=page,
                timeout=10
            )
            response.raise_for_status()
            logger.info(f"✅ Created subnet: {subnet_data['name']} (SN{subnet_data['id']})")
            return True
        
        except Exception as e:
            logger.error(f"Failed to create subnet page: {e}")
            return False
    
    def update_subnet_page(self, page_id: str, subnet_data: Dict[str, Any]) -> bool:
        """Update existing subnet page with latest stats."""
        try:
            page = {
                'properties': {
                    'Validators': {
                        'number': subnet_data.get('validators', 0)
                    },
                    'Emissions per Block': {
                        'rich_text': [{'text': {'content': str(subnet_data.get('emission', 'N/A'))}}]
                    },
                    'Status': {
                        'select': {'name': subnet_data.get('status', 'Active')}
                    },
                }
            }
            
            response = requests.patch(
                f'{NOTION_API}/pages/{page_id}',
                headers=self.headers,
                json=page,
                timeout=10
            )
            response.raise_for_status()
            logger.info(f"🔄 Updated subnet stats (validators: {subnet_data.get('validators')})")
            return True
        
        except Exception as e:
            logger.error(f"Failed to update subnet page {page_id}: {e}")
            return False


def process_subnet(subnet: Dict, enricher: SubnetEnricher, notion_client: NotionClient) -> bool:
    """Process a single subnet: enrich data and sync to Notion."""
    try:
        subnet_id = subnet.get('uid')
        subnet_name = subnet.get('name', f'Subnet {subnet_id}')
        
        # Enrich with GitHub & AI analysis
        enrichment = enricher.generate_description_with_gemini({
            'name': subnet_name,
            'description': subnet.get('description', ''),
            'gpu_required': subnet.get('gpu_required', False),
            'estimated_difficulty': subnet.get('difficulty', 'Unknown'),
            'emission': subnet.get('emission_per_block', 'N/A'),
        })
        
        # Build subnet data for Notion
        subnet_data = {
            'id': subnet_id,
            'name': subnet_name,
            'status': 'Active' if subnet.get('active', True) else 'Paused',
            'validators': subnet.get('validators_count', 0),
            'emission': subnet.get('emission_per_block', 'N/A'),
            'gpu_required': subnet.get('gpu_required', False),
            'category': enrichment['category'],
            'difficulty': enrichment['difficulty'],
            'estimated_roi': enrichment['estimated_roi'],
            'mining_criteria': enrichment['mining_criteria'],
            'hardware_specs': subnet.get('hardware_specs', 'See documentation'),
            'github_link': subnet.get('github_link', ''),
            'docs_link': subnet.get('docs_link', ''),
            'taostats_link': f'https://taostats.io/subnets/{subnet_id}',
            'website_link': subnet.get('website_link', ''),
            'discord_link': subnet.get('discord_link', ''),
        }
        
        # Check if subnet exists in Notion
        existing_page_id = notion_client.find_subnet(subnet_id)
        
        if existing_page_id:
            # Update existing
            return notion_client.update_subnet_page(existing_page_id, subnet_data)
        else:
            # Create new
            return notion_client.create_subnet_page(subnet_data)
    
    except Exception as e:
        logger.error(f"Error processing subnet {subnet.get('uid')}: {e}")
        return False


def main():
    """Main execution."""
    logger.info("🚀 Starting Bittensor Subnet Auto-Populator")
    
    # Validate environment
    if not all([TAOSTATS_API_KEY, GEMINI_API_KEY, NOTION_API_KEY]):
        logger.error("❌ Missing required API keys. Set TAOSTATS_API_KEY, GEMINI_API_KEY, NOTION_API_KEY")
        sys.exit(1)
    
    # Initialize clients
    taostats = TaostatsClient(TAOSTATS_API_KEY)
    enricher = SubnetEnricher(GEMINI_API_KEY)
    notion = NotionClient(NOTION_API_KEY, NOTION_DATABASE_ID)
    
    # Fetch all subnets
    subnets = taostats.get_all_subnets()
    if not subnets:
        logger.error("❌ No subnets fetched from Taostats")
        sys.exit(1)
    
    # Process each subnet
    created = 0
    updated = 0
    failed = 0
    
    for subnet in subnets:
        result = process_subnet(subnet, enricher, notion)
        if result:
            if notion.find_subnet(subnet.get('uid')):
                updated += 1
            else:
                created += 1
        else:
            failed += 1
    
    # Summary
    logger.info(f"\n✅ Sync Complete:")
    logger.info(f"   Created: {created}")
    logger.info(f"   Updated: {updated}")
    logger.info(f"   Failed: {failed}")
    
    if failed > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
