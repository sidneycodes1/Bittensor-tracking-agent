#!/usr/bin/env python3
import os
import sys
import json
import time
import requests
from typing import Optional, Dict, Any
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
NOTION_API_KEY = os.getenv('NOTION_API_KEY')
COINGECKO_API_KEY = os.getenv('COINGECKO_API_KEY')
NOTION_DATABASE_ID = 'c38cadde-ded5-4c42-b24e-4acb3c4bcffa'

GEMINI_API = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent'
NOTION_API = 'https://api.notion.com/v1'
SUBNET_REGISTRY_URL = 'https://raw.githubusercontent.com/taostat/subnets-infos/main/subnets.json'
COINGECKO_MARKETS_URL = 'https://api.coingecko.com/api/v3/coins/markets'

OFFICIAL_TAGS = [
    'compute', 'llm-inference', 'prediction', 'fine-tuning', 'data-marketplace',
    'trading', 'reinforcement-learning', 'defi', 'price-prediction', 'data-scraping',
    'image-generation', 'simulation', 'search', 'data-labeling', 'bandwidth',
    'knowledge-verification', 'protein-folding', 'drug-discovery', 'text-embedding', 'storage'
]

import bittensor as bt
logger.info('Bittensor SDK ' + bt.__version__ + ' loaded')


def fetch_subnet_registry():
    try:
        r = requests.get(SUBNET_REGISTRY_URL, timeout=15)
        r.raise_for_status()
        registry = r.json()
        logger.info('Loaded real metadata for ' + str(len(registry)) + ' subnets from Taostats registry')
        return registry
    except Exception as e:
        logger.warning('Could not fetch subnet registry: ' + str(e))
        return {}


def fetch_coingecko_market_data():
    if not COINGECKO_API_KEY:
        logger.warning('No COINGECKO_API_KEY set - skipping market data')
        return {}
    market_by_name = {}
    try:
        for page in [1, 2]:
            params = {
                'vs_currency': 'usd',
                'category': 'bittensor-subnets',
                'per_page': 250,
                'page': page,
                'x_cg_demo_api_key': COINGECKO_API_KEY,
            }
            r = requests.get(COINGECKO_MARKETS_URL, params=params, timeout=15)
            if r.status_code != 200:
                logger.warning('CoinGecko request failed: ' + str(r.status_code) + ' ' + r.text[:200])
                break
            coins = r.json()
            if not coins:
                break
            for coin in coins:
                key = coin.get('name', '').strip().lower()
                if key:
                    market_by_name[key] = {
                        'price': coin.get('current_price'),
                        'market_cap': coin.get('market_cap'),
                        'change_24h': coin.get('price_change_percentage_24h'),
                    }
            time.sleep(1)
        logger.info('Loaded CoinGecko market data for ' + str(len(market_by_name)) + ' subnet tokens')
    except Exception as e:
        logger.warning('CoinGecko fetch failed: ' + str(e))
    return market_by_name


def match_market_data(subnet_name, market_by_name):
    if not subnet_name:
        return None
    key = subnet_name.strip().lower()
    if key in market_by_name:
        return market_by_name[key]
    for name_key in market_by_name:
        if key in name_key or name_key in key:
            return market_by_name[name_key]
    return None


