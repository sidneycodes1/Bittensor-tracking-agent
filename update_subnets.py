#!/usr/bin/env python3
"""
Bittensor Subnet Auto-Populator (Blockchain Version)
Queries subnets directly from Bittensor blockchain using the Bittensor SDK.
"""

import os
import sys
import json
import requests
import time
from typing import Optional, List, Dict, Any
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
NOTION_API_KEY = os.getenv('NOTION_API_KEY')
NOTION_DATABASE_ID = 'bf5ac6c5-72e8-453e-90b4-2ffee1714e43'

GEMINI_API = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent'
NOTION_API = 'https://api.notion.com/v1'

try:
    import bittensor as bt
    logger.info("✅ Bittensor SDK loaded")
except ImportError:
    logger.error("Installing Bittensor SDK...")
    os.system('pip install bittensor')
    import bittensor as bt


class SubnetEnricher:
    def __init__(self, gemini_key: str):
        self.gemini_key = gemini_key
    
    def generate_description_with_gemini(self, subnet_data: Dict[str, Any]) -> Dict[str, str]:
        try:
            prompt = f"""
Analyze this Bittensor subnet and provide:
1. Category: Mining, Development, Creator, Validator, or Data
2. Difficulty: Beginner, Intermediate, or Advanced
3. Mining criteria (2-3 sentences)
4. Estimated ROI

Subnet:
- Name: {subnet_data.get('name', 'Unknown')}
- Validators: {subnet_data.get('validators', 0)}
- Emission: {subnet_data.get('emission', 'Unknown')} TAO

Respond in JSON:
{{"category": "Mining", "difficulty": "Intermediate", "mining_criteria": "...", "estimated_roi": "..."}}
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
                return self._default_analysis()
            
            result = response.json()
            text_response = result['candidates'][0]['content']['parts'][0]['text']
            data = json.loads(text_response)
            
            return {
                'category': data.get('category', 'Mining'),
                'difficulty': data.get('difficulty', 'Intermediate'),
                'mining_criteria': data.get('mining_criteria', 'Subnet opportunity'),
                'estimated_roi': data.get('estimated_roi', 'ROI varies'),
            }
        except Exception as e:
            logger.warning(f"Gemini error: {e}")
            return self._default_analysis()
    
    def _default_analysis(self) -> Dict[str, str]:
        return {
            'category': 'Mining',
            'difficulty': 'Intermediate',
            'mining_criteria': 'Bittensor subnet',
            'estimated_roi': 'ROI varies',
        }


class BittensorClient:
    def __init__(self):
        self.subtensor = None
        self._connect()
    
    def _connect(self):
        try:
            logger.info("Connecting to Bittensor...")
            self.subtensor = bt.subtensor(network='mainnet')
            logger.info("✅ Connected to Bittensor mainnet")
        except Exception as e:
            logger.warning(f"Mainnet failed: {e}")
            try:
                self.subtensor = bt.subtensor(network='finney')
                logger.info("✅ Connected to Bittensor finney")
            except:
                logger.error("Cannot connect to Bittensor")
                self.subtensor = None
    
    def get_all_subnets(self) -> List[Dict[str, Any]]:
        if not self.subtensor:
            logger.error("Not connected to Bittensor")
            return []
        
        try:
            logger.info("Querying Bittensor blockchain...")
            subnets = []
            
            for subnet_id in range(200):
                try:
                    subnet_info = self.subtensor.get_subnet_info(subnet_id)
                    if subnet_info is None:
                        continue
                    
                    subnet_data = {
                        'id': subnet_id,
                        'name': getattr(subnet_info, 'name', f'Subnet {subnet_id}'),
                        'validators': getattr(subnet_info, 'n', 0),
                        'emission': round(getattr(subnet_info, 'emission_per_block', 0), 4),
                        'status': 'Active',
                    }
                    subnets.append(subnet_data)
                    logger.info(f"✅ SN{subnet_id}: {subnet_data['name']}")
                except:
                    continue
            
            logger.info(f"✅ Found {len(subnets)} subnets")
            return subnets
        except Exception as e:
            logger.error(f"Failed to fetch subnets: {e}")
            return []


class NotionClient:
    def __init__(self, api_key: str, database_id: str):
        self.api_key = api_key
        self.database_id = database_id
        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Notion-Version': '2022-06-28',
            'Content-Type': 'application/json',
        }
    
    def find_subnet(self, subnet_id: int) -> Optional[str]:
        try:
            query = {'filter': {'property': 'Subnet ID', 'number': {'equals': subnet_id}}}
            response = requests.post(
                f'{NOTION_API}/databases/{self.database_id}/query',
                headers=self.headers,
                json=query,
                timeout=10
            )
            results = response.json()['results']
            return results[0]['id'] if results else None
        except:
            return None
    
    def create_subnet_page(self, subnet_data: Dict[str, Any]) -> bool:
        try:
            page = {
                'parent': {'database_id': self.database_id},
                'properties': {
                    'Subnet Name': {'title': [{'text': {'content': subnet_data['name']}}]},
                    'Subnet ID': {'number': subnet_data['id']},
                    'Categories': {'multi_select': [{'name': subnet_data['category']}]},
                    'Difficulty': {'multi_select': [{'name': subnet_data['difficulty']}]},
                    'Status': {'select': {'name': subnet_data['status']}},
                    'Estimated ROI': {'rich_text': [{'text': {'content': subnet_data['estimated_roi']}}]},
                    'Validators': {'number': subnet_data.get('validators', 0)},
                    'Emissions per Block': {'rich_text': [{'text': {'content': str(subnet_data.get('emission', 'N/A'))}}]},
                    'Taostats Link': {'url': f'https://taostats.io/subnets/{subnet_data["id"]}'},
                    'Notes': {'rich_text': [{'text': {'content': subnet_data.get('mining_criteria', '')}}]},
                }
            }
            response = requests.post(f'{NOTION_API}/pages', headers=self.headers, json=page, timeout=10)
            logger.info(f"✅ Created SN{subnet_data['id']}: {subnet_data['name']}")
            return True
        except Exception as e:
            logger.error(f"Failed to create page: {e}")
            return False
    
    def update_subnet_page(self, page_id: str, subnet_data: Dict[str, Any]) -> bool:
        try:
            page = {
                'properties': {
                    'Validators': {'number': subnet_data.get('validators', 0)},
                    'Emissions per Block': {'rich_text': [{'text': {'content': str(subnet_data.get('emission', 'N/A'))}}]},
                    'Status': {'select': {'name': subnet_data.get('status', 'Active')}},
                }
            }
            response = requests.patch(f'{NOTION_API}/pages/{page_id}', headers=self.headers, json=page, timeout=10)
            return True
        except:
            return False


def main():
    logger.info("🚀 Bittensor Blockchain Subnet Auto-Populator")
    
    if not all([GEMINI_API_KEY, NOTION_API_KEY]):
        logger.error("Missing API keys")
        sys.exit(1)
    
    bittensor_client = BittensorClient()
    enricher = SubnetEnricher(GEMINI_API_KEY)
    notion = NotionClient(NOTION_API_KEY, NOTION_DATABASE_ID)
    
    subnets = bittensor_client.get_all_subnets()
    if not subnets:
        logger.error("No subnets fetched")
        sys.exit(1)
    
    created = 0
    updated = 0
    failed = 0
    
    for subnet in subnets:
        try:
            enrichment = enricher.generate_description_with_gemini(subnet)
            
            subnet_data = {
                'id': subnet['id'],
                'name': subnet['name'],
                'status': subnet['status'],
                'validators': subnet.get('validators', 0),
                'emission': subnet.get('emission', 'N/A'),
                'category': enrichment['category'],
                'difficulty': enrichment['difficulty'],
                'estimated_roi': enrichment['estimated_roi'],
                'mining_criteria': enrichment['mining_criteria'],
            }
            
            existing_page_id = notion.find_subnet(subnet['id'])
            
            if existing_page_id:
                if notion.update_subnet_page(existing_page_id, subnet_data):
                    updated += 1
                else:
                    failed += 1
            else:
                if notion.create_subnet_page(subnet_data):
                    created += 1
                else:
                    failed += 1
            
            time.sleep(0.5)
        except Exception as e:
            logger.error(f"Error processing subnet: {e}")
            failed += 1
    
    logger.info(f"\n✅ Sync Complete: Created={created}, Updated={updated}, Failed={failed}")
    
    if failed > 0 and created == 0 and updated == 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
