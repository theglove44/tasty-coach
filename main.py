#!/usr/bin/env python3
"""Tastytrade Auto - Orchestrator Agent"""

import sys
import asyncio
import argparse
import logging
import json
from typing import Optional
from datetime import datetime as dt, date

from utils.tasty_client import TastyClient
from agents.scanner import ScannerAgent
from agents.portfolio import PortfolioAgent
from agents.strategy import StrategyAgent
from agents.manager import RiskManager
from utils.market_schedule import MarketSchedule
from utils.launcher_ui import LauncherUI
from agents.options_researcher import OptionsResearcherAgent


def setup_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tastytrade Auto Orchestrator")
    parser.add_argument("--watchlist", "-w", type=str, help="Name of the watchlist to scan")
    parser.add_argument("--health", action="store_true", help="Run Portfolio Health Check only")
    parser.add_argument("--threshold", "-t", type=float, help="IVR threshold percentage")
    parser.add_argument("--test-connection", "-c", action="store_true", help="Test connection")
    parser.add_argument("--list-watchlists", "-l", action="store_true", help="List available watchlists")
    parser.add_argument("--market", "-m", action="store_true", help="Check Market Status")
    parser.add_argument("--snapshot", "-s", action="store_true", help="Market Snapshot")
    parser.add_argument("--json", "-j", action="store_true", help="Output snapshot as JSON (use with --snapshot)")
    parser.add_argument("--report", "-r", action="store_true", help="Generate Account Report (use --discord for Discord format)")
    parser.add_argument(
        "--history",
        choices=["week", "month", "year"],
        help="Review account performance over the previous week, month, or year",
    )
    parser.add_argument(
        "--history-month",
        type=str,
        metavar="YYYY-MM",
        help="Review account performance for a specific calendar month",
    )
    parser.add_argument("--menu", action="store_true", help="Open the interactive command menu")
    parser.add_argument("--transactions", action="store_true", help="Show recent transaction history")
    parser.add_argument("--orders", action="store_true", help="Show recent order history")
    parser.add_argument("--days", type=int, default=30, help="Days to look back (default: 30, use with --transactions/--orders)")
    parser.add_argument("--symbol", type=str, help="Filter by underlying symbol (use with --transactions/--orders)")
    parser.add_argument("--type", type=str, dest="txn_type", help="Filter transaction type: Trade, 'Receive Deliver', etc.")
    parser.add_argument("--sync", action="store_true", help="Sync trade history to local database")
    parser.add_argument("--sync-full", action="store_true", help="Full re-sync of trade history")
    parser.add_argument("--trades", action="store_true", help="Show trade groups from local DB")
    parser.add_argument("--trade", type=str, metavar="SYMBOL", help="Show trade groups for a specific underlying")
    parser.add_argument("--performance", action="store_true", help="Show trading performance summary")
    parser.add_argument("--performance-by-strategy", action="store_true", help="Show performance broken down by strategy type")
    parser.add_argument("--pl-daily", action="store_true", help="Show daily P/L summary")
    parser.add_argument("--pl-weekly", action="store_true", help="Show weekly P/L summary")
    parser.add_argument("--pl-monthly", action="store_true", help="Show monthly P/L summary")
    parser.add_argument("--equity-curve", action="store_true", help="Show NLV equity curve")
    parser.add_argument("--period", type=str, default="3m", help="Time period: 1m, 3m, 6m, 1y, all (default: 3m, use with --performance/--pl-*/--equity-curve)")
    parser.add_argument("--review-position", type=str, metavar="SYMBOL", help="Review position and show roll scenarios for underlying (e.g. --review-position SLV)")
    parser.add_argument("--output", "-o", type=str, help="Output file path for JSON export (use with --review-position)")
    parser.add_argument("--discord", "-d", action="store_true", help="Format output for Discord")
    parser.add_argument(
        "--account",
        type=str,
        help="Account number to use (e.g. 5WW46136). Alternatively set TASTY_ACCOUNT_NUMBER in .env",
    )
    parser.add_argument("--home", action="store_true", help="Unified account dashboard (portfolio, performance, risk).")
    parser.add_argument("--alerts", nargs="?", const=50, type=int, default=None, metavar="N", help="Print last N persisted alerts (default 50) for the resolved account.")
    parser.add_argument("--timeline", action="store_true", help="Event timeline (assignments, exercises, opens/closes, rolls) for the active account.")
    parser.add_argument("--timeline-days", type=int, default=30, help="Lookback window for --timeline (default 30).")
    parser.add_argument("--timeline-symbol", type=str, default=None, help="Optional underlying filter for --timeline.")
    parser.add_argument("--dashboard", action="store_true", help="Market Quality Dashboard (no account needed)")
    parser.add_argument("--html", action="store_true", help="Open dashboard in browser (use with --dashboard)")
    parser.add_argument("--research", metavar='SYMBOL', type=str, help="Research options chain for SYMBOL and output ranked trade ideas")
    parser.add_argument("--expiration", metavar='YYYY-MM-DD', type=str, help="Target expiration for --research (default: nearest monthly ~45 DTE)")
    parser.add_argument("--format", choices=['json', 'text'], default='text', help="Output format for --research (default: text)")
    parser.add_argument("--min-credit-ratio", type=float, default=None, help="Minimum credit as fraction of spread width (default: 0.25)")
    parser.add_argument("--min-delta", type=float, default=None, help="Minimum absolute short delta (default: 0.15)")
    parser.add_argument("--max-delta", type=float, default=None, help="Maximum absolute short delta (default: 0.45)")
    parser.add_argument("--force", action="store_true", help="Override Risk Manager blocks")
    parser.add_argument("--debug", "-D", action="store_true", help="Enable debug logging")
    return parser


