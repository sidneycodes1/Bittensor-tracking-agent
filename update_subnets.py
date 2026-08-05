#!/usr/bin/env python3
"""
Bittensor SDK Diagnostic v2
subtensor.subnets is a namespace object (not a plain method) in SDK v11.
This inspects what's actually callable inside it.
"""

import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

import bittensor as bt
logger.info(f"Bittensor SDK version: {bt.__version__}")

subtensor = bt.subtensor(network='finney')
logger.info("✅ Connected")

ns = subtensor.subnets
logger.info(f"subtensor.subnets is: {type(ns)}")

methods = [m for m in dir(ns) if not m.startswith('_')]
logger.info(f"\n{'='*60}")
logger.info(f"METHODS/ATTRS on subtensor.subnets ({len(methods)} found):")
for m in methods:
    attr = getattr(ns, m)
    kind = 'callable' if callable(attr) else 'value'
    logger.info(f"  - {m}  ({kind})")
logger.info(f"{'='*60}\n")

# Try the most likely ones and show actual results
likely = ['all', 'all_info', 'get_all', 'list', 'get', 'info', 'all_subnets']
for name in likely:
    if hasattr(ns, name):
        attr = getattr(ns, name)
        logger.info(f"✅ FOUND: subnets.{name}")
        if callable(attr):
            try:
                import inspect
                sig = inspect.signature(attr)
                logger.info(f"   signature: {name}{sig}")
            except Exception as e:
                logger.info(f"   (no signature: {e})")
            # Try actually calling it with no args
            try:
                result = attr()
                logger.info(f"   ✅ CALLED SUCCESSFULLY. Result type: {type(result)}")
                if hasattr(result, '__len__'):
                    logger.info(f"   Length: {len(result)}")
                if hasattr(result, '__iter__'):
                    first = next(iter(result), None)
                    if first is not None:
                        logger.info(f"   First item type: {type(first)}")
                        logger.info(f"   First item attrs: {[a for a in dir(first) if not a.startswith('_')][:20]}")
                        logger.info(f"   First item repr: {repr(first)[:300]}")
            except Exception as e:
                logger.info(f"   ❌ call failed: {e}")

logger.info("\nDiagnostic v2 complete. Copy the full log output back to Claude.")
