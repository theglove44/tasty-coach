"""Interactive terminal launcher for tastytrade-coach."""

import asyncio
from difflib import SequenceMatcher
import os
import select
import sys
import termios
import tty
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional, Sequence

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from agents.history import AccountHistoryAgent
from agents.manager import RiskManager
from agents.portfolio import PortfolioAgent
from agents.reviewer import ReviewerAgent
from agents.scanner import IVRData, ScannerAgent
from agents.strategy import StrategyAgent
from utils.market_schedule import MarketSchedule
from utils.tasty_client import TastyClient
from tastytrade.watchlists import PrivateWatchlist, PublicWatchlist
from tastytrade.market_data import get_market_data_by_type
from tastytrade.metrics import get_market_metrics


@dataclass
class LauncherContext:
    """Holds the currently selected account-scoped agents."""

    account_number: Optional[str]
    portfolio: PortfolioAgent
    strategy: StrategyAgent
    risk_manager: RiskManager
    market_schedule: MarketSchedule


@dataclass
class LauncherAction:
    """Describes one launcher action."""

    key: str
    title: str
    description: str
    handler: Callable[[], Awaitable[None]]
    exit_on_run: bool = False
    shortcut: Optional[str] = None


class LauncherUI:
    """Interactive launcher that wraps the existing command-line actions."""

    def __init__(
        self,
        client: TastyClient,
        session,
        account_number: Optional[str] = None,
        default_threshold: Optional[float] = None,
    ) -> None:
        self.client = client
        self.session = session
        self.account_number = account_number
        self.default_threshold = default_threshold
        self.console = Console()
        self.context: Optional[LauncherContext] = None
        self.refresh_interval = 5.0
        self.show_help = False
        self.last_health_report: Optional[dict[str, Any]] = None
        self._watchlist_symbol_cache: dict[str, list[str]] = {}

    async def run(self) -> int:
        """Run the interactive launcher loop."""
        await self._ensure_context()
        actions = self._actions()
        selected = 0

        while True:
            self._render_home(actions, selected)
            key = await self._read_key(timeout=self.refresh_interval)
            if key is None:
                continue

            if key == "F1":
                self.show_help = not self.show_help
                continue
            if key == "F2":
                continue
            if key == "F3":
                await self._run_watchlist_scan()
                await self._pause()
                continue
            if key == "F4":
                await self._run_market_status()
                await self._pause()
                continue
            if key == "F5":
                await self._run_health_check()
                await self._pause()
                continue
            if key == "F10":
                return 0

            if key in {"UP", "k"}:
                selected = (selected - 1) % len(actions)
                continue
            if key in {"DOWN", "j"}:
                selected = (selected + 1) % len(actions)
                continue
            if key == "ENTER":
                action = actions[selected]
                if action.exit_on_run:
                    return 0
                await action.handler()
                await self._pause()
                actions = self._actions()
                selected = min(selected, len(actions) - 1)
                continue

            if key in {action.key for action in actions}:
                action = next(action for action in actions if action.key == key)
                if action.exit_on_run:
                    return 0
                await action.handler()
                await self._pause()
                actions = self._actions()
                selected = min(selected, len(actions) - 1)
                continue

            if key == "ESC":
                continue

    async def _ensure_context(self) -> None:
        """Resolve the active account and create account-scoped agents."""
        if self.context:
            return

        account_number = await self._select_account()
        portfolio = PortfolioAgent(self.session, account_number=account_number)
        await portfolio.init()
        self.context = LauncherContext(
            account_number=account_number,
            portfolio=portfolio,
            strategy=StrategyAgent(self.session),
            risk_manager=RiskManager(self.session, account_number=account_number),
            market_schedule=MarketSchedule(self.session),
        )

    async def _select_account(self) -> Optional[str]:
        """Prompt for an account when more than one is available."""
        accounts = await self.client.get_accounts()
        if not accounts:
            raise ValueError("No accounts found.")

        if self.account_number:
            return self.account_number

        if len(accounts) == 1:
            acct = accounts[0]
            self.console.print(
                f"[dim]Using account {getattr(acct, 'account_number', '?')}[/dim]"
            )
            return getattr(acct, "account_number", None)

        selected = 0
        while True:
            self.console.clear()
            self.console.print(
                Panel.fit(
                    "[bold]Select Account[/bold]\nUse [cyan]up/down[/cyan] and [cyan]enter[/cyan].",
                    border_style="cyan",
                )
            )

            table = Table(box=box.ROUNDED, expand=False, show_header=True)
            table.add_column(" ", width=2)
            table.add_column("Account", style="bold")
            table.add_column("Nickname", style="dim")

            for idx, acct in enumerate(accounts):
                style = "bold black on cyan" if idx == selected else ""
                table.add_row(
                    ">" if idx == selected else " ",
                    getattr(acct, "account_number", "?"),
                    getattr(acct, "nickname", "") or "",
                    style=style,
                )

            self.console.print(table)
            key = await self._read_key()
            if key in {"UP", "k"}:
                selected = (selected - 1) % len(accounts)
            elif key in {"DOWN", "j"}:
                selected = (selected + 1) % len(accounts)
            elif key == "ENTER":
                chosen = accounts[selected]
                return getattr(chosen, "account_number", None)

    def _actions(self) -> list[LauncherAction]:
        """Build the current list of launcher actions."""
        return [
            LauncherAction("1", "Market status", "Open/close state and session timing", self._run_market_status, shortcut="F4"),
            LauncherAction("2", "Portfolio health", "Buying power, cash, theta, and risk checks", self._run_health_check, shortcut="F5"),
            LauncherAction(
                "3",
                "Watchlist workflow",
                "Risk check, manage positions, scan, and screen",
                self._run_watchlist_scan,
                shortcut="F3",
            ),
            LauncherAction("4", "Market snapshot", "Quick snapshot for a watchlist", self._run_market_snapshot),
            LauncherAction("5", "Account report", "Positions report for the selected account", self._run_account_report),
            LauncherAction("6", "History report", "Performance over week/month/year", self._run_history_report),
            LauncherAction("7", "Review position", "Roll scenarios for a single symbol", self._run_review_position),
            LauncherAction("8", "List watchlists", "Show private and public watchlists", self._run_list_watchlists),
            LauncherAction("d", "Account dashboard", "Unified portfolio, performance, and risk view", self._run_account_dashboard),
            LauncherAction("t", "Event timeline", "Recent fills, assignments, exercises, and rolls", self._run_event_timeline),
            LauncherAction("9", "Dashboard", "Open the market quality dashboard", self._run_dashboard),
            LauncherAction("a", "Switch account", "Pick a different linked account", self._switch_account),
            LauncherAction("s", "Settings", "Edit thresholds and alert toggles", self._run_settings_editor),
            LauncherAction("q", "Quit", "Exit the launcher", self._quit, exit_on_run=True, shortcut="F10"),
        ]

    def _render_home(self, actions: Sequence[LauncherAction], selected: int) -> None:
        """Draw the launcher header and action list."""
        self.console.clear()

        account = self.context.account_number if self.context else self.account_number or "Unknown"
        market_panel = self._build_market_status_panel()
        account_panel = self._build_account_panel(account)

        self.console.print(Columns([market_panel, account_panel], equal=True, expand=True))

        actions_table = Table(box=box.ROUNDED, expand=True, show_header=True)
        actions_table.add_column("Key", style="bold cyan", width=5)
        actions_table.add_column("Action", style="bold")
        actions_table.add_column("What it does", style="dim")
        actions_table.add_column("Hotkey", style="magenta", width=8)

        for idx, action in enumerate(actions):
            row_style = "bold black on cyan" if idx == selected else ""
            actions_table.add_row(
                action.key,
                action.title,
                action.description,
                action.shortcut or "",
                style=row_style,
            )

        focus = actions[selected]
        detail = Panel(
            Text.from_markup(
                f"[bold]{focus.title}[/bold]\n\n"
                f"{focus.description}\n\n"
                f"[dim]Use arrow keys or press [cyan]{focus.key}[/cyan] to run this action."
                f"{f' Shortcut: [magenta]{focus.shortcut}[/magenta].' if focus.shortcut else ''}[/dim]"
            ),
            title="Focus",
            border_style="magenta",
        )

        self.console.print(Columns([actions_table, detail], equal=True, expand=True))
        self.console.print(self._build_shortcuts_panel())
        if self.show_help:
            self.console.print(self._build_help_panel())

    def _build_market_status_panel(self) -> Panel:
        """Build a live market status panel for the home screen."""
        state = self.context.market_schedule.get_market_state()
        next_open = self.context.market_schedule.get_next_open()
        time_to_open = self.context.market_schedule.get_time_to_next_open()
        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = [f"[bold]State:[/bold] [cyan]{state}[/cyan]", f"[bold]Now:[/bold] {now_text}"]
        if next_open:
            lines.append(f"[bold]Next open:[/bold] {next_open.strftime('%Y-%m-%d %H:%M %Z')}")
        if time_to_open:
            days = time_to_open.days
            hours, remainder = divmod(time_to_open.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            time_bits = []
            if days:
                time_bits.append(f"{days}d")
            time_bits.append(f"{hours}h")
            time_bits.append(f"{minutes}m")
            lines.append(f"[bold]Time to open:[/bold] {' '.join(time_bits)}")

        return Panel.fit("\n".join(lines), title="Live Market", border_style="green")

    def _build_account_panel(self, account: str) -> Panel:
        """Build the account summary panel for the home screen."""
        lines = [f"[bold]Account:[/bold] {account}"]
        if self.last_health_report:
            report = self.last_health_report
            lines.extend(
                [
                    f"[bold]NLV:[/bold] ${report['nlv']:,.2f}",
                    f"[bold]BP Usage:[/bold] {report['bp_usage_pct']:.2f}% [{report['bp_usage_status']}]",
                    f"[bold]Theta:[/bold] {report['portfolio_theta']:.2f}",
                ]
            )
        else:
            lines.append("[dim]Run health check to populate account metrics.[/dim]")

        return Panel.fit("\n".join(lines), title="Account Snapshot", border_style="blue")

    def _build_shortcuts_panel(self) -> Panel:
        """Build a compact shortcut bar."""
        bar = Text()
        bar.append("F1 Help", style="bold cyan")
        bar.append("  |  ")
        bar.append("F2 Refresh", style="bold cyan")
        bar.append("  |  ")
        bar.append("F3 Watchlist", style="bold cyan")
        bar.append("  |  ")
        bar.append("F4 Market", style="bold cyan")
        bar.append("  |  ")
        bar.append("F5 Health", style="bold cyan")
        bar.append("  |  ")
        bar.append("F10 Quit", style="bold cyan")
        return Panel(bar, border_style="dim", title="Shortcuts")

    def _build_help_panel(self) -> Panel:
        """Build an expanded help panel."""
        help_text = (
            "[bold]Navigation[/bold]\n"
            "Arrow keys or j/k move the selection.\n"
            "Enter runs the highlighted action.\n"
            "Typing 1-9, a, or q jumps straight to that action.\n\n"
            "[bold]Function keys[/bold]\n"
            "F1 toggles this help.\n"
            "F2 refreshes the home screen.\n"
            "F3 opens the watchlist workflow.\n"
            "F4 shows market status.\n"
            "F5 shows portfolio health.\n"
            "F10 quits the launcher."
        )
        return Panel(help_text, title="Help", border_style="yellow")

    async def _build_scanner(self, threshold: Optional[float] = None) -> ScannerAgent:
        """Create a scanner with the requested IVR threshold."""
        resolved_threshold = threshold if threshold is not None else self.default_threshold
        return ScannerAgent(self.session, threshold=resolved_threshold)

    async def _run_market_status(self) -> None:
        """Print the current market schedule status."""
        self.context.market_schedule.print_status()

    async def _run_health_check(self) -> None:
        """Print the portfolio health report."""
        report = await self.context.risk_manager.calculate_portfolio_risk()
        self.last_health_report = report
        self._print_health_report(report)

    async def _run_watchlist_scan(self) -> None:
        """Run the full watchlist workflow with risk checks and strategy screening."""
        watchlist = await self._pick_watchlist("Watchlist to scan")
        if not watchlist:
            return

        threshold_text = await self._prompt_text(
            "IVR threshold",
            default=str(self.default_threshold if self.default_threshold is not None else 25.0),
        )
        scanner = await self._build_scanner(float(threshold_text))

        report = await self.context.risk_manager.calculate_portfolio_risk()
        self.last_health_report = report
        self._print_health_report(report)

        if report["bp_usage_pct"] > 50.0:
            proceed = await self._prompt_confirm(
                "Buying power usage is above 50%. Continue anyway?",
                default=False,
            )
            if not proceed:
                return

        positions = await self.context.portfolio.get_positions()
        if positions:
            self.console.print("\n[bold]Checking existing positions...[/bold]")
            to_close = await self.context.strategy.manage_positions(positions)
            if to_close:
                self.console.print(f"[yellow]{len(to_close)} positions hit exit criteria:[/yellow]")
                for item in to_close:
                    self.console.print(f"  • {item['position'].symbol}: {item['reason']}")
            else:
                self.console.print("[green]All positions remain within parameters.[/green]")

        self.console.print(f"\n[bold]Scanning watchlist:[/bold] {watchlist}")
        symbols = await self._get_watchlist_symbols(watchlist)
        if not symbols:
            self.console.print(f"[red]No symbols found in {watchlist}[/red]")
            return

        results = await self._scan_watchlist_live(scanner, watchlist, symbols)
        targets = scanner.get_high_ivr_targets(results)
        self.console.print(scanner.generate_report(targets))

        if targets:
            self.console.print(f"[dim]Screening {len(targets)} high IVR targets...[/dim]")
            all_strategy_targets = []
            for target in targets:
                strategy_targets = await self.context.strategy.screen_strategies(
                    target.symbol,
                    target.iv_rank,
                )
                all_strategy_targets.extend(strategy_targets)

            if all_strategy_targets:
                self.console.print("")
                self.context.strategy.print_strategy_report(all_strategy_targets)
            else:
                self.console.print("[yellow]No valid strategies found for these targets.[/yellow]")

    async def _run_market_snapshot(self) -> None:
        """Print a quick market snapshot for a single symbol."""
        source = await self._prompt_choice(
            "Pick a symbol from",
            choices=["watchlist", "positions", "manual"],
            default="watchlist",
        )

        symbol: Optional[str]
        if source == "watchlist":
            watchlist = await self._pick_watchlist("Watchlist for snapshot")
            if not watchlist:
                return
            symbols = await self._get_watchlist_symbols(watchlist)
            if symbols:
                symbol = await self._pick_symbol(
                    f"Symbol from {watchlist}",
                    symbols,
                    source_label=f"Watchlist: {watchlist}",
                )
            else:
                self.console.print(f"[yellow]No symbols found in {watchlist}; enter one manually.[/yellow]")
                symbol = (await self._prompt_text("Underlying symbol")).strip().upper() or None
        elif source == "positions":
            symbols = await self._get_account_symbols()
            if symbols:
                symbol = await self._pick_symbol(
                    "Symbol from account positions",
                    symbols,
                    source_label="Account positions",
                )
            else:
                self.console.print("[yellow]No open positions found; enter a symbol manually.[/yellow]")
                symbol = (await self._prompt_text("Underlying symbol")).strip().upper() or None
        else:
            symbol = (await self._prompt_text("Underlying symbol")).strip().upper() or None

        if not symbol:
            return

        scanner = await self._build_scanner()
        self.console.print(f"[bold]Fetching market snapshot:[/bold] {symbol}")

        snapshot_data = await scanner.get_market_snapshot([symbol])
        scanner.print_snapshot(snapshot_data)

    async def _run_account_report(self) -> None:
        """Print the current account positions report."""
        discord = await self._prompt_confirm("Format for Discord?", default=False)
        self.console.print("[bold]Generating account report...[/bold]")
        await self.context.portfolio.print_positions_report(discord=discord)

    async def _run_history_report(self) -> None:
        """Print a performance history report."""
        period_choice = await self._prompt_choice(
            "History range",
            choices=["week", "month", "year", "calendar"],
            default="month",
        )
        month = None
        if period_choice == "calendar":
            month = await self._prompt_text("Month (YYYY-MM)")
            period_choice = None

        discord = await self._prompt_confirm("Format for Discord?", default=False)
        history = await AccountHistoryAgent(
            self.session,
            account_number=self.context.account_number,
        ).init()
        report = await history.build_performance_report(
            range_name=period_choice,
            month=month,
        )
        history.print_performance_report(report, discord=discord)

    async def _run_review_position(self) -> None:
        """Review a position and show roll scenarios."""
        symbol = (
            await self._prompt_text(
                "Underlying symbol to review (press Enter to pick from open positions)",
                default="",
            )
        ).strip().upper() or None

        if not symbol:
            symbols = await self._get_account_symbols()
            if symbols:
                symbol = await self._pick_symbol(
                    "Open position to review",
                    symbols,
                    source_label="Account positions",
                )
            else:
                self.console.print("[yellow]No open positions found; enter a symbol manually.[/yellow]")
                symbol = (await self._prompt_text("Underlying symbol")).strip().upper() or None

        if not symbol:
            return

        discord = await self._prompt_confirm("Format for Discord?", default=False)
        output = (await self._prompt_text("Output path for JSON export", default="")).strip() or None

        self.console.print(f"[bold]Reviewing positions for {symbol}...[/bold]")
        reviewer = await ReviewerAgent(
            self.session,
            account_number=self.context.account_number,
        ).init()
        results = await reviewer.review_positions(underlying_filter=symbol)

        if not results:
            self.console.print(f"[red]No positions found for {symbol}[/red]")
            return

        if output:
            reviewer.export_json(results, output)
        else:
            reviewer.print_review_report(results, discord=discord)

    async def _run_list_watchlists(self) -> None:
        """List the available watchlists."""
        watchlists = self._get_watchlist_catalog()
        self.console.print("\n[bold]Private Watchlists[/bold]")
        for item in watchlists:
            if item["scope"] == "Private":
                self.console.print(f"  • {item['name']}")

        self.console.print("\n[bold]Public Watchlists[/bold]")
        for item in watchlists:
            if item["scope"] == "Public":
                self.console.print(f"  • {item['name']}")

    async def _run_account_dashboard(self) -> None:
        """Launcher handler: invoke the unified account dashboard."""
        from utils.dashboard_ui import run_account_dashboard
        account_number = (
            self.context.account_number if self.context else self.account_number
        )
        await run_account_dashboard(self.session, account_number=account_number)

    async def _run_settings_editor(self) -> None:
        """Launcher handler: interactive editor for Phase A settings."""
        from rich.prompt import Confirm, Prompt
        from rich.table import Table
        from utils.settings import (
            NUMERIC_KEYS,
            OPTIONAL_NUMERIC_KEYS,
            settings as settings_obj,
        )

        console = self.console
        numeric_keys = sorted(NUMERIC_KEYS) + sorted(OPTIONAL_NUMERIC_KEYS)
        toggle_keys = sorted((settings_obj.get("alert_toggles") or {}).keys())

        pending: dict[str, Any] = {}

        try:
            console.print("[bold]Settings — numeric thresholds[/bold]")
            console.print("[dim]  Enter a number to change. For optional keys, type 'none' to clear.[/dim]")
            for key in numeric_keys:
                current = settings_obj.get(key)
                shown = "" if current is None else str(current)
                answer = Prompt.ask(
                    f"  {key}",
                    default=shown,
                    console=console,
                )
                if answer == shown:
                    continue
                if key in OPTIONAL_NUMERIC_KEYS and answer.strip().lower() in ("none", "null", ""):
                    pending[key] = None
                else:
                    pending[key] = answer

            console.print("\n[bold]Settings — alert toggles[/bold]")
            toggles = settings_obj.get("alert_toggles") or {}
            for cat in toggle_keys:
                current_bool = bool(toggles.get(cat, True))
                new_bool = Confirm.ask(
                    f"  Enable alerts for {cat}?",
                    default=current_bool,
                    console=console,
                )
                if new_bool != current_bool:
                    pending[f"alert_toggles.{cat}"] = new_bool
        except KeyboardInterrupt:
            console.print("\n[yellow]Cancelled — no changes written.[/yellow]")
            return

        if not pending:
            console.print("\n[dim]No changes.[/dim]")
            return

        preview = Table(title="Pending changes", show_header=True)
        preview.add_column("Key")
        preview.add_column("New value")
        for k, v in pending.items():
            preview.add_row(k, repr(v))
        console.print(preview)

        if not Confirm.ask("Save changes?", default=True, console=console):
            console.print("[yellow]Discarded.[/yellow]")
            return

        try:
            settings_obj.set_many(pending)
            console.print("[green]Settings saved to {}[/green]".format(settings_obj.config_path))
        except ValueError as e:
            console.print(f"[red]Invalid value: {e}[/red]")
        except OSError as e:
            console.print(f"[red]Could not write config: {e}[/red]")

    async def _run_event_timeline(self) -> None:
        """Launcher handler: render event timeline for the active account."""
        from utils.timeline_ui import run_timeline
        account_number = (
            self.context.account_number if self.context else self.account_number
        )
        if not account_number:
            self.console.print("[red]No active account.[/red]")
            return
        await run_timeline(
            session=self.session,
            account_number=account_number,
            days=30,
            symbol=None,
            console=self.console,
        )

    async def _run_dashboard(self) -> None:
        """Open the market quality dashboard."""
        from agents.dashboard import run_dashboard

        open_html = await self._prompt_confirm("Open in browser?", default=False)
        await run_dashboard(self.session, html=open_html)

    def _get_watchlist_catalog(self) -> list[dict[str, str]]:
        """Return a combined private/public watchlist catalog."""
        catalog: list[dict[str, str]] = []
        for watchlist in PrivateWatchlist.get(self.session):
            catalog.append({"name": watchlist.name, "scope": "Private"})
        for watchlist in PublicWatchlist.get(self.session):
            catalog.append({"name": watchlist.name, "scope": "Public"})
        return catalog

    async def _get_watchlist_symbols(self, watchlist_name: str) -> list[str]:
        """Fetch and cache symbols for a watchlist."""
        if watchlist_name in self._watchlist_symbol_cache:
            return self._watchlist_symbol_cache[watchlist_name]

        scanner = ScannerAgent(self.session, threshold=self.default_threshold or 25.0)
        symbols = await scanner.get_symbols_from_watchlist(watchlist_name, equity_only=False)
        self._watchlist_symbol_cache[watchlist_name] = symbols
        return symbols

    async def _get_account_symbols(self) -> list[str]:
        """Return the current account's underlying symbols for picker use."""
        positions = await self.context.portfolio.get_positions()
        symbols: list[str] = []
        seen: set[str] = set()

        for position in positions:
            symbol = (
                getattr(position, "underlying_symbol", None)
                or getattr(position, "symbol", None)
                or ""
            ).strip().upper()
            if symbol and symbol not in seen:
                seen.add(symbol)
                symbols.append(symbol)

        symbols.sort()
        return symbols

    def _watchlist_score(
        self,
        watchlist_name: str,
        scope: str,
        filter_text: str,
        symbols: Optional[Sequence[str]] = None,
    ) -> float:
        """Return a fuzzy match score for a watchlist row."""
        if not filter_text:
            return 1.0

        needle = filter_text.lower().strip()
        haystack = f"{watchlist_name} {scope}".lower()
        score = SequenceMatcher(None, needle, haystack).ratio()
        if needle in haystack:
            score = max(score, 2.0 + (len(needle) / max(len(haystack), 1)))

        if symbols:
            symbol_haystack = " ".join(symbols).lower()
            if needle in symbol_haystack:
                score = max(score, 1.5 + (len(needle) / max(len(symbol_haystack), 1)))
            score = max(score, SequenceMatcher(None, needle, symbol_haystack).ratio())

        return score

    def _symbol_score(
        self,
        symbol: str,
        filter_text: str,
        source_label: str = "",
    ) -> float:
        """Return a fuzzy match score for a symbol row."""
        if not filter_text:
            return 1.0

        needle = filter_text.lower().strip()
        haystack = f"{symbol} {source_label}".lower()
        score = SequenceMatcher(None, needle, haystack).ratio()
        if needle in haystack:
            score = max(score, 2.0 + (len(needle) / max(len(haystack), 1)))
        return score

    async def _pick_symbol(
        self,
        title: str,
        symbols: Sequence[str],
        source_label: str,
        default: Optional[str] = None,
    ) -> Optional[str]:
        """Search and pick a symbol using live filtering."""
        if not symbols:
            self.console.print("[red]No symbols available.[/red]")
            return None

        catalog = [{"symbol": symbol, "source": source_label} for symbol in symbols]
        filter_text = default or ""
        selected = 0

        while True:
            filtered = self._filter_symbols(catalog, filter_text)
            if filtered:
                selected = min(selected, len(filtered) - 1)
            else:
                selected = 0

            selected_item = filtered[selected] if filtered else None

            self.console.clear()
            self.console.print(
                Panel.fit(
                    f"[bold]{title}[/bold]\nType to filter, arrows to move, Enter to select, Esc to cancel.",
                    border_style="cyan",
                )
            )
            self.console.print(
                Panel(
                    Text.assemble(("Filter: ", "bold"), (filter_text or "(all)", "cyan")),
                    border_style="magenta",
                )
            )

            table = Table(box=box.ROUNDED, expand=True, show_header=True)
            table.add_column(" ", width=2)
            table.add_column("Symbol", style="bold")
            table.add_column("Source", style="dim")
            table.add_column("Score", style="magenta", width=8)

            if not filtered:
                table.add_row(" ", "[dim]No matches[/dim]", "", "")
            else:
                for idx, item in enumerate(filtered):
                    row_style = "bold black on cyan" if idx == selected else ""
                    score = self._symbol_score(item["symbol"], filter_text, item["source"])
                    table.add_row(
                        ">" if idx == selected else " ",
                        item["symbol"],
                        item["source"],
                        f"{score:.2f}",
                        style=row_style,
                    )

            preview = self._build_symbol_preview_panel(selected_item, filter_text, len(filtered))
            self.console.print(Columns([table, preview], equal=True, expand=True))
            self.console.print(self._build_shortcuts_panel())

            key = await self._read_key(timeout=None)
            if key == "ESC":
                return None
            if key == "ENTER":
                if filtered:
                    return filtered[selected]["symbol"]
                if filter_text.strip():
                    return filter_text.strip().upper()
                continue
            if key in {"UP", "k"} and filtered:
                selected = (selected - 1) % len(filtered)
                continue
            if key in {"DOWN", "j"} and filtered:
                selected = (selected + 1) % len(filtered)
                continue
            if key == "BACKSPACE":
                filter_text = filter_text[:-1]
                continue
            if key == "SPACE":
                filter_text += " "
                continue
            if len(key) == 1 and key.isprintable():
                filter_text += key
                continue

    def _filter_symbols(
        self,
        catalog: Sequence[dict[str, str]],
        filter_text: str,
    ) -> list[dict[str, str]]:
        """Filter symbols by fuzzy match."""
        if not filter_text:
            return list(catalog)

        needle = filter_text.lower().strip()
        scored = []
        for item in catalog:
            score = self._symbol_score(item["symbol"], filter_text, item["source"])
            if needle in item["symbol"].lower() or needle in item["source"].lower() or score > 0.25:
                scored.append((score, item))

        scored.sort(key=lambda pair: (-pair[0], pair[1]["symbol"].lower(), pair[1]["source"]))
        return [item for _, item in scored]

    def _build_symbol_preview_panel(
        self,
        symbol: Optional[dict[str, str]],
        filter_text: str,
        matches: int,
    ) -> Panel:
        """Build a preview panel for the currently selected symbol."""
        if not symbol:
            return Panel(
                "[dim]Type to filter symbols, or press Enter to accept the typed symbol.[/dim]",
                title="Preview",
                border_style="dim",
            )

        preview_lines = [
            f"[bold]Symbol:[/bold] {symbol['symbol']}",
            f"[bold]Source:[/bold] {symbol['source']}",
            f"[bold]Matches:[/bold] {matches}",
        ]

        if filter_text:
            preview_lines.append(f"[bold]Filter:[/bold] {filter_text}")

        return Panel("\n".join(preview_lines), title="Preview", border_style="blue")

    async def _pick_watchlist(self, title: str, default: Optional[str] = None) -> Optional[str]:
        """Search and pick a watchlist using live filtering."""
        catalog = self._get_watchlist_catalog()
        if not catalog:
            self.console.print("[red]No watchlists available.[/red]")
            return None

        filter_text = default or ""
        selected = 0

        while True:
            filtered = await self._filter_watchlists(catalog, filter_text)
            if filtered:
                selected = min(selected, len(filtered) - 1)
            else:
                selected = 0

            selected_item = filtered[selected] if filtered else None
            selected_symbols = await self._get_watchlist_symbols(selected_item["name"]) if selected_item else []

            self.console.clear()
            self.console.print(
                Panel.fit(
                    f"[bold]{title}[/bold]\nType to filter, arrows to move, Enter to select, Esc to cancel.",
                    border_style="cyan",
                )
            )

            self.console.print(
                Panel(
                    Text.assemble(("Filter: ", "bold"), (filter_text or "(all)", "cyan")),
                    border_style="magenta",
                )
            )

            table = Table(box=box.ROUNDED, expand=True, show_header=True)
            table.add_column(" ", width=2)
            table.add_column("Watchlist", style="bold")
            table.add_column("Scope", style="dim", width=10)
            table.add_column("Score", style="magenta", width=8)

            if not filtered:
                table.add_row(" ", "[dim]No matches[/dim]", "", "")
            else:
                for idx, item in enumerate(filtered):
                    row_style = "bold black on cyan" if idx == selected else ""
                    score = self._watchlist_score(item["name"], item["scope"], filter_text)
                    table.add_row(
                        ">" if idx == selected else " ",
                        item["name"],
                        item["scope"],
                        f"{score:.2f}",
                        style=row_style,
                    )

            preview = self._build_watchlist_preview_panel(selected_item, selected_symbols)
            self.console.print(Columns([table, preview], equal=True, expand=True))
            self.console.print(self._build_shortcuts_panel())

            key = await self._read_key(timeout=None)
            if key == "ESC":
                return None
            if key == "ENTER":
                if filtered:
                    return filtered[selected]["name"]
                continue
            if key in {"UP", "k"} and filtered:
                selected = (selected - 1) % len(filtered)
                continue
            if key in {"DOWN", "j"} and filtered:
                selected = (selected + 1) % len(filtered)
                continue
            if key == "BACKSPACE":
                filter_text = filter_text[:-1]
                continue
            if key == "SPACE":
                filter_text += " "
                continue
            if len(key) == 1 and key.isprintable():
                filter_text += key
                continue

    async def _filter_watchlists(
        self,
        catalog: list[dict[str, str]],
        filter_text: str,
    ) -> list[dict[str, str]]:
        """Filter watchlists by fuzzy match across names and symbols."""
        if not filter_text:
            return catalog

        needle = filter_text.lower().strip()
        symbol_lists = await asyncio.gather(
            *(self._get_watchlist_symbols(item["name"]) for item in catalog)
        )
        scored: list[tuple[float, dict[str, str]]] = []
        for item, symbols in zip(catalog, symbol_lists):
            score = self._watchlist_score(item["name"], item["scope"], filter_text, symbols)
            if (
                needle in item["name"].lower()
                or needle in item["scope"].lower()
                or any(needle in symbol.lower() for symbol in symbols)
                or score > 0.25
            ):
                scored.append((score, item))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["name"].lower(), pair[1]["scope"]))
        return [item for _, item in scored]

    def _build_watchlist_preview_panel(
        self,
        watchlist: Optional[dict[str, str]],
        symbols: list[str],
    ) -> Panel:
        """Build a preview panel for the currently selected watchlist."""
        if not watchlist:
            return Panel(
                "[dim]Select a watchlist to preview its symbols.[/dim]",
                title="Preview",
                border_style="dim",
            )

        preview_lines = [
            f"[bold]Name:[/bold] {watchlist['name']}",
            f"[bold]Scope:[/bold] {watchlist['scope']}",
            f"[bold]Symbols:[/bold] {len(symbols)}",
        ]

        if symbols:
            preview_lines.append("")
            preview_lines.append("[bold]First symbols:[/bold]")
            for symbol in symbols[:8]:
                preview_lines.append(f"• {symbol}")
            if len(symbols) > 8:
                preview_lines.append(f"... and {len(symbols) - 8} more")
        else:
            preview_lines.append("")
            preview_lines.append("[dim]No symbols found in this watchlist.[/dim]")

        return Panel("\n".join(preview_lines), title="Preview", border_style="blue")

    async def _scan_watchlist_live(
        self,
        scanner: ScannerAgent,
        watchlist: str,
        symbols: list[str],
    ) -> dict[str, Any]:
        """Scan a watchlist in batches and repaint the live results pane."""
        batch_size = 50
        results: dict[str, Any] = {}
        batches = [symbols[i:i + batch_size] for i in range(0, len(symbols), batch_size)]
        recent_batch: list[str] = []

        with Live(
            self._render_scan_layout(
                watchlist=watchlist,
                symbols=symbols,
                results=results,
                batch_index=0,
                batch_total=max(len(batches), 1),
                recent_batch=recent_batch,
            ),
            console=self.console,
            refresh_per_second=8,
            screen=False,
        ) as live:
            for index, batch in enumerate(batches, start=1):
                recent_batch = batch
                live.update(
                    self._render_scan_layout(
                        watchlist=watchlist,
                        symbols=symbols,
                        results=results,
                        batch_index=index - 1,
                        batch_total=len(batches),
                        recent_batch=recent_batch,
                    )
                )

                try:
                    metrics_list = get_market_metrics(self.session, batch)
                    metrics = {m.symbol: m for m in metrics_list}
                    prices_list = get_market_data_by_type(self.session, equities=batch)
                    prices = {d.symbol: d for d in prices_list}

                    for symbol in batch:
                        metric = metrics.get(symbol)
                        data = prices.get(symbol)

                        ivr = IVRData(symbol=symbol)
                        if data:
                            ivr.current_price = data.mark or data.last
                            ivr.volume = data.volume

                        if metric:
                            ivr.iv_rank = (
                                float(metric.implied_volatility_index_rank) * 100
                                if metric.implied_volatility_index_rank
                                else None
                            )
                            ivr.iv_percentile = (
                                float(metric.implied_volatility_percentile) * 100
                                if metric.implied_volatility_percentile
                                else None
                            )
                            ivr.current_iv = (
                                float(metric.implied_volatility_index)
                                if metric.implied_volatility_index
                                else None
                            )
                            ivr.beta = float(metric.beta) if metric.beta else None
                            ivr.liquidity_rank = float(metric.liquidity_rank) if metric.liquidity_rank else None
                            if metric.earnings and metric.earnings.expected_report_date:
                                ivr.next_earnings_date = metric.earnings.expected_report_date.strftime("%m/%d")
                            ivr.has_options = True

                        results[symbol] = ivr
                except Exception as exc:
                    self.console.print(f"[red]Error scanning batch {index}/{len(batches)}:[/red] {exc}")

                live.update(
                    self._render_scan_layout(
                        watchlist=watchlist,
                        symbols=symbols,
                        results=results,
                        batch_index=index,
                        batch_total=len(batches),
                        recent_batch=recent_batch,
                    )
                )

        return results

    def _render_scan_layout(
        self,
        watchlist: str,
        symbols: list[str],
        results: dict[str, Any],
        batch_index: int,
        batch_total: int,
        recent_batch: list[str],
    ) -> Layout:
        """Render the split-pane live scan layout."""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=5),
            Layout(name="body", ratio=1),
            Layout(name="footer", size=3),
        )
        layout["body"].split_row(
            Layout(name="left", ratio=1),
            Layout(name="right", ratio=1),
        )

        targets = [item for item in results.values() if item.iv_rank is not None and item.iv_rank >= (self.default_threshold or 25.0)]
        targets.sort(key=lambda item: item.iv_rank or 0, reverse=True)

        layout["header"].update(
            Panel.fit(
                f"[bold]Scanning[/bold] {watchlist}\n"
                f"Symbols: {len(symbols)}  |  Batches: {batch_index}/{batch_total}",
                border_style="cyan",
            )
        )
        layout["left"].update(self._build_scan_status_panel(batch_index, batch_total, recent_batch, results))
        layout["right"].update(self._build_scan_targets_panel(targets, results))
        layout["footer"].update(
            Panel(
                "F2 refresh home  |  F1 help  |  Esc cancel picker  |  Scan updates in real time",
                border_style="dim",
            )
        )
        return layout

    def _build_scan_status_panel(
        self,
        batch_index: int,
        batch_total: int,
        recent_batch: list[str],
        results: dict[str, Any],
    ) -> Panel:
        """Build the live status panel for a scan."""
        scanned = len(results)
        remaining = max(batch_total - batch_index, 0)
        body = [
            f"[bold]Completed batches:[/bold] {batch_index}/{batch_total}",
            f"[bold]Symbols scanned:[/bold] {scanned}",
            f"[bold]Remaining batches:[/bold] {remaining}",
        ]
        if recent_batch:
            body.append("")
            body.append("[bold]Recent batch:[/bold]")
            for symbol in recent_batch[:12]:
                body.append(f"• {symbol}")

        return Panel("\n".join(body), title="Live Status", border_style="green")

    def _build_scan_targets_panel(self, targets: list[Any], results: dict[str, Any]) -> Panel:
        """Build the live targets panel for a scan."""
        table = Table(box=box.SIMPLE_HEAVY, expand=True)
        table.add_column("Symbol", style="bold")
        table.add_column("IVR", justify="right")
        table.add_column("IV", justify="right")
        table.add_column("Price", justify="right")
        table.add_column("Liq", justify="center")

        if not targets:
            table.add_row("[dim]Waiting for targets...[/dim]", "", "", "", "")
        else:
            for item in targets[:12]:
                ivr = f"{item.iv_rank:.1f}%" if item.iv_rank is not None else "N/A"
                iv = f"{item.current_iv * 100:.0f}%" if item.current_iv else "N/A"
                price = f"${item.current_price:,.2f}" if item.current_price else "N/A"
                liq = ("★" * min(5, max(1, int(item.liquidity_rank)))).ljust(5) if item.liquidity_rank else "N/A"
                table.add_row(item.symbol, ivr, iv, price, liq)

        footer = f"[dim]Targets above threshold: {len(targets)} | Scanned: {len(results)}[/dim]"
        return Panel(table, title="Live Targets", border_style="magenta", subtitle=footer)

    async def _switch_account(self) -> None:
        """Prompt for a different account and rebuild account-scoped agents."""
        self.account_number = await self._select_account()
        portfolio = PortfolioAgent(self.session, account_number=self.account_number)
        await portfolio.init()
        self.context = LauncherContext(
            account_number=self.account_number,
            portfolio=portfolio,
            strategy=StrategyAgent(self.session),
            risk_manager=RiskManager(self.session, account_number=self.account_number),
            market_schedule=MarketSchedule(self.session),
        )
        self.last_health_report = None

    async def _quit(self) -> None:
        """No-op quit handler."""
        return None

    def _print_health_report(self, report: dict) -> None:
        """Render a concise health summary in the terminal."""
        self.console.print(
            Panel.fit(
                (
                    f"[bold]NLV:[/bold] ${report['nlv']:,.2f}\n"
                    f"[bold]BP Usage:[/bold] {report['bp_usage_pct']:.2f}% [{report['bp_usage_status']}]\n"
                    f"[bold]Cash:[/bold] ${report['cash_balance']:,.2f}\n"
                    f"[bold]Day Trade BP:[/bold] ${report['day_trading_buying_power']:,.2f}\n"
                    f"[bold]Portfolio Delta:[/bold] {report['portfolio_delta']:.2f}\n"
                    f"[bold]Theta:[/bold] {report['portfolio_theta']:.2f} [{report['theta_status']}]"
                ),
                title="Portfolio Health",
                border_style="green",
            )
        )

        if report["trade_size_warnings"]:
            self.console.print("[bold yellow]Trade Size Warnings[/bold yellow]")
            for warn in report["trade_size_warnings"]:
                self.console.print(f"  • {warn}")
        else:
            self.console.print("[green]Trade Sizes: OK[/green]")

        if report.get("session_warnings"):
            self.console.print("[bold yellow]Market Session Warnings[/bold yellow]")
            for warn in report["session_warnings"]:
                self.console.print(f"  • {warn}")

    async def _prompt_text(self, prompt: str, default: str = "") -> str:
        """Ask for free-form text using a normal terminal prompt."""
        if default:
            return await asyncio.to_thread(
                lambda: self.console.input(f"{prompt} [dim]({default})[/dim]: ") or default
            )
        return await asyncio.to_thread(lambda: self.console.input(f"{prompt}: "))

    async def _prompt_confirm(self, prompt: str, default: bool = False) -> bool:
        """Ask for a yes/no answer."""
        while True:
            answer = await self._prompt_text(prompt, "y" if default else "n")
            normalized = answer.strip().lower()
            if not normalized:
                return default
            if normalized in {"y", "yes"}:
                return True
            if normalized in {"n", "no"}:
                return False

    async def _prompt_choice(
        self,
        prompt: str,
        choices: Sequence[str],
        default: str,
    ) -> str:
        """Ask the user to choose one of the provided options."""
        choice_text = "/".join(choices)
        while True:
            answer = await self._prompt_text(f"{prompt} [{choice_text}]", default)
            normalized = answer.strip().lower() or default
            if normalized in choices:
                return normalized

    async def _pause(self) -> None:
        """Wait for the user before returning to the launcher."""
        await asyncio.to_thread(
            lambda: self.console.input("\n[dim]Press Enter to return to the launcher...[/dim]")
        )

    async def _read_key(self, timeout: Optional[float] = None) -> Optional[str]:
        """Read a single key press from the terminal."""
        return await asyncio.to_thread(self._read_key_sync, timeout)

    def _read_key_sync(self, timeout: Optional[float] = None) -> Optional[str]:
        """Read and normalize a single key press."""
        if not sys.stdin.isatty():
            value = input().strip().lower()
            return value or "ENTER"

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            if timeout is not None and not self._has_input(fd, timeout):
                return None

            raw = os.read(fd, 1)
            if not raw:
                return "ENTER"
            if raw == b"\x03":
                raise KeyboardInterrupt
            if raw in {b"\r", b"\n"}:
                return "ENTER"
            if raw == b" ":
                return "SPACE"
            if raw in {b"\x7f", b"\b"}:
                return "BACKSPACE"
            if raw != b"\x1b":
                return raw.decode(errors="ignore").lower()

            seq = raw
            if self._has_input(fd, 0.05):
                seq += os.read(fd, 1)
                if self._has_input(fd, 0.05):
                    seq += os.read(fd, 1)
                    if self._has_input(fd, 0.05):
                        seq += os.read(fd, 1)

            mapping = {
                b"\x1b[A": "UP",
                b"\x1b[B": "DOWN",
                b"\x1b[C": "RIGHT",
                b"\x1b[D": "LEFT",
                b"\x1bOP": "F1",
                b"\x1bOQ": "F2",
                b"\x1bOR": "F3",
                b"\x1bOS": "F4",
                b"\x1b[15~": "F5",
                b"\x1b[17~": "F6",
                b"\x1b[18~": "F7",
                b"\x1b[19~": "F8",
                b"\x1b[20~": "F9",
                b"\x1b[21~": "F10",
            }
            return mapping.get(seq, "ESC")
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    def _has_input(self, fd: int, timeout: float) -> bool:
        """Return True when the terminal has more bytes ready to read."""
        readable, _, _ = select.select([fd], [], [], timeout)
        return bool(readable)
