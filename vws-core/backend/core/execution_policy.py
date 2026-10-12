"""R-08/R-10/GD-07: sole source of prohibited execution and reflection names.

This declarative module alone is exempt from the authored-source AST scan.
It contains no SDK import, callable implementation, or execution capability.
"""

from typing import Final

BANNED_ORDER_REQUESTS: Final[frozenset[str]] = frozenset(
    {
        "OrderRequest",
        "MarketOrderRequest",
        "LimitOrderRequest",
        "StopOrderRequest",
        "StopLimitOrderRequest",
        "TrailingStopOrderRequest",
        "ReplaceOrderRequest",
        "ClosePositionRequest",
        "TakeProfitRequest",
        "StopLossRequest",
    }
)

# AX-12/14: only these SDK members may occur in the exact isolated executor.
# Money movement and every other prohibited request remain banned everywhere.
EXECUTOR_RELATIVE_PATH: Final[str] = "backend/execution/alpaca_executor.py"
ALLOWED_EXECUTOR_NAMES: Final[frozenset[str]] = frozenset(
    {
        "LimitOrderRequest",
        "StopOrderRequest",
        "TakeProfitRequest",
        "StopLossRequest",
        "submit_order",
        "cancel_order_by_id",
        "OTO",
        "OCO",
    }
)
ORDER_HTTP_PATH: Final[str] = "/v2/orders"
ISOLATED_ORDER_CLASSES: Final[frozenset[str]] = frozenset({"OTO", "OCO"})
ORDER_HTTP_FACTORY_NAMES: Final[frozenset[str]] = frozenset({"make_order_session", "OrderSession"})

BANNED_EXECUTION_METHODS: Final[frozenset[str]] = frozenset(
    {
        "submit_order",
        "replace_order_by_id",
        "replace_order",
        "cancel_order_by_id",
        "cancel_order",
        "cancel_orders",
        "cancel_all_orders",
        "close_position",
        "close_all_positions",
        "exercise_options_position",
        "create_transfer",
        "create_ach_transfer",
        "create_bank_transfer",
        "create_wire_transfer",
        "submit_transfer",
        "initiate_transfer",
        "transfer_create",
        "transfer",
        "create_ach_relationship_for_account",
        "delete_ach_relationship_for_account",
        "create_transfer_for_account",
        "cancel_transfer_for_account",
        "create_journal",
        "create_batch_journal",
        "create_reverse_batch_journal",
        "cancel_journal_by_id",
    }
)

# Amendment 01 section 2.1: removed account and asset fields may never be read.
# This is the sole declaration of the deprecated SDK field names.
BANNED_ALPACA_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "pattern_day_trader",
        "daytrade_count",
        "last_daytrade_count",
        "daytrading_buying_power",
        "last_daytrading_buying_power",
        "bod_dtbp",
        "pdt_check",
        "dtbp_check",
        "easy_to_borrow",
        "maintenance_margin_requirement",
    }
)

BANNED_DYNAMIC_BUILTINS: Final[frozenset[str]] = frozenset(
    {"eval", "exec", "compile", "__import__"}
)
RESTRICTED_REFLECTION: Final[frozenset[str]] = frozenset(
    {"getattr", "setattr", "__getattribute__", "__setattr__", "attrgetter", "methodcaller"}
)
BANNED_IMPORT_FUNCTIONS: Final[frozenset[str]] = frozenset({"importlib.import_module"})
MUTATING_HTTP_METHODS: Final[frozenset[str]] = frozenset({"POST", "DELETE", "PATCH", "PUT"})
DIRECT_HTTP_CALLS: Final[frozenset[str]] = frozenset(
    {
        "requests.Session",
        "requests.sessions.Session",
        "requests.session",
        "httpx.Client",
        "httpx.AsyncClient",
        "requests.request",
        "requests.get",
        "requests.post",
        "requests.put",
        "requests.patch",
        "requests.delete",
        "requests.head",
        "requests.options",
        "requests.api.request",
        "requests.api.get",
        "requests.api.post",
        "requests.api.put",
        "requests.api.patch",
        "requests.api.delete",
        "requests.api.head",
        "requests.api.options",
        "httpx.request",
        "httpx.get",
        "httpx.post",
        "httpx.put",
        "httpx.patch",
        "httpx.delete",
        "httpx.head",
        "httpx.options",
        "httpx.stream",
    }
)
HTTP_CLIENT_TYPES: Final[frozenset[str]] = frozenset(
    {"requests.Session", "requests.sessions.Session", "httpx.Client", "httpx.AsyncClient"}
)
BANNED_TLS_MEMBERS: Final[frozenset[str]] = frozenset({"CERT_NONE", "_create_unverified_context"})
HTTP_URL_PATTERN: Final[str] = r"http://([^/\s'\"<>]+)"
BANNED_LLM_TOOL_FIELDS: Final[frozenset[str]] = frozenset(
    {"tools", "functions", "tool_choice", "function_call"}
)
PRIVATE_LLM_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "account",
        "account_id",
        "account_number",
        "account_flags",
        "portfolio",
        "portfolio_snapshot",
        "positions",
        "buying_power",
        "cash",
        "settled_cash",
        "equity",
        "net_liquidation",
        "cost_basis",
        "cash_available",
        "alpaca_api_key",
        "alpaca_secret_key",
        "plaid_access_token",
        "telegram_bot_token",
    }
)
PRIVATE_LLM_MODELS: Final[frozenset[str]] = frozenset(
    {"PortfolioSnapshot", "AccountFlags", "PortfolioState", "PositionState", "Settings"}
)
INBOUND_NETWORK_CALLS: Final[frozenset[str]] = frozenset(
    {
        "socket.socket.bind",
        "socket.socket.listen",
        "socket.create_server",
        "asyncio.start_server",
        "asyncio.start_unix_server",
        "asyncio.create_server",
        "http.server.HTTPServer",
        "http.server.ThreadingHTTPServer",
        "socketserver.TCPServer",
        "socketserver.ThreadingTCPServer",
        "socketserver.UDPServer",
        "socketserver.ThreadingUDPServer",
    }
)
TRANSFER_CREATION_WORDS: Final[frozenset[str]] = frozenset(
    {
        "create",
        "submit",
        "initiate",
        "execute",
        "send",
        "withdraw",
        "deposit",
        "cancel",
        "delete",
        "remove",
        "replace",
        "update",
        "add",
        "link",
        "move",
    }
)
MONEY_ENDPOINT_WORDS: Final[frozenset[str]] = frozenset(
    {
        "transfer",
        "transfers",
        "wallet",
        "wallets",
        "whitelist",
        "whitelists",
        "journal",
        "journals",
        "ach",
        "wire",
        "bank",
        "fund",
        "funding",
        "deposit",
        "deposits",
        "withdrawal",
        "withdrawals",
        "money",
    }
)

# Generated dependencies and tool output are not project-authored source. No
# authored package, script, test, or root-level Python directory is excluded.
GENERATED_DIRECTORIES: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".hypothesis",
        ".tox",
        ".nox",
        "build",
        "dist",
        "mutants",
        "node_modules",
    }
)
