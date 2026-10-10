"""XK-08: self-contained, exact accounting projection; no server or script."""

import csv
import io
from datetime import date, datetime
from decimal import Decimal, localcontext
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Self

from pydantic import Field, model_validator

from backend.core.errors import DataIntegrityError
from backend.data.data_layer import _provider_money
from backend.domain.models import FrozenModel, PortfolioSnapshot, Price, UTCDateTime
from backend.ops.anchors import controlled_path
from backend.ops.trading_controls import ControlScope
from backend.pnl.models import PnLDay
from backend.tax.models import TaxFill

MAX_REPORT_BYTES = 2 * 1024 * 1024
REPORT_PREFIX = b"<!doctype html>\n<!-- Project V accounting report XK-08 -->\n"


class ReportSnapshot(FrozenModel):
    scope: ControlScope
    as_of: UTCDateTime
    days: tuple[PnLDay, ...] = Field(max_length=20000)
    spy: tuple[tuple[date, Price], ...] | None = Field(default=None, max_length=20001)
    portfolio: PortfolioSnapshot | None = None
    trades: tuple[TaxFill, ...] = Field(max_length=20)
    tax: tuple[str, ...] = Field(max_length=30)
    health: tuple[str, ...] = Field(max_length=30)
    edge: tuple[str, ...] = Field(max_length=30)

    @model_validator(mode="after")
    def bound(self) -> Self:
        sessions = tuple(row.observation.session for row in self.days)
        if sessions != tuple(sorted(set(sessions))) or any(
            row.observation.account_id != self.scope.account_id
            or row.observation.env != self.scope.environment
            or row.observation.as_of > self.as_of
            for row in self.days
        ):
            raise ValueError("XK-08: exact ordered accounting days must bind to this scope")
        if self.portfolio is not None and (
            self.portfolio.account_id != self.scope.account_id or self.portfolio.as_of > self.as_of
        ):
            raise ValueError("XK-08: portfolio account or time differs")
        if any(
            row.account_id != self.scope.account_id
            or row.env != self.scope.environment
            or row.ts > self.as_of
            for row in self.trades
        ):
            raise ValueError("XK-08: physical trades must bind to this scope")
        if self.spy is not None:
            dates = tuple(day for day, _ in self.spy)
            if dates != tuple(sorted(set(dates))) or any(day > self.as_of.date() for day in dates):
                raise ValueError("XK-08: benchmark is duplicated or future")
        if any(
            not isinstance(text, str) or not 1 <= len(text) <= 16384
            for group in (self.tax, self.health, self.edge)
            for text in group
        ):
            raise ValueError("XK-08: bounded report text required")
        return self

    @classmethod
    def recorded(cls, payload: dict[str, Any]) -> Self:
        try:
            raw = dict(payload)
            raw["as_of"] = datetime.fromisoformat(str(raw["as_of"]))
            raw["days"] = tuple(PnLDay.from_payload(row) for row in raw["days"])
            raw["trades"] = tuple(TaxFill.from_payload(row) for row in raw["trades"])
            if raw["spy"] is not None:
                raw["spy"] = tuple(
                    (date.fromisoformat(day), _provider_money(price)) for day, price in raw["spy"]
                )
            if raw["portfolio"] is not None:
                portfolio = dict(raw["portfolio"])
                portfolio["as_of"] = datetime.fromisoformat(portfolio["as_of"])
                portfolio["positions"] = {
                    symbol: {
                        **row,
                        "avg_cost": _provider_money(row["avg_cost"]),
                        "last_price": _provider_money(row["last_price"]),
                    }
                    for symbol, row in portfolio["positions"].items()
                }
                portfolio["open_orders"] = tuple(
                    {
                        **row,
                        "limit_price": _provider_money(row["limit_price"]),
                        "stop_price": None
                        if row["stop_price"] is None
                        else _provider_money(row["stop_price"]),
                    }
                    for row in portfolio["open_orders"]
                )
                portfolio["protective_stops"] = tuple(
                    {**row, "stop_price": _provider_money(row["stop_price"])}
                    for row in portfolio["protective_stops"]
                )
                raw["portfolio"] = PortfolioSnapshot.model_validate(portfolio)
            return cls.model_validate(raw)
        except Exception:
            raise DataIntegrityError("XK-08: stored report source is unverifiable") from None


def _safe(text: object) -> str:
    return escape(str(text))