def _warn_if_not_in_venv() -> None:
    if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        print(
            "⚠️  You are not running inside the project venv. "
            "If you see import/type errors, run: source venv/bin/activate"
        )


def _print_research_text(report: dict) -> None:
    """Print research report in human-readable text format"""
    symbol = report.get('symbol', '?')
    status = report.get('status', '?')
    expiration = report.get('expiration')
    dte = report.get('dte')
    resolution = report.get('expiration_resolution', '?')
    warnings = report.get('warnings', [])
    underlying = report.get('underlying', {})
    chain_summary = report.get('chain_summary', {})
    ideas = report.get('trade_ideas', [])

    print(f"\n{'='*80}")
    print(f"Options Research Report - {symbol}")
    print(f"{'='*80}")

    print(f"\nStatus: {status}")
    if expiration:
        print(f"Expiration: {expiration} ({dte} DTE)")
    print(f"Resolution Mode: {resolution}")

    if underlying:
        ivr_val = underlying.get('ivr')
        iv_val = underlying.get('iv')
        if ivr_val is not None:
            print(f"IVR: {ivr_val:.1f}%")
        else:
            print("IVR: N/A")
        if iv_val is not None:
            print(f"IV: {iv_val:.1%}")
        else:
            print("IV: N/A")

    if chain_summary:
        print(f"\nChain Summary:")
        print(f"  Total Strikes: {chain_summary.get('total_strikes', 0)}")
        print(f"  Calls: {chain_summary.get('calls', 0)}")
        print(f"  Puts: {chain_summary.get('puts', 0)}")
        print(f"  Strikes with Greeks: {chain_summary.get('strikes_with_greeks', 0)}")

    if warnings:
        print(f"\nWarnings:")
        for w in warnings:
            print(f"  • {w}")

    if not ideas:
        print(f"\nNo viable trade ideas found.")
        return

    print(f"\n{'='*80}")
    print(f"Trade Ideas ({len(ideas)} ranked)")
    print(f"{'='*80}")

    for idea in ideas:
        rank = idea.get('rank')
        strategy = idea.get('strategy', '?')
        dte_idea = idea.get('dte', 0)
        width = idea.get('width', 0)
        credit = idea.get('credit', 0)
        max_loss = idea.get('max_loss', 0)
        credit_pct = idea.get('credit_pct_of_width', 0)
        short_delta = idea.get('short_delta', 0)
        pop = idea.get('pop_estimate', 0)
        score = idea.get('score', 0)
        score_breakdown = idea.get('score_breakdown', {})
        breakevens = idea.get('breakevens', [])
        net_greeks = idea.get('net_greeks', {})
        legs = idea.get('legs', [])

        print(f"\n[{rank}] {strategy}")
        print(f"    {'─'*76}")
        print(f"    Width: ${width:.2f} | Credit: ${credit:.2f} ({credit_pct:.1%}) | Max Loss: ${max_loss:.2f}")
        print(f"    Short Delta: {short_delta:.2f} | POP: {pop:.1%} | DTE: {dte_idea}")
        print(f"    Breakeven: {', '.join(f'${be:.2f}' for be in breakevens)}")
        print(f"    Net Greeks: Δ={net_greeks.get('delta', 0):.2f}, Γ={net_greeks.get('gamma', 0):.4f}, " +
              f"Θ={net_greeks.get('theta', 0):.2f}, ν={net_greeks.get('vega', 0):.2f}")
        print(f"    Score: {score:.1f}/100")
        if score_breakdown:
            raw = score_breakdown.get('raw_components', {})
            print(f"      Credit: {raw.get('credit_component', 0):.2f}, " +
                  f"Delta: {raw.get('delta_component', 0):.2f}, " +
                  f"DTE: {raw.get('dte_component', 0):.2f}, " +
                  f"Liquidity: {raw.get('liquidity_component', 0):.2f}")

        print(f"\n    Legs:")
        for i, leg in enumerate(legs, 1):
            action = leg.get('action', '?')
            opt_type = leg.get('option_type', '?')
            strike = leg.get('strike', 0)
            bid = leg.get('bid')
            ask = leg.get('ask')
            mid = leg.get('mid')
            oi = leg.get('open_interest', 0)
            delta = leg.get('delta', 0)

            mid_str = f"${mid:.2f}" if mid else "N/A"
            bid_ask_str = ""
            if bid is not None and ask is not None:
                bid_ask_str = f" (bid: ${bid:.2f}, ask: ${ask:.2f})"

            print(f"      [{i}] {action:4s} {opt_type:4s} ${strike:7.2f} @ {mid_str}{bid_ask_str} " +
                  f"(OI: {oi:5d}, Δ: {delta:6.2f})")


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

        if args.menu or (len(sys.argv) == 1 and sys.stdin.isatty() and sys.stdout.isatty()):
            launcher = LauncherUI(
                client,
                session,
                account_number=args.account or client.config.account_number,
                default_threshold=args.threshold or client.config.ivr_threshold,
            )
            return await launcher.run()

        if args.home:
            account_number = args.account or client.config.account_number
            accounts = await client.get_accounts()
            if len(accounts) > 1 and not account_number:
                print("❌ Multiple accounts found. Please set TASTY_ACCOUNT_NUMBER in .env or pass --account.")
                for a in accounts:
                    acct_num = getattr(a, "account_number", "?")
                    nickname = getattr(a, "nickname", "") or ""
                    extra = f" ({nickname})" if nickname else ""
                    print(f"  • {acct_num}{extra}")
                return 1
            from utils.dashboard_ui import run_account_dashboard
            return await run_account_dashboard(session, account_number=account_number)

        if args.alerts is not None:
            account_number = args.account or client.config.account_number
            accounts = await client.get_accounts()
            if not accounts:
                print("❌ No linked accounts found for this session.")
                return 1
            if len(accounts) > 1 and not account_number:
                print("❌ Multiple accounts found. Please set TASTY_ACCOUNT_NUMBER in .env or pass --account.")
                return 1
            if not account_number:
                account_number = getattr(accounts[0], "account_number", None)
            if not account_number:
                print("❌ Could not resolve an account number for --alerts.")
                return 1
            from utils.alert_store import AlertStore, print_alert_history
            from utils.db import TradeDB
            db = TradeDB()
            try:
                print_alert_history(AlertStore(db), account_number, limit=args.alerts)
            finally:
                db.close()
            return 0

        if args.timeline:
            account_number = args.account or client.config.account_number
            accounts = await client.get_accounts()
            if not accounts:
                print("❌ No linked accounts found for this session.")
                return 1
            if len(accounts) > 1 and not account_number:
                print("❌ Multiple accounts found. Please set TASTY_ACCOUNT_NUMBER in .env or pass --account.")
                for a in accounts:
                    acct_num = getattr(a, "account_number", "?")
                    nickname = getattr(a, "nickname", "") or ""
                    extra = f" ({nickname})" if nickname else ""
                    print(f"  • {acct_num}{extra}")
                return 1
            if not account_number:
                account_number = getattr(accounts[0], "account_number", None)
            if not account_number:
                print("❌ Could not resolve an account number for --timeline.")
                return 1
            from utils.timeline_ui import run_timeline
            return await run_timeline(
                session=session,
                account_number=account_number,
                days=args.timeline_days,
                symbol=args.timeline_symbol,
            )

        if args.dashboard:
            from agents.dashboard import run_dashboard
            return await run_dashboard(session, html=args.html)

        if args.research:
            symbol = args.research.strip().upper()
            exp_date = None
            if args.expiration:
                try:
                    exp_date = dt.strptime(args.expiration, '%Y-%m-%d').date()
                except ValueError:
                    print(f"Invalid --expiration format: {args.expiration}. Use YYYY-MM-DD.")
                    return 2

            agent = OptionsResearcherAgent(
                session,
                min_credit_ratio=args.min_credit_ratio,
                min_delta=args.min_delta,
                max_delta=args.max_delta,
            )
            report = await agent.research(symbol, exp_date)

            if args.format == 'json':
                print(json.dumps(report, indent=2, default=str))
            else:
                _print_research_text(report)

            status = report.get('status', '')
            if status in ('INVALID_SYMBOL', 'NO_CHAIN', 'EXPIRATION_NOT_FOUND'):
                return 2
            return 0

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
            if not args.json:
                print("\n📸 Fetching Market Snapshot...")
            symbols = await scanner.get_symbols_from_watchlist("Snapshot", equity_only=False)

            if not symbols:
                print("❌ Watchlist 'Snapshot' not found or empty.")
                print("   Please create a watchlist named 'Snapshot' with your desired symbols (e.g. /ESH6, /NQH6, VIX)")
                return 1

            snapshot_data = await scanner.get_market_snapshot(symbols)

            if args.json:
                await scanner.enrich_with_iv(snapshot_data)
                scanner.print_snapshot_json(snapshot_data)
            else:
                scanner.print_snapshot(snapshot_data)
            return 0

        if args.report:
            print("\nGenerating Account Report...")
            await portfolio.print_positions_report(discord=args.discord)
            return 0

        if args.history or args.history_month:
            from agents.history import AccountHistoryAgent

            if args.history and args.history_month:
                print("❌ Use either --history or --history-month, not both.")
                return 1

            history = await AccountHistoryAgent(
                session,
                account_number=account_number,
            ).init()
            report = await history.build_performance_report(
                range_name=args.history,
                month=args.history_month,
            )
            history.print_performance_report(report, discord=args.discord)
            return 0

        if args.transactions:
            from agents.history import HistoryAgent

            print(f"\nFetching transaction history (last {args.days} days)...")
            history = await HistoryAgent(session, account_number=account_number).init()
            transactions = await history.get_transactions(
                days=args.days,
                symbol=args.symbol,
                transaction_type=args.txn_type,
            )
            history.print_transactions(transactions, discord=args.discord)
            return 0

        if args.orders:
            from agents.history import HistoryAgent

            print(f"\nFetching order history (last {args.days} days)...")
            history = await HistoryAgent(session, account_number=account_number).init()
            orders = await history.get_orders(
                days=args.days,
                symbol=args.symbol,
            )
            history.print_orders(orders, discord=args.discord)
            return 0

        if args.sync or args.sync_full:
            from agents.history import HistoryAgent

            mode = "full" if args.sync_full else "incremental"
            print(f"\nSyncing trade history ({mode})...")
            history = await HistoryAgent(session, account_number=account_number).init()
            result = await history.sync(full=args.sync_full)
            print(
                f"Synced: {result['transactions']} transactions, "
                f"{result['orders']} orders, "
                f"{result['groups']} new trade groups"
            )
            return 0

        if args.trades or args.trade:
            from agents.history import HistoryAgent

            history = await HistoryAgent(session, account_number=account_number).init()
            acct = account_number or (history.account.account_number if history.account else "")
            history.print_trade_groups(
                acct,
                underlying=args.trade,
                discord=args.discord,
            )
            return 0

        if args.performance or args.performance_by_strategy:
            from agents.analytics import AnalyticsAgent

            analytics = await AnalyticsAgent(session, account_number=account_number).init()
            start = analytics._parse_period(args.period)
            start_str = start.isoformat() if start else None

            if args.performance_by_strategy:
                strategies = analytics.get_strategy_performance(start_date=start_str)
                analytics.print_strategy_breakdown(strategies, discord=args.discord)
            else:
                summary = analytics.get_performance_summary(start_date=start_str)
                analytics.print_performance(summary, discord=args.discord)
            return 0

        if args.pl_daily or args.pl_weekly or args.pl_monthly:
            from agents.analytics import AnalyticsAgent

            analytics = await AnalyticsAgent(session, account_number=account_number).init()
            start = analytics._parse_period(args.period)
            start_str = start.isoformat() if start else None

            if args.pl_daily:
                data = analytics.get_daily_pl(start_date=start_str)
                analytics.print_pl_summary(data, "day", discord=args.discord)
            elif args.pl_weekly:
                data = analytics.get_weekly_pl(start_date=start_str)
                analytics.print_pl_summary(data, "week", discord=args.discord)
            else:
                data = analytics.get_monthly_pl(start_date=start_str)
                analytics.print_pl_summary(data, "month", discord=args.discord)
            return 0

        if args.equity_curve:
            from agents.analytics import AnalyticsAgent

            analytics = await AnalyticsAgent(session, account_number=account_number).init()
            time_back_map = {"1m": "1m", "3m": "3m", "6m": "6m", "1y": "1y", "2y": "2y", "all": "all"}
            time_back = time_back_map.get(args.period, "1y")
            data = await analytics.get_equity_curve(time_back=time_back)
            analytics.print_equity_curve(data, discord=args.discord)
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
            for w in PrivateWatchlist.get(session):
                print(f"  • {w.name}")
            print("\nPublic Watchlists:")
            for w in PublicWatchlist.get(session):
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
            symbols = await scanner.get_symbols_from_watchlist(args.watchlist, equity_only=False)
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
