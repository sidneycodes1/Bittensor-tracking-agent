#!/usr/bin/env python3
"""
Bittensor Subnet Auto-Populator — REAL DATA VERSION
Pulls actual subnet names/descriptions/GitHub links from Taostats' public
registry, blends with live blockchain stats, uses AI only to categorize.
"""

import os
import sys
import json
import time
import requests
from typing import Optional, List, Dict, Any
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
NOTION_API_KEY = os.getenv('NOTION_API_KEY')
NOTION_DATABASE_ID = 'c38cadde-ded5-4c42-b24e-4acb3c4bcffa'

GEMINI_API = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent'
NOTION_API = 'https://api.notion.com/v1'
SUBNET_REGISTRY_URL = 'https://raw.githubusercontent.com/taostat/subnets-infos/main/subnets.json'

import bittensor as bt
logger.info(f"✅ Bittensor SDK {bt.__version__} loaded")


def fetch_subnet_registry() -> Dict[str, Any]:
    """Fetch real subnet names/descriptions/GitHub links maintained by Taostats."""
    try:
        r = requests.get(SUBNET_REGISTRY_URL, timeout=15)
        r.raise_for_status()
        registry = r.json()
        logger.info(f"✅ Loaded real metadata for {len(registry)} subnets from Taostats registry")
        return registry
    except Exception as e:
        logger.warning(f"Could not fetch subnet registry: {e}")
        return {}


class SubnetEnricher:
    def __init__(self, gemini_key: str):
        self.gemini_key = gemini_key

    def analyze(self, subnet_data: Dict[str, Any]) -> Dict[str, str]:
        has_real_info = subnet_data.get('real_name') and subnet_data.get('real_description')

        try:
            if has_real_info:
                prompt = f"""
Someone with ZERO crypto background wants to understand this real Bittensor subnet.

Subnet #{subnet_data['id']}: "{subnet_data['real_name']}"
Official description: {subnet_data['real_description']}
Network stats: {subnet_data['validators']} active nodes, registration cost {subnet_data.get('burn', 'unknown')} TAO.

Based on this REAL description, write JSON with:
"category": one of Mining, Development, Creator, Validator, Data
"difficulty": one of Beginner, Intermediate, Advanced
"mining_criteria": 3-4 plain-English sentences explaining, based on the official description above: what this subnet actually does, what running a miner on it involves in practice, and who it's realistically a good fit for.
"estimated_roi": one practical sentence on realistic earning expectations for this specific type of work
"hardware_specs": specific hardware needed for THIS subnet's actual task (e.g. if it's LLM/image work, likely needs GPU; if it's data collection, likely doesn't)

Respond in JSON only, no markdown:
{{"category": "...", "difficulty": "...", "mining_criteria": "...", "estimated_roi": "...", "hardware_specs": "..."}}
"""
            else:
                prompt = f"""
This Bittensor subnet (#{subnet_data['id']}) has no public registry entry yet — it may be new, unregistered, or private.

Network stats: {subnet_data['validators']} active nodes, registration cost {subnet_data.get('burn', 'unknown')} TAO.

Write JSON with:
"category": your best guess from Mining, Development, Creator, Validator, Data
"difficulty": Beginner, Intermediate, or Advanced
"mining_criteria": Be HONEST that no official description exists yet for this subnet. Suggest checking taostats.io/subnets/{subnet_data['id']} directly for current info. Do not fabricate details about what it does.
"estimated_roi": "Unknown — no public data available for this subnet yet"
"hardware_specs": "Unknown — check taostats.io/subnets/{subnet_data['id']} or the subnet's Discord for details"

Respond in JSON only, no markdown:
{{"category": "...", "difficulty": "...", "mining_criteria": "...", "estimated_roi": "...", "hardware_specs": "..."}}
"""
            response = requests.post(
                GEMINI_API,
                params={'key': self.gemini_key},
                json={
                    'contents': [{'parts': [{'text': prompt}]}],
                    'generationConfig': {'temperature': 0.3, 'maxOutputTokens': 500}
                },
                timeout=15
            )
            if response.status_code != 200:
                return self._default()

            text = response.json()['candidates'][0]['content']['parts'][0]['text'].strip()
            if text.startswith('```'):
                text = text.split('```')[1]
                if text.startswith('json'):
                    text = text[4:]
            data = json.loads(text.strip())

            return {
                'category': data.get('category', 'Mining'),
                'difficulty': data.get('difficulty', 'Intermediate'),
                'mining_criteria': data.get('mining_criteria', 'Bittensor subnet'),
                'estimated_roi': data.get('estimated_roi', 'ROI varies'),
                'hardware_specs': data.get('hardware_specs', 'See official docs'),
            }
        except Exception as e:
            logger.warning(f"Gemini error for subnet {subnet_data.get('id')}: {e}")
            return self._default()

    def _default(self) -> Dict[str, str]:
        return {
            'category': 'Mining',
            'difficulty': 'Intermediate',
            'mining_criteria': 'No data available — see Taostats for details',
            'estimated_roi': 'Unknown',
            'hardware_specs': 'See official docs',
        }


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
            r = requests.post(f'{NOTION_API}/databases/{self.database_id}/query',
                               headers=self.headers, json=query, timeout=10)
            results = r.json().get('results', [])
            return results[0]['id'] if results else None
        except Exception as e:
            logger.warning(f"Notion lookup failed for SN{subnet_id}: {e}")
            return None

    def create_subnet_page(self, d: Dict[str, Any]) -> bool:
        try:
            page = {
                'parent': {'database_id': self.database_id},
                'properties': {
                    'Subnet Name': {'title': [{'text': {'content': d['name']}}]},
                    'Subnet ID': {'number': d['id']},
                    'Categories': {'multi_select': [{'name': d['category']}]},
                    'Difficulty': {'multi_select': [{'name': d['difficulty']}]},
                    'Status': {'select': {'name': 'Active'}},
                    'Estimated ROI': {'rich_text': [{'text': {'content': d['estimated_roi']}}]},
                    'Validators': {'number': d.get('validators', 0)},
                    'Emissions per Block': {'rich_text': [{'text': {'content': str(d.get('burn', 'N/A'))}}]},
                    'Hardware Specs': {'rich_text': [{'text': {'content': d.get('hardware_specs', 'See docs')}}]},
                    'Taostats Link': {'url': f'https://taostats.io/subnets/{d["id"]}'},
                    'GitHub Link': {'url': d.get('github', '') or ''},
                    'Notes': {'rich_text': [{'text': {'content': d.get('mining_criteria', '')}}]},
                }
            }
            r = requests.post(f'{NOTION_API}/pages', headers=self.headers, json=page, timeout=10)
            if r.status_code >= 300:
                logger.error(f"Notion create failed for SN{d['id']} ({r.status_code}): {r.text[:200]}")
                return False
            logger.info(f"✅ Created SN{d['id']}: {d['name']}")
            return True
        except Exception as e:
            logger.error(f"Create failed for SN{d['id']}: {e}")
            return False
            
            def update_subnet_page(self, page_id: str, d: Dict[str, Any]) -> bool:
        try:
            page = {
                'properties': {
                    'Subnet Name': {'title': [{'text': {'content': d['name']}}]},
                    'Categories': {'multi_select': [{'name': d['category']}]},
                    'Difficulty': {'multi_select': [{'name': d['difficulty']}]},
                    'Estimated ROI': {'rich_text': [{'text': {'content': d['estimated_roi']}}]},
                    'Validators': {'number': d.get('validators', 0)},
                    'Emissions per Block': {'rich_text': [{'text': {'content': str(d.get('burn', 'N/A'))}}]},
                    'Hardware Specs': {'rich_text': [{'text': {'content': d.get('hardware_specs', 'See docs')}}]},
                    'GitHub Link': {'url': d.get('github', '') or ''},
                    'Notes': {'rich_text': [{'text': {'content': d.get('mining_criteria', '')}}]},
                    'Status': {'select': {'name': 'Active'}},
                }
            }
            r = requests.patch(f'{NOTION_API}/pages/{page_id}', headers=self.headers, json=page, timeout=10)
            if r.status_code >= 300:
                logger.error(f"Notion update failed for SN{d['id']} ({r.status_code}): {r.text[:200]}")
                return False
            logger.info(f"🔄 Updated SN{d['id']}: {d['name']}")
            return True
        except Exception as e:
            logger.warning(f"Update failed: {e}")
            return False