def _curve(snapshot: ReportSnapshot) -> str:
    if not snapshot.days:
        return "<p>Equity curve UNVERIFIED: no completed accounting series.</p>"
    prices = {} if snapshot.spy is None else dict(snapshot.spy)
    baseline = tuple(day for day in prices if day < snapshot.days[0].observation.session)
    spy_start = prices[max(baseline)] if baseline else None
    benchmark = spy_start is not None and all(
        row.observation.session in prices for row in snapshot.days
    )
    with localcontext() as precision:
        precision.prec = 256
        growth = Decimal(1)
        returns = [Decimal(0)]
        spy_returns = [Decimal(0)]
        for row in snapshot.days:
            growth *= 1 + row.day_ret
            returns.append(growth - 1)
            if benchmark and spy_start is not None:
                spy_returns.append(prices[row.observation.session] / spy_start - 1)
        values = returns + (spy_returns if benchmark else [])
        low, high = min(values), max(values)
        spread = high - low or Decimal(1)

        def points(series: list[Decimal]) -> str:
            return " ".join(
                f"{Decimal(index) * 560 / (len(returns) - 1):.2f},{210 - (value - low) * 200 / spread:.2f}"
                for index, value in enumerate(series)
            )

        chart = f'<svg viewBox="0 0 560 220" role="img" aria-label="Flow-adjusted cumulative returns"><polyline fill="none" stroke="#126648" points="{points(returns)}"/>'
        if benchmark:
            chart += f'<polyline fill="none" stroke="#375ea3" points="{points(spy_returns)}"/>'
        chart += "</svg>"
        return (
            chart
            + f"<p>Account TWR {returns[-1]:.2%}; SPY "
            + (f"{spy_returns[-1]:.2%} (price only)." if benchmark else "UNVERIFIED (price only).")
            + " External cash flows are excluded.</p>"
        )


def html_report(snapshot: ReportSnapshot) -> bytes:
    source = ReportSnapshot.model_validate(snapshot)
    parts = [
        REPORT_PREFIX.decode(),
        '<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Project V accounting report</title>',
        "<style>body{font:16px system-ui;color:#17241e;max-width:1100px;margin:32px auto;padding:0 20px}table{border-collapse:collapse;width:100%}th,td{padding:8px;border-bottom:1px solid #ddd;text-align:left}svg{max-width:100%;height:auto}pre{white-space:pre-wrap}h2{margin-top:32px}</style></head><body>",
        f"<h1>{source.scope.environment} accounting report</h1><p>As of {_safe(source.as_of.isoformat())}. Estimates; 1099-B wins. Paper is simulated and is not for filing.</p>",
        "<h2>Equity curve: TWR vs SPY</h2>",
        _curve(source),
        "<h2>P&amp;L calendar</h2>",
    ]
    if source.days:
        parts.append(
            f'<svg viewBox="0 0 560 {(len(source.days) + 51) // 52 * 16}" role="img" aria-label="Daily P and L heat map">'
        )
        for index, row in enumerate(source.days):
            color = "#18805b" if row.day_pnl > 0 else "#b33f3f" if row.day_pnl < 0 else "#a3a3a3"
            parts.append(
                f'<rect x="{index % 52 * 10}" y="{index // 52 * 16}" width="8" height="12" fill="{color}"><title>{row.observation.session}: ${row.day_pnl:.2f}</title></rect>'
            )
        parts.append(
            "</svg><p>Each square is a completed session: green positive, red negative, gray flat.</p>"
        )
        parts.append(
            "<details><summary>Exact daily values</summary><table><tr><th>Session</th><th>Equity</th><th>P&amp;L</th><th>Return</th><th>External flow</th></tr>"
        )
        parts.extend(
            f"<tr><td>{row.observation.session}</td><td>{row.observation.equity:.2f}</td><td>{row.day_pnl:.2f}</td><td>{row.day_ret:.6%}</td><td>{row.observation.external_flows:.2f}</td></tr>"
            for row in source.days
        )
        parts.append("</table></details>")
    else:
        parts.append("<p>P&amp;L UNVERIFIED.</p>")
    parts.append(
        "<h2>Positions and observed stops</h2><table><tr><th>Symbol</th><th>Held shares</th><th>Broker stops</th></tr>"
    )
    if source.portfolio is None:
        parts.append('<tr><td colspan="3">Position evidence UNVERIFIED.</td></tr>')
    else:
        for symbol, held in sorted(source.portfolio.positions.items()):
            stops = tuple(row for row in source.portfolio.protective_stops if row.symbol == symbol)
            proof = (
                "; ".join(f"{row.qty} at ${row.stop_price:.2f}" for row in stops)
                if sum(row.qty for row in stops) == held.qty
                else "UNVERIFIED: coverage differs"
            )
            parts.append(
                f"<tr><td>{_safe(symbol)}</td><td>{held.qty}</td><td>{_safe(proof)}</td></tr>"
            )
        if not source.portfolio.positions:
            parts.append('<tr><td colspan="3">No holdings observed.</td></tr>')
    parts.append(
        "</table><h2>Last 20 physical trades</h2><table><tr><th>UTC</th><th>Symbol</th><th>Side</th><th>Shares</th><th>Price</th><th>Fees</th></tr>"
    )
    parts.extend(
        f"<tr><td>{_safe(row.ts.isoformat())}</td><td>{_safe(row.symbol)}</td><td>{row.side.value}</td><td>{row.qty}</td><td>{row.price:.2f}</td><td>{row.fees:.6f}</td></tr>"
        for row in source.trades
    )
    parts.append("</table>")
    for heading, lines in (
        ("Tax YTD", source.tax),
        ("Health", source.health),
        ("Edge after costs", source.edge),
    ):
        parts.append(
            f"<h2>{heading}</h2><pre>" + _safe("\n".join(lines) or "UNVERIFIED") + "</pre>"
        )
    parts.append("</body></html>")
    payload = "".join(parts).encode("utf-8")
    validate_report(payload)
    return payload


