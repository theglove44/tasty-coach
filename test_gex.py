#!/usr/bin/env python3
"""Quick test of the GEX agent."""

import asyncio
import logging
from utils.tasty_client import TastyClient
from agents.gex import GEXAgent

logging.basicConfig(level=logging.INFO)

async def main():
    # Authenticate
    client = TastyClient()
    if not client.authenticate():
        print("Authentication failed")
        return
    
    session = client.get_session()
    
    # Create agent and run
    agent = GEXAgent(session)
    
    # Test with SPY (faster than SPX)
    result = await agent.calculate_gex('SPY', max_dte=7, data_wait_seconds=3.0)
    
    if result.error:
        print(f"Error: {result.error}")
        return
    
    # Print report
    print(agent.generate_report(result))
    print()
    print("--- Gamma Walls ---")
    print(agent.get_gamma_walls(result))
    print()
    print("--- Regime Analysis ---")
    print(agent.analyze_regime(result))

if __name__ == '__main__':
    asyncio.run(main())