def main():
    logger.info("🚀 Bittensor Subnet Auto-Populator (Real Data Version)")

    if not all([GEMINI_API_KEY, NOTION_API_KEY]):
        logger.error("Missing GEMINI_API_KEY or NOTION_API_KEY")
        sys.exit(1)

    registry = fetch_subnet_registry()

    logger.info("Connecting to Bittensor finney...")
    subtensor = bt.subtensor(network='finney')
    logger.info("✅ Connected")

    logger.info("Fetching all subnets via subtensor.subnets.all()...")
    raw_subnets = subtensor.subnets.all()
    logger.info(f"✅ Got {len(raw_subnets)} subnets from blockchain")

    enricher = SubnetEnricher(GEMINI_API_KEY)
    notion = NotionClient(NOTION_API_KEY, NOTION_DATABASE_ID)

    created = updated = failed = 0

    for info in raw_subnets:
        try:
            netuid = info.netuid
            registry_entry = registry.get(str(netuid), {})
            real_name = registry_entry.get('name', '')
            real_description = registry_entry.get('description', '')
            real_github = registry_entry.get('github', '')

            display_name = real_name if real_name and real_name != 'Unknown' else f'Subnet {netuid}'

            subnet = {
                'id': netuid,
                'name': display_name,
                'validators': getattr(info, 'neuron_count', 0),
                'burn': getattr(info, 'burn', 'N/A'),
                'real_name': real_name if real_name != 'Unknown' else '',
                'real_description': real_description,
                'github': real_github,
            }

            enrichment = enricher.analyze(subnet)
            subnet_data = {**subnet, **enrichment}

            existing = notion.find_subnet(netuid)
            if existing:
                if notion.update_subnet_page(existing, subnet_data):
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
            logger.error(f"Error on subnet {getattr(info, 'netuid', '?')}: {e}")
            failed += 1

    logger.info(f"\n✅ DONE — Created: {created}, Updated: {updated}, Failed: {failed}")

    if created == 0 and updated == 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