class SubnetEnricher:
    def __init__(self, gemini_key):
        self.gemini_key = gemini_key

    def analyze(self, subnet_data):
        has_real_info = subnet_data.get('real_name') and subnet_data.get('real_description')
        tags_list = ', '.join(OFFICIAL_TAGS)

        try:
            if has_real_info:
                prompt = ('Someone with ZERO crypto background wants to understand this real Bittensor subnet.\n\n'
                           + 'Subnet #' + str(subnet_data['id']) + ': "' + subnet_data['real_name'] + '"\n'
                           + 'Official description: ' + subnet_data['real_description'] + '\n'
                           + 'Network stats: ' + str(subnet_data['validators']) + ' active nodes, registration cost '
                           + str(subnet_data.get('burn', 'unknown')) + ' TAO.\n\n'
                           + 'Based on this REAL description, write JSON with:\n'
                           + '"category": one of Mining, Development, Creator, Validator, Data\n'
                           + '"domain_tag": pick the SINGLE best match from this exact official list (use the exact spelling, lowercase, hyphenated as shown): ' + tags_list + '\n'
                           + '"difficulty": one of Beginner, Intermediate, Advanced\n'
                           + '"mining_criteria": 3-4 plain-English sentences explaining what this subnet does, what running a miner on it involves, and who it fits.\n'
                           + '"estimated_roi": one practical sentence on realistic earning expectations\n'
                           + '"hardware_specs": specific hardware needed for this subnet\'s actual task\n\n'
                           + 'Respond in JSON only, no markdown:\n'
                           + '{"category": "...", "domain_tag": "...", "difficulty": "...", "mining_criteria": "...", "estimated_roi": "...", "hardware_specs": "..."}')
            else:
                prompt = ('This Bittensor subnet (#' + str(subnet_data['id']) + ') has no public registry entry yet.\n\n'
                           + 'Network stats: ' + str(subnet_data['validators']) + ' active nodes, registration cost '
                           + str(subnet_data.get('burn', 'unknown')) + ' TAO.\n\n'
                           + 'Write JSON with:\n'
                           + '"category": your best guess from Mining, Development, Creator, Validator, Data\n'
                           + '"domain_tag": pick your best guess from this exact list: ' + tags_list + '\n'
                           + '"difficulty": Beginner, Intermediate, or Advanced\n'
                           + '"mining_criteria": Be honest that no official description exists yet. Suggest checking taostats.io/subnets/' + str(subnet_data['id']) + '. Do not fabricate.\n'
                           + '"estimated_roi": "Unknown - no public data available for this subnet yet"\n'
                           + '"hardware_specs": "Unknown - check taostats.io or the subnet Discord"\n\n'
                           + 'Respond in JSON only, no markdown:\n'
                           + '{"category": "...", "domain_tag": "...", "difficulty": "...", "mining_criteria": "...", "estimated_roi": "...", "hardware_specs": "..."}')

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

            domain_tag = data.get('domain_tag', '')
            if domain_tag not in OFFICIAL_TAGS:
                domain_tag = 'compute'

            return {
                'category': data.get('category', 'Mining'),
                'domain_tag': domain_tag,
                'difficulty': data.get('difficulty', 'Intermediate'),
                'mining_criteria': data.get('mining_criteria', 'Bittensor subnet'),
                'estimated_roi': data.get('estimated_roi', 'ROI varies'),
                'hardware_specs': data.get('hardware_specs', 'See official docs'),
            }
        except Exception as e:
            logger.warning('Gemini error for subnet ' + str(subnet_data.get('id')) + ': ' + str(e))
            return self._default()

    def _default(self):
        return {
            'category': 'Mining',
            'domain_tag': 'compute',
            'difficulty': 'Intermediate',
            'mining_criteria': 'No data available - see Taostats for details',
            'estimated_roi': 'Unknown',
            'hardware_specs': 'See official docs',
        }