def validate_report(payload: bytes) -> None:
    if (
        not isinstance(payload, bytes)
        or not payload.startswith(REPORT_PREFIX)
        or not 1 <= len(payload) <= MAX_REPORT_BYTES
    ):
        raise DataIntegrityError("XK-08: generated bounded report bytes required")
    text = payload.decode("utf-8", errors="strict").lower()
    if any(
        token in text
        for token in (
            "<script",
            "javascript:",
            "http:",
            "https:",
            "<iframe",
            "<object",
            "<embed",
            "<form",
            "onload=",
            "onclick=",
            "src=",
            "href=",
        )
    ):
        raise DataIntegrityError(
            "XK-08: reports cannot contain scripts, external URLs or active content"
        )
    allowed: dict[str, set[str]] = {
        name: set()
        for name in (
            "html",
            "head",
            "title",
            "style",
            "body",
            "h1",
            "h2",
            "p",
            "table",
            "tr",
            "th",
            "pre",
            "details",
            "summary",
        )
    }
    allowed.update(
        {
            "html": {"lang"},
            "meta": {"charset", "name", "content"},
            "svg": {"viewbox", "role", "aria-label"},
            "polyline": {"fill", "stroke", "points"},
            "rect": {"x", "y", "width", "height", "fill"},
            "td": {"colspan"},
        }
    )

    class StaticReport(HTMLParser):
        style = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag not in allowed or any(name not in allowed[tag] for name, _ in attrs):
                raise DataIntegrityError("XK-08: unapproved HTML tag or attribute")
            self.style = tag == "style"

        def handle_endtag(self, tag: str) -> None:
            if tag not in allowed:
                raise DataIntegrityError("XK-08: unapproved HTML closing tag")
            if tag == "style":
                self.style = False

        def handle_data(self, data: str) -> None:
            if self.style and any(
                value in data.lower() for value in ("url", "@", "expression", "\\")
            ):
                raise DataIntegrityError("XK-08: CSS cannot load or execute content")

    parser = StaticReport()
    parser.feed(payload.decode("utf-8"))
    parser.close()


def save_html(root: Path, snapshot: ReportSnapshot) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    target = controlled_path(root / "latest.html")
    payload = html_report(snapshot)
    temporary = controlled_path(root / "latest.html.pending")
    try:
        with temporary.open("wb") as stream:
            stream.write(payload)
        temporary.replace(target)
        if target.read_bytes() != payload:
            raise ValueError("report readback differs")
        return target
    except Exception:
        raise DataIntegrityError("XK-08: local report could not be verified") from None


def monthly_csv(snapshot: ReportSnapshot, month: str) -> bytes:
    source = ReportSnapshot.model_validate(snapshot)
    try:
        start = date.fromisoformat(month + "-01")
        if start.strftime("%Y-%m") != month:
            raise ValueError("canonical month required")
    except Exception:
        raise DataIntegrityError("XK-08: use month YYYY-MM") from None
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")

    def row(*values: object) -> None:
        writer.writerow(
            tuple(
                "'" + value
                if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@"))
                else value
                for value in values
            )
        )

    row("section", "as_of_or_session", "key", "value", "environment")
    growth = Decimal(1)
    for day in source.days:
        with localcontext() as precision:
            precision.prec = 256
            growth *= 1 + day.day_ret
        if day.observation.session.strftime("%Y-%m") == month:
            for key, value in (
                ("equity", day.observation.equity),
                ("day_pnl", day.day_pnl),
                ("day_ret", day.day_ret),
                ("TWR", growth - 1),
                ("external_flows", day.observation.external_flows),
            ):
                row(
                    "equity/calendar", day.observation.session, key, value, source.scope.environment
                )
    if source.portfolio is not None:
        for symbol, held in sorted(source.portfolio.positions.items()):
            row(
                "positions",
                source.portfolio.as_of.isoformat(),
                symbol,
                held.qty,
                source.scope.environment,
            )
        for stop in source.portfolio.protective_stops:
            row(
                "stops",
                source.portfolio.as_of.isoformat(),
                stop.symbol,
                f"{stop.qty} at {stop.stop_price}",
                source.scope.environment,
            )
    for trade in source.trades:
        if trade.ts.strftime("%Y-%m") == month:
            row(
                "trades",
                trade.ts.isoformat(),
                trade.symbol,
                trade.model_dump_json(),
                source.scope.environment,
            )
    for name, lines in (("tax_ytd", source.tax), ("health", source.health), ("edge", source.edge)):
        for line in lines:
            row(name, source.as_of.isoformat(), "observed", line, source.scope.environment)
    if source.spy is None:
        row("benchmark", source.as_of.isoformat(), "SPY", "UNVERIFIED", source.scope.environment)
    else:
        for spy_day, price in source.spy:
            if spy_day.strftime("%Y-%m") == month:
                row("benchmark", spy_day, "SPY close (price only)", price, source.scope.environment)
    return output.getvalue().encode("utf-8")
