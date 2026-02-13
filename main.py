#!/usr/bin/env python3
"""Tastytrade Auto - Orchestrator Agent"""

import sys
import asyncio
import argparse
import logging
from typing import Optional

from utils.tasty_client import TastyClient
from agents.scanner import ScannerAgent
from agents.portfolio import PortfolioAgent
from agents.strategy import StrategyAgent
from agents.manager import RiskManager
from utils.market_schedule import MarketSchedule


def setup_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tastytrade Auto Orchestrator")
    parser.add_argument("--watchlist", "-w", type=str, help="Name of the watchlist to scan")
    parser.add_argument("--health", action="store_true", help="Run Portfolio Health Check only")
    parser.add_argument("--threshold", "-t", type=float, help="IVR threshold percentage")
    parser.add_argument("--test-connection", "-c", action="store_true", help="Test connection")
    parser.add_argument("--list-watchlists", "-l", action="store_true", help="List available watchlists")
    parser.add_argument("--market", "-m", action="store_true", help="Check Market Status")
    parser.add_argument("--snapshot", "-s", action="store_true", help="Market Snapshot")
    parser.add_argument("--report", "-r", action="store_true", help="Generate Account Report (use --discord for Discord format)")
    parser.add_argument("--review-position", type=str, metavar="SYMBOL", help="Review position and show roll scenarios for underlying (e.g. --review-position SLV)")
    parser.add_argument("--output", "-o", type=str, help="Output file path for JSON export (use with --review-position)")
    parser.add_argument("--discord", "-d", action="store_true", help="Format output for Discord")
    parser.add_argument(
        "--account",
        type=str,
        help="Account number to use (e.g. 5WW46136). Alternatively set TASTY_ACCOUNT_NUMBER in .env",
    )
    parser.add_argument("--force", action="store_true", help="Override Risk Manager blocks")
    parser.add_argument("--debug", "-D", action="store_true", help="Enable debug logging")
    return parser


def _warn_if_not_in_venv() -> None:
    if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        print(
            "⚠️  You are not running inside the project venv. "
            "If you see import/type errors, run: source venv/bin/activate"
        )


