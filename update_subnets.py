#!/usr/bin/env python3
"""
Bittensor SDK Diagnostic
Connects to the chain and lists every method related to 'subnet' or 'metagraph'
that actually exists on this installed SDK version, so we stop guessing.
"""

import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    import bittensor as bt
    logger.info(f"✅ Bittensor SDK loaded — version: {getattr(bt, '__version__', 'unknown')}")
except ImportError:
    os.system('pip install bittensor')
    import bittensor as bt


def main():
    logger.info("Connecting to Bittensor finney...")
    subtensor = bt.subtensor(network='finney')
    logger.info("✅ Connected")

    all_methods = dir(subtensor)

    subnet_related = [m for m in all_methods if 'subnet' in m.lower() and not m.startswith('_')]
    metagraph_related = [m for m in all_methods if 'metagraph' in m.lower() and not m.startswith('_')]
    netuid_related = [m for m in all_methods if 'netuid' in m.lower() and not m.startswith('_')]

    logger.info(f"\n{'='*60}")
    logger.info(f"METHODS CONTAINING 'subnet' ({len(subnet_related)} found):")
    for m in subnet_related:
        logger.info(f"  - {m}")

    logger.info(f"\nMETHODS CONTAINING 'metagraph' ({len(metagraph_related)} found):")
    for m in metagraph_related:
        logger.info(f"  - {m}")

    logger.info(f"\nMETHODS CONTAINING 'netuid' ({len(netuid_related)} found):")
    for m in netuid_related:
        logger.info(f"  - {m}")

    logger.info(f"{'='*60}\n")

    # Try the most likely candidates and show what they actually return
    candidates = [
        'get_subnets',
        'all_subnets',
        'subnets',
        'get_all_subnets_info',
        'get_metagraph_info',
        'metagraph',
        'get_subnet_info',
        'subnet_exists',
    ]

    logger.info("Testing likely candidates:")
    for name in candidates:
        if hasattr(subtensor, name):
            attr = getattr(subtensor, name)
            logger.info(f"  ✅ EXISTS: {name} -> {type(attr)}")
            if callable(attr):
                try:
                    import inspect
                    sig = inspect.signature(attr)
                    logger.info(f"     signature: {name}{sig}")
                except Exception as e:
                    logger.info(f"     (could not get signature: {e})")
        else:
            logger.info(f"  ❌ missing: {name}")

    logger.info("\nDiagnostic complete. Copy the full log output back to Claude.")


if __name__ == '__main__':
    main()
