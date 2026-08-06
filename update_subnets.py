#!/usr/bin/env python3
"""
Bittensor Subnet Auto-Populator — FINAL WORKING VERSION
Confirmed API: subtensor.subnets.all() returns list[SubnetInfo]
Each SubnetInfo has: netuid, neuron_count, tempo, burn
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

import bittensor as bt
logger.info(f"✅ Bittensor SDK {bt.__version__} loaded")


class SubnetEnricher:
    def __init__(self, gemini_key: str):
        self.gemini_key = gemini_key

    def analyze(self, subnet_data: Dict[str, Any]) -> Dict[str, str]:
        try:
            prompt = f"""
You are explaining a Bittensor subnet to someone with ZERO crypto/tech background — a complete beginner.

Subnet #{subnet_data['id']} on the Bittensor network.
Data we know: {subnet_data['validators']} active nodes, tempo of {subnet_data.get('tempo', 'unknown')} blocks, registration cost of {subnet_data.get('burn', 'unknown')} TAO.

Write a JSON response with these fields:

"category": one of Mining, Development, Creator, Validator, Data

"difficulty": one of Beginner, Intermediate, Advanced

"mining_criteria": Write 4-5 full sentences in PLAIN ENGLISH, like you're explaining it to a smart friend who has never touched crypto. Cover: (1) what this subnet most likely does or is used for based on its subnet number and typical Bittensor subnet patterns, (2) what "mining" on it actually means in practice — do they run software, provide computing power, submit data, etc, (3) roughly what kind of computer/setup they'd need, (4) who this is realistically a good fit for (a beginner tinkering vs someone with serious GPU hardware vs a developer). If you are not confident what this specific subnet does, say so honestly and suggest checking taostats.io/subnets/{subnet_data['id']} for the current description rather than guessing wildly.

"estimated_roi": one practical sentence on realistic earning expectations and what affects them (competition, hardware quality, network conditions) — not just "ROI varies"

"hardware_specs": Be specific — either "No special hardware, just a laptop and internet connection" for low-barrier subnets, or actual specs like "Dedicated GPU (RTX 3080 or better), 32GB RAM, stable internet" for compute-heavy ones — base this on what's typical for the category you picked.

Respond in JSON only, no markdown formatting:
{{"category": "...", "difficulty": "...", "mining_criteria": "...", "estimated_roi": "...", "hardware_specs": "..."}}
"""
            response = requests.post(
                GEMINI_API,
                params={'key': self.gemini_key},
                json={
                    'contents': [{'parts': [{'text': prompt}]}],
                    'generationConfig': {'temperature': 0.4, 'maxOutputTokens': 600}
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
            logger.warning(f"Gemini error for subnet: {e}")
            return self._default()

    def _default(self) -> Dict[str, str]:
        return {
            'category': 'Mining',
            'difficulty': 'Intermediate',
            'mining_criteria': 'Bittensor subnet — see Taostats for details',
            'estimated_roi': 'ROI varies',
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
                    'Taostats Link': {'url': f'https://taostats.io/subnets/{d["id"]}'},
                    'Notes': {'rich_text': [{'text': {'content': d.get('mining_criteria', '')}}]},
                }
            }
            r = requests.post(f'{NOTION_API}/pages', headers=self.headers, json=page, timeout=10)
            if r.status_code >= 300:
                logger.error(f"Notion create failed for SN{d['id']} ({r.status_code}): {r.text[:200]}")
                return False
            logger.info(f"✅ Created SN{d['id']}")
            return True
        except Exception as e:
            logger.error(f"Create failed for SN{d['id']}: {e}")
            return False

    def update_subnet_page(self, page_id: str, d: Dict[str, Any]) -> bool:
        try:
            page = {
                'properties': {
                    'Validators': {'number': d.get('validators', 0)},
                    'Emissions per Block': {'rich_text': [{'text': {'content': str(d.get('burn', 'N/A'))}}]},
                    'Status': {'select': {'name': 'Active'}},
                }
            }
            r = requests.patch(f'{NOTION_API}/pages/{page_id}', headers=self.headers, json=page, timeout=10)
            return r.status_code < 300
        except Exception as e:
            logger.warning(f"Update failed: {e}")
            return False


def main():
    logger.info("🚀 Bittensor Subnet Auto-Populator")

    if not all([GEMINI_API_KEY, NOTION_API_KEY]):
        logger.error("Missing GEMINI_API_KEY or NOTION_API_KEY")
        sys.exit(1)

    logger.info("Connecting to Bittensor finney...")
    subtensor = bt.subtensor(network='finney')
    logger.info("✅ Connected")

    logger.info("Fetching all subnets via subtensor.subnets.all()...")
    raw_subnets = subtensor.subnets.all()
    logger.info(f"✅ Got {len(raw_subnets)} subnets from blockchain")

    enricher = SubnetEnricher(GEMINI_API_KEY)
    notion = NotionClient(NOTION_API_KEY, NOTION_DATABASE_ID)

    created = updated = failed = 0

    # Process first 15 this run — confirm it works end-to-end before scaling to all 129
    for info in raw_subnets[:15]:
        try:
            netuid = info.netuid
            subnet = {
                'id': netuid,
                'name': f'Subnet {netuid}',
                'validators': getattr(info, 'neuron_count', 0),
                'tempo': getattr(info, 'tempo', 'N/A'),
                'burn': getattr(info, 'burn', 'N/A'),
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