async def async_main() -> int:
    _warn_if_not_in_venv()

    parser = setup_argument_parser()
    args = parser.parse_args()

    client = TastyClient()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(
            getattr(logging, client.config.log_level.upper(), logging.INFO)
        )

    try:
        if args.test_connection:
            print("Testing connection...")
            if client.authenticate():
                print("✅ Authentication successful")
                accounts = await client.get_accounts()
                print(f"✅ Found {len(accounts)} accounts")
                for a in accounts:
                    acct_num = getattr(a, "account_number", "?")
                    nickname = getattr(a, "nickname", "") or ""
                    extra = f" ({nickname})" if nickname else ""
                    print(f"  • {acct_num}{extra}")
                if len(accounts) > 1:
                    print(
                        "\nTip: set TASTY_ACCOUNT_NUMBER in your .env "
                        "(e.g. TASTY_ACCOUNT_NUMBER=5WW46136) or pass --account."
                    )
                return 0
            else:
                print("❌ Authentication failed")
                return 1

        session = client.get_session()
        if not session:
            print("❌ Failed to establish session")
            return 1

        account_number: Optional[str] = args.account or client.config.account_number

        # If the user has multiple accounts, force explicit selection
        accounts = await client.get_accounts()
        if len(accounts) > 1 and not account_number:
            print("❌ Multiple accounts found. Please set TASTY_ACCOUNT_NUMBER in .env or pass --account.")
            for a in accounts:
                acct_num = getattr(a, "account_number", "?")
                nickname = getattr(a, "nickname", "") or ""
                extra = f" ({nickname})" if nickname else ""
                print(f"  • {acct_num}{extra}")
            return 1

        scanner = ScannerAgent(session, threshold=args.threshold or client.config.ivr_threshold)
        portfolio = PortfolioAgent(session, account_number=account_number)
        await portfolio.init()  # Async initialization
        strategy = StrategyAgent(session)
        risk_manager = RiskManager(session, account_number=account_number)
        market_schedule = MarketSchedule(session)

        if args.market:
            market_schedule.print_status()
            return 0

        if args.snapshot:
            print("\n📸 Fetching Market Snapshot...")
            symbols = await scanner.get_symbols_from_watchlist("Snapshot", equity_only=False)
            
            if not symbols:
                print("❌ Watchlist 'Snapshot' not found or empty.")
                print("   Please create a watchlist named 'Snapshot' with your desired symbols (e.g. /ESH6, /NQH6, VIX)")
                return 1
            
            snapshot_data = await scanner.get_market_snapshot(symbols)
            scanner.print_snapshot(snapshot_data)
            return 0

        if args.report:
            print("\nGenerating Account Report...")
            await portfolio.print_positions_report(discord=args.discord)
            return 0

        if args.review_position:
            from agents.reviewer import ReviewerAgent

            print(f"\n📋 Reviewing positions for {args.review_position}...")
            reviewer = await ReviewerAgent(session, account_number=account_number).init()

            results = await reviewer.review_positions(underlying_filter=args.review_position)

            if not results:
                print(f"❌ No positions found for {args.review_position}")
                return 1

            # Print formatted report (or JSON if --output flag provided)
            if args.output:
                reviewer.export_json(results, args.output)
            else:
                reviewer.print_review_report(results, discord=args.discord)

            return 0

        if args.list_watchlists:
            from tastytrade.watchlists import PrivateWatchlist, PublicWatchlist

            print("\nPrivate Watchlists:")
            for w in await PrivateWatchlist.get(session):
                print(f"  • {w.name}")
            print("\nPublic Watchlists:")
            for w in await PublicWatchlist.get(session):
                print(f"  • {w.name}")
            return 0

        if args.watchlist or args.health:
            # 1. Account Risk & Health Check
            print("\n🏥 Checking Portfolio Health...")

            risk_report = await risk_manager.calculate_portfolio_risk()

            print(f"💰 NLV: ${risk_report['nlv']:,.2f}")
            print(
                f"📊 BP Usage: {risk_report['bp_usage_pct']:.2f}% [{risk_report['bp_usage_status']}]"
            )
            print(f"💵 Cash: ${risk_report['cash_balance']:,.2f} | Day Trade BP: ${risk_report['day_trading_buying_power']:,.2f}")
            if risk_report.get('day_trade_excess') is not None:
                print(f"📉 Day Trade Excess: ${risk_report['day_trade_excess']:,.2f}")

            print(
                f"⚖️  Portfolio Delta: {risk_report['portfolio_delta']:.2f} | Theta: {risk_report['portfolio_theta']:.2f} [{risk_report['theta_status']}]"
            )

            if risk_report["trade_size_warnings"]:
                print("\n⚠️  Trade Size Warnings (>5% NLV):")
                for warn in risk_report["trade_size_warnings"]:
                    print(f"  • {warn}")
            else:
                print("✅ Trade Sizes: OK")
            
            if risk_report.get("session_warnings"):
                print("\n🕒 Market Session Warnings:")
                for warn in risk_report["session_warnings"]:
                    print(f"  • {warn}")

            # Blocking Logic
            is_critical_failure = False
            if risk_report["bp_usage_pct"] > 50.0:
                print("\n⛔ CRITICAL: Buying Power Usage exceeds 50% limit!")
                is_critical_failure = True

            if is_critical_failure:
                if args.force:
                    print(
                        "⚠️  Proceeding despite critical risk failures due to --force flag."
                    )
                else:
                    print("\n🛑 Execution BLOCKED by Risk Manager. Use --force to override.")
                    return 1

            if args.health:
                return 0

            # 2. Manage existing positions
            positions = await portfolio.get_positions()
            if positions:
                print("\n🔄 Checking existing positions for management...")
                to_close = await strategy.manage_positions(positions)
                if to_close:
                    print(f"⚠️ {len(to_close)} positions hit exit criteria:")
                    for item in to_close:
                        print(f"  • {item['position'].symbol}: {item['reason']}")
                else:
                    print("✅ All positions within parameters.")

            # 3. Scan for new opportunities
            print(f"\n🔍 Scanning watchlist: {args.watchlist}")
            symbols = await scanner.get_symbols_from_watchlist(args.watchlist)
            if not symbols:
                print(f"❌ No symbols found in {args.watchlist}")
                return 1

            print(f"⏳ Analyzing {len(symbols)} symbols...")
            results = await scanner.scan_ivr(symbols)
            targets = scanner.get_high_ivr_targets(results)
            print(scanner.generate_report(targets))

            if targets:
                print(f"\n🔍 Screening strategies for {len(targets)} high IVR targets...")
                all_strategy_targets = []

                for t in targets:
                    strategy_targets = await strategy.screen_strategies(t.symbol, t.iv_rank)
                    all_strategy_targets.extend(strategy_targets)

                if all_strategy_targets:
                    print("")
                    strategy.print_strategy_report(all_strategy_targets)
                else:
                    print("\nNo valid strategies found for these targets based on criteria.")

            return 0

        print("Use --watchlist to scan, --health to check risk, or --help for options")
        return 1

    except KeyboardInterrupt:
        print("\n⚠️  Operation cancelled")
        return 130
    except Exception as e:
        print(f"❌ Error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
