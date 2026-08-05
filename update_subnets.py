#!/usr/bin/env python3
"""
Bittensor Subnet Auto-Populator — FINAL WORKING VERSION
Confirmed working with Bittensor SDK v11.0.2 via subtensor.subnets.all()
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
- Netuid: {subnet_data.get('id')}
- Neuron count: {subnet_data.get('validators', 0)}
- Tempo: {subnet_data.get('tempo', 'Unknown')}
- Burn cost: {subnet_data.get('burn', 'Unknown')}

Respond in JSON only, no markdown fences:
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
            text_response = result['candidates'][0]['content']['parts'][0]['text'].strip()
            if text_response.startswith('```'):
                text_response = text_response.split('```')[1]
                if text_response.startswith('json'):
                    text_response = text_response[4:]
            data = json.loads(text_response.strip())

            return {
                'category': data.get('category', 'Mining'),
                'difficulty': data.get('difficulty', 'Intermediate'),
                'mining_criteria': data.get('mining_criteria', 'Bittensor subnet opportunity'),
                'estimated_roi': data.get('estimated_roi', 'ROI varies'),
            }
        except Exception as e:
            logger.warning(f"Gemini error for subnet {subnet_data.get('id')}: {e}")
            return self._default_analysis()

    def _default_analysis(self) -> Dict[str, str]:
        return {
            'category': 'Mining',
            'difficulty': 'Intermediate',
            'mining_criteria': 'Bittensor subnet - see taostats for live details',
            'estimated_roi': 'ROI varies by subnet activity',
        }


class BittensorClient:
    def __init__(self):
        logger.info("Connecting to Bittensor finney (mainnet)...")
        self.subtensor = bt.subtensor(network='finney')
        logger.info("✅ Connected")

    def get_all_subnets(self) -> List[Dict[str, Any]]:
        logger.info("Fetching subnets via subtensor.subnets.all()...")
        raw_subnets = self.subtensor.subnets.all()
        logger.info(f"✅ Got {len(raw_subnets)} subnets from chain")

        subnets = []
        for info in raw_subnets:
            netuid = getattr(info, 'netuid', None)
            tempo = getattr(info, 'tempo', 'Unknown')
            burn = getattr(info, 'burn', 'Unknown')
            neuron_count = getattr(info, 'neuron_count', 0)

            subnets.append({
                'id': netuid,
                'name': f'Subnet {netuid}',
                'validators': neuron_count,
                'tempo': tempo,
                'burn': str(burn),
                'emission': 'N/A',
                'status': 'Active',
            })
        return subnets


class NotionClient:
    def __init__(self, api_key: str, database_id: str):
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
                headers=self.headers, json=query, timeout=10
            )
            results = response.json().get('results', [])
            return results[0]['id'] if results else None
        except Exception as e:
            logger.warning(f"Notion lookup failed for subnet {subnet_id}: {e}")
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
                    'Emissions per Block': {'rich_text': [{'text': {'content': f"tempo={subnet_data.get('tempo')}, burn={subnet_data.get('burn')}"}}]},
                    'Taostats Link': {'url': f'https://taostats.io/subnets/{subnet_data["id"]}'},
                    'Notes': {'rich_text': [{'text': {'content': subnet_data.get('mining_criteria', '')}}]},
                }
            }
            response = requests.post(f'{NOTION_API}/pages', headers=self.headers, json=page, timeout=10)
            if response.status_code >= 300:
                logger.error(f"Notion create failed ({response.status_code}): {response.text[:300]}")
                return False
            logger.info(f"✅ Created SN{subnet_data['id']}")
            return True
        except Exception as e:
            logger.error(f"Failed to create page: {e}")
            return False

    def update_subnet_page(self, page_id: str, subnet_data: Dict[str, Any]) -> bool:
        try:
            page = {
                'properties': {
                    'Validators': {'number': subnet_data.get('validators', 0)},
                    'Emissions per Block': {'rich_text': [{'text': {'content': f"tempo={subnet_data.get('tempo')}, burn={subnet_data.get('burn')}"}}]},
                    'Status': {'select': {'name': subnet_data.get('status', 'Active')}},
                }
            }
            response = requests.patch(f'{NOTION_API}/pages/{page_id}', headers=self.headers, json=page, timeout=10)
            logger.info(f"🔄 Updated SN{subnet_data['id']}")
            return response.status_code < 300
        except Exception as e:
            logger.warning(f"Notion update failed: {e}")
            return False


def main():
    logger.info("🚀 Bittensor Blockchain Subnet Auto-Populator (FINAL)")

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

    # First run: process all subnets found (up to ~130). Gemini calls add
    # up, so this run may take a few minutes - that's expected.
    for subnet in subnets:
        try:
            enrichment = enricher.generate_description_with_gemini(subnet)

            subnet_data = {**subnet, **enrichment}

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

            time.sleep(0.3)
        except Exception as e:
            logger.error(f"Error processing subnet {subnet.get('id')}: {e}")
            failed += 1

    logger.info(f"\n✅ Sync Complete: Created={created}, Updated={updated}, Failed={failed}")

    if failed > 0 and created == 0 and updated == 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
