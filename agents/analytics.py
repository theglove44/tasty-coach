"""Analytics agent — performance metrics and equity curve from local trade history."""

import logging
from datetime import date, timedelta
from typing import Optional, List

from rich.console import Console
from rich.table import Table

from tastytrade import Session, Account

from utils.db import TradeDB


class AnalyticsAgent:
    """Computes and displays trading performance metrics from local DB."""

    def __init__(self, session: Session, account_number: Optional[str] = None):
        self.session = session
        self.logger = logging.getLogger(__name__)
        self.account_number = account_number
        self.account: Optional[Account] = None

    async def init(self) -> "AnalyticsAgent":
        self.account = await self._get_account()
        return self

    async def _get_account(self) -> Optional[Account]:
        try:
            accounts = Account.get(self.session)
            if not accounts:
                return None
            if self.account_number:
                for acct in accounts:
                    if getattr(acct, "account_number", None) == self.account_number:
                        return acct
                available = ", ".join(
                    [getattr(a, "account_number", "?") for a in accounts]
                )
                raise ValueError(
                    f"Account {self.account_number} not found. Available: {available}"
                )
            return accounts[0]
        except Exception as e:
            self.logger.error(f"Error fetching accounts: {e}")
            return None

    def _resolve_account_number(self) -> str:
        return self.account_number or (
            self.account.account_number if self.account else ""
        )

    def _parse_period(self, period: str) -> Optional[date]:
        """Convert period string to start date. Returns None for 'all'."""
        mapping = {
            "1m": 30,
            "3m": 90,
            "6m": 180,
            "1y": 365,
            "2y": 730,
        }
        if period == "all":
            return None
        days = mapping.get(period, 90)
        return date.today() - timedelta(days=days)

    # --- Performance summary ---

    def get_performance_summary(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        """Compute overall performance metrics from closed trade groups."""
        db = TradeDB()
        try:
            acct = self._resolve_account_number()
            sql = """
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN realized_pl > 0 THEN 1 ELSE 0 END) as winners,
                    SUM(CASE WHEN realized_pl <= 0 THEN 1 ELSE 0 END) as losers,
                    AVG(realized_pl) as avg_pl,
                    SUM(realized_pl) as total_pl,
                    SUM(total_fees) as total_fees,
                    AVG(holding_days) as avg_holding_days,
                    MAX(realized_pl) as largest_win,
                    MIN(realized_pl) as largest_loss,
                    SUM(CASE WHEN realized_pl > 0 THEN realized_pl ELSE 0 END) as gross_wins,
                    SUM(CASE WHEN realized_pl < 0 THEN ABS(realized_pl) ELSE 0 END) as gross_losses,
                    AVG(CASE WHEN realized_pl > 0 THEN realized_pl END) as avg_win,
                    AVG(CASE WHEN realized_pl <= 0 THEN realized_pl END) as avg_loss
                FROM trade_groups
                WHERE account_number = ? AND status IN ('closed', 'expired', 'assigned')
            """
            params = [acct]

            if start_date:
                sql += " AND opened_at >= ?"
                params.append(start_date)
            if end_date:
                sql += " AND closed_at <= ?"
                params.append(end_date)

            row = db.conn.execute(sql, params).fetchone()
            if not row or row["total_trades"] == 0:
                return {}

            total = row["total_trades"]
            winners = row["winners"] or 0
            losers = row["losers"] or 0
            win_rate = (winners / total * 100) if total > 0 else 0
            gross_wins = row["gross_wins"] or 0
            gross_losses = row["gross_losses"] or 0
            profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else float("inf")
            avg_win = row["avg_win"] or 0
            avg_loss = row["avg_loss"] or 0
            expectancy = (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss)

            return {
                "total_trades": total,
                "winners": winners,
                "losers": losers,
                "win_rate": win_rate,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "avg_pl": row["avg_pl"] or 0,
                "total_pl": row["total_pl"] or 0,
                "total_fees": row["total_fees"] or 0,
                "profit_factor": profit_factor,
                "avg_holding_days": row["avg_holding_days"] or 0,
                "largest_win": row["largest_win"] or 0,
                "largest_loss": row["largest_loss"] or 0,
                "expectancy": expectancy,
            }
        finally:
            db.close()

    # --- Strategy breakdown ---

    def get_strategy_performance(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[dict]:
        """P/L broken down by strategy type."""
        db = TradeDB()
        try:
            acct = self._resolve_account_number()
            sql = """
                SELECT
                    COALESCE(strategy_type, 'Unknown') as strategy_type,
                    COUNT(*) as trades,
                    SUM(CASE WHEN realized_pl > 0 THEN 1 ELSE 0 END) as winners,
                    AVG(realized_pl) as avg_pl,
                    SUM(realized_pl) as total_pl,
                    SUM(total_fees) as total_fees,
                    AVG(holding_days) as avg_days
                FROM trade_groups
                WHERE account_number = ? AND status IN ('closed', 'expired', 'assigned')
            """
            params = [acct]
            if start_date:
                sql += " AND opened_at >= ?"
                params.append(start_date)
            if end_date:
                sql += " AND closed_at <= ?"
                params.append(end_date)

            sql += " GROUP BY strategy_type ORDER BY total_pl DESC"

            rows = db.conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            db.close()

    # --- Roll chain P/L ---

    def get_roll_chain_pl(self, group_id: int) -> dict:
        """Walk parent_group_id chain to compute total P/L across all rolls."""
        db = TradeDB()
        try:
            chain = db.get_roll_chain(group_id)
            if not chain:
                return {}

            total_pl = sum(g["realized_pl"] or 0 for g in chain)
            total_fees = sum(g["total_fees"] or 0 for g in chain)
            total_collected = sum(g["total_premium_collected"] or 0 for g in chain)
            total_paid = sum(g["total_premium_paid"] or 0 for g in chain)

            first = chain[0]
            last = chain[-1]
            total_days = None
            if first["opened_at"] and last.get("closed_at"):
                from datetime import datetime
                try:
                    opened = datetime.fromisoformat(first["opened_at"])
                    closed = datetime.fromisoformat(last["closed_at"])
                    total_days = (closed - opened).days
                except (ValueError, TypeError):
                    pass

            return {
                "chain_length": len(chain),
                "group_ids": [g["id"] for g in chain],
                "underlying": first["underlying_symbol"],
                "total_pl": total_pl,
                "total_fees": total_fees,
                "total_collected": total_collected,
                "total_paid": total_paid,
                "total_days": total_days,
                "first_opened": first["opened_at"],
                "last_closed": last.get("closed_at"),
            }
        finally:
            db.close()

    # --- Time-based P/L ---

    def get_monthly_pl(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> list[dict]:
        return self._get_period_pl("month", start_date, end_date)

    def get_weekly_pl(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> list[dict]:
        return self._get_period_pl("week", start_date, end_date)

    def get_daily_pl(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> list[dict]:
        return self._get_period_pl("day", start_date, end_date)

    def _get_period_pl(
        self, period: str, start_date: Optional[str], end_date: Optional[str]
    ) -> list[dict]:
        db = TradeDB()
        try:
            acct = self._resolve_account_number()

            if period == "month":
                fmt = "%Y-%m"
            elif period == "week":
                fmt = "%Y-W%W"
            else:
                fmt = "%Y-%m-%d"

            sql = f"""
                SELECT
                    strftime('{fmt}', closed_at) as period,
                    COUNT(*) as trades,
                    SUM(realized_pl) as pl,
                    SUM(total_fees) as fees
                FROM trade_groups
                WHERE account_number = ? AND status IN ('closed', 'expired', 'assigned')
                  AND closed_at IS NOT NULL
            """
            params = [acct]
            if start_date:
                sql += " AND closed_at >= ?"
                params.append(start_date)
            if end_date:
                sql += " AND closed_at <= ?"
                params.append(end_date)

            sql += " GROUP BY period ORDER BY period"

            rows = db.conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            db.close()

    # --- Equity curve ---

    async def get_equity_curve(self, time_back: str = "1y") -> list[dict]:
        """Fetch NLV history from API."""
        if not self.account:
            return []
        try:
            history = self.account.get_net_liquidating_value_history(
                self.session, time_back=time_back
            )
            results = []
            for point in history:
                results.append({
                    "time": point.time.isoformat() if hasattr(point, "time") and point.time else str(point.time),
                    "open": float(point.open) if hasattr(point, "open") else None,
                    "high": float(point.high) if hasattr(point, "high") else None,
                    "low": float(point.low) if hasattr(point, "low") else None,
                    "close": float(point.close) if hasattr(point, "close") else None,
                })
            return results
        except Exception as e:
            self.logger.error(f"Error fetching equity curve: {e}")
            return []

    # --- Display methods ---

    def print_performance(self, summary: dict, discord: bool = False) -> None:
        if not summary:
            print("No closed trades found. Run --sync first.")
            return

        console = Console(width=120)
        table = Table(title="Performance Summary", show_lines=False)
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")

        pl = summary["total_pl"]
        pl_color = "green" if pl >= 0 else "red"

        rows = [
            ("Total Trades", str(summary["total_trades"])),
            ("Winners / Losers", f"{summary['winners']} / {summary['losers']}"),
            ("Win Rate", f"{summary['win_rate']:.1f}%"),
            ("Avg Win", f"[green]${summary['avg_win']:,.2f}[/green]"),
            ("Avg Loss", f"[red]${summary['avg_loss']:,.2f}[/red]"),
            ("Avg P/L", f"${summary['avg_pl']:,.2f}"),
            ("Total P/L", f"[{pl_color}]${pl:,.2f}[/{pl_color}]"),
            ("Total Fees", f"${summary['total_fees']:,.2f}"),
            ("Profit Factor", f"{summary['profit_factor']:.2f}" if summary["profit_factor"] != float("inf") else "N/A"),
            ("Expectancy", f"${summary['expectancy']:,.2f}"),
            ("Avg Holding Days", f"{summary['avg_holding_days']:.1f}"),
            ("Largest Win", f"[green]${summary['largest_win']:,.2f}[/green]"),
            ("Largest Loss", f"[red]${summary['largest_loss']:,.2f}[/red]"),
        ]
        for label, value in rows:
            table.add_row(label, value)

        console.print(table)

    def print_strategy_breakdown(
        self, strategies: list[dict], discord: bool = False
    ) -> None:
        if not strategies:
            print("No strategy data found.")
            return

        console = Console(width=160)
        table = Table(title="Performance by Strategy", show_lines=False)
        table.add_column("Strategy", style="bold")
        table.add_column("Trades", justify="right")
        table.add_column("Win Rate", justify="right")
        table.add_column("Avg P/L", justify="right")
        table.add_column("Total P/L", justify="right")
        table.add_column("Fees", justify="right", style="dim")
        table.add_column("Avg Days", justify="right")

        for s in strategies:
            trades = s["trades"]
            winners = s["winners"] or 0
            wr = (winners / trades * 100) if trades > 0 else 0
            pl = s["total_pl"] or 0
            pl_color = "green" if pl >= 0 else "red"

            table.add_row(
                s["strategy_type"],
                str(trades),
                f"{wr:.0f}%",
                f"${(s['avg_pl'] or 0):,.2f}",
                f"[{pl_color}]${pl:,.2f}[/{pl_color}]",
                f"${(s['total_fees'] or 0):,.2f}",
                f"{(s['avg_days'] or 0):.0f}",
            )

        console.print(table)

    def print_pl_summary(
        self, periods: list[dict], period_type: str, discord: bool = False
    ) -> None:
        if not periods:
            print(f"No {period_type} P/L data found.")
            return

        console = Console(width=120)
        table = Table(title=f"P/L by {period_type.title()}", show_lines=False)
        table.add_column("Period", style="cyan")
        table.add_column("Trades", justify="right")
        table.add_column("P/L", justify="right")
        table.add_column("Fees", justify="right", style="dim")

        cumulative = 0.0
        for p in periods:
            pl = p["pl"] or 0
            cumulative += pl
            color = "green" if pl >= 0 else "red"

            table.add_row(
                p["period"],
                str(p["trades"]),
                f"[{color}]${pl:,.2f}[/{color}]",
                f"${(p['fees'] or 0):,.2f}",
            )

        console.print(table)

        cum_color = "green" if cumulative >= 0 else "red"
        console.print(f"\n  Cumulative P/L: [{cum_color}]${cumulative:,.2f}[/{cum_color}]")

    def print_equity_curve(
        self, data: list[dict], discord: bool = False
    ) -> None:
        if not data:
            print("No equity curve data found.")
            return

        console = Console(width=140)
        table = Table(title="Equity Curve (NLV History)", show_lines=False)
        table.add_column("Date", style="cyan", no_wrap=True)
        table.add_column("Open", justify="right")
        table.add_column("High", justify="right", style="green")
        table.add_column("Low", justify="right", style="red")
        table.add_column("Close", justify="right", style="bold")
        table.add_column("Change", justify="right")

        prev_close = None
        for point in data:
            close = point["close"]
            change_str = ""
            if prev_close and close:
                change = close - prev_close
                pct = (change / prev_close) * 100
                color = "green" if change >= 0 else "red"
                change_str = f"[{color}]{change:+,.0f} ({pct:+.1f}%)[/{color}]"
            prev_close = close

            time_str = point["time"][:10] if point["time"] else ""

            table.add_row(
                time_str,
                f"${point['open']:,.0f}" if point["open"] else "",
                f"${point['high']:,.0f}" if point["high"] else "",
                f"${point['low']:,.0f}" if point["low"] else "",
                f"${close:,.0f}" if close else "",
                change_str,
            )

        console.print(table)

        # Summary
        if len(data) >= 2 and data[0]["close"] and data[-1]["close"]:
            start_val = data[0]["close"]
            end_val = data[-1]["close"]
            total_change = end_val - start_val
            total_pct = (total_change / start_val) * 100
            color = "green" if total_change >= 0 else "red"
            console.print(
                f"\n  Period: ${start_val:,.0f} -> ${end_val:,.0f} | "
                f"Change: [{color}]{total_change:+,.0f} ({total_pct:+.1f}%)[/{color}]"
            )