class NotionClient:
    def __init__(self, api_key, database_id):
        self.database_id = database_id
        self.headers = {
            'Authorization': 'Bearer ' + api_key,
            'Notion-Version': '2022-06-28',
            'Content-Type': 'application/json',
        }

    def find_subnet(self, subnet_id):
        try:
            query = {'filter': {'property': 'Subnet ID', 'number': {'equals': subnet_id}}}
            r = requests.post(NOTION_API + '/databases/' + self.database_id + '/query',
                               headers=self.headers, json=query, timeout=10)
            results = r.json().get('results', [])
            return results[0]['id'] if results else None
        except Exception as e:
            logger.warning('Notion lookup failed for SN' + str(subnet_id) + ': ' + str(e))
            return None

    def _build_properties(self, d, include_create_only):
        props = {
            'Categories': {'multi_select': [{'name': d['category']}]},
            'Domain Tag': {'multi_select': [{'name': d['domain_tag']}]},
            'Difficulty': {'multi_select': [{'name': d['difficulty']}]},
            'Estimated ROI': {'rich_text': [{'text': {'content': d['estimated_roi']}}]},
            'Validators': {'number': d.get('validators', 0)},
            'Emissions per Block': {'rich_text': [{'text': {'content': str(d.get('burn', 'N/A'))}}]},
            'Hardware Specs': {'rich_text': [{'text': {'content': d.get('hardware_specs', 'See docs')}}]},
            'GitHub Link': {'url': d.get('github', '') or ''},
            'Notes': {'rich_text': [{'text': {'content': d.get('mining_criteria', '')}}]},
            'Status': {'select': {'name': 'Active'}},
        }
        if d.get('market_cap') is not None:
            props['Market Cap'] = {'rich_text': [{'text': {'content': '$' + format(d['market_cap'], ',.0f')}}]}
        if d.get('change_24h') is not None:
            props['24h Price Change'] = {'rich_text': [{'text': {'content': format(d['change_24h'], '.2f') + '%'}}]}
        if include_create_only:
            props['Subnet Name'] = {'title': [{'text': {'content': d['name']}}]}
            props['Subnet ID'] = {'number': d['id']}
            props['Taostats Link'] = {'url': 'https://taostats.io/subnets/' + str(d['id'])}
        else:
            props['Subnet Name'] = {'title': [{'text': {'content': d['name']}}]}
        return props

    def create_subnet_page(self, d):
        try:
            page = {
                'parent': {'database_id': self.database_id},
                'properties': self._build_properties(d, include_create_only=True)
            }
            r = requests.post(NOTION_API + '/pages', headers=self.headers, json=page, timeout=10)
            if r.status_code >= 300:
                logger.error('Notion create failed for SN' + str(d['id']) + ' (' + str(r.status_code) + '): ' + r.text[:200])
                return False
            logger.info('Created SN' + str(d['id']) + ': ' + d['name'])
            return True
        except Exception as e:
            logger.error('Create failed for SN' + str(d['id']) + ': ' + str(e))
            return False

    def update_subnet_page(self, page_id, d):
        try:
            page = {'properties': self._build_properties(d, include_create_only=False)}
            r = requests.patch(NOTION_API + '/pages/' + page_id, headers=self.headers, json=page, timeout=10)
            if r.status_code >= 300:
                logger.error('Notion update failed for SN' + str(d['id']) + ' (' + str(r.status_code) + '): ' + r.text[:200])
                return False
            logger.info('Updated SN' + str(d['id']) + ': ' + d['name'])
            return True
        except Exception as e:
            logger.warning('Update failed: ' + str(e))
            return False


def main():
    logger.info('Starting Bittensor Subnet Auto-Populator')

    if not all([GEMINI_API_KEY, NOTION_API_KEY]):
        logger.error('Missing GEMINI_API_KEY or NOTION_API_KEY')
        sys.exit(1)

    registry = fetch_subnet_registry()
    market_data = fetch_coingecko_market_data()

    logger.info('Connecting to Bittensor finney...')
    subtensor = bt.subtensor(network='finney')
    logger.info('Connected')

    logger.info('Fetching all subnets via subtensor.subnets.all()...')
    raw_subnets = subtensor.subnets.all()
    logger.info('Got ' + str(len(raw_subnets)) + ' subnets from blockchain')

    enricher = SubnetEnricher(GEMINI_API_KEY)
    notion = NotionClient(NOTION_API_KEY, NOTION_DATABASE_ID)

    created = 0
    updated = 0
    failed = 0

    for info in raw_subnets:
        try:
            netuid = info.netuid
            registry_entry = registry.get(str(netuid), {})
            real_name = registry_entry.get('name', '')
            real_description = registry_entry.get('description', '')
            real_github = registry_entry.get('github', '')

            display_name = real_name if real_name and real_name != 'Unknown' else 'Subnet ' + str(netuid)

            market = match_market_data(real_name, market_data)

            subnet = {
                'id': netuid,
                'name': display_name,
                'validators': getattr(info, 'neuron_count', 0),
                'burn': getattr(info, 'burn', 'N/A'),
                'real_name': real_name if real_name != 'Unknown' else '',
                'real_description': real_description,
                'github': real_github,
            }
            if market:
                subnet['market_cap'] = market.get('market_cap')
                subnet['change_24h'] = market.get('change_24h')

            enrichment = enricher.analyze(subnet)
            subnet_data = dict(subnet)
            subnet_data.update(enrichment)

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
            logger.error('Error on subnet ' + str(getattr(info, 'netuid', '?')) + ': ' + str(e))
            failed += 1

    logger.info('DONE - Created: ' + str(created) + ', Updated: ' + str(updated) + ', Failed: ' + str(failed))

    if created == 0 and updated == 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
