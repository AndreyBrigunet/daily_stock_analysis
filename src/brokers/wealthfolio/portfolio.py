from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


logger = logging.getLogger(__name__)


class WealthfolioPortfolioError(RuntimeError):
    """Raised when the Wealthfolio MCP portfolio cannot be loaded."""


@dataclass
class WealthfolioHolding:
    symbol: str
    name: Optional[str]
    account: Optional[str]
    quantity: float
    currency: Optional[str]
    market_value_base: Optional[float]
    cost_basis_base: Optional[float]
    avg_cost_base: Optional[float]
    unrealized_gain_pct: Optional[float]
    total_gain_base: Optional[float]
    total_gain_pct: Optional[float]
    day_change_pct: Optional[float]
    weight: Optional[float]


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _mcp_url() -> str:
    url = _env("WEALTHFOLIO_URL")
    if not url:
        raise WealthfolioPortfolioError(
            "WEALTHFOLIO_URL lipsește. Exemplu: https://folio.brigu.net/mcp"
        )

    url = url.rstrip("/")
    if not url.endswith("/mcp"):
        url += "/mcp"
    return url


def _token() -> str:
    token = _env("WEALTHFOLIO_TOKEN")
    if not token:
        raise WealthfolioPortfolioError("WEALTHFOLIO_TOKEN lipsește.")
    return token


def _timeout() -> int:
    raw = _env("WEALTHFOLIO_TIMEOUT_SECONDS")
    if not raw:
        return 30
    try:
        return max(5, int(raw))
    except ValueError as exc:
        raise WealthfolioPortfolioError(
            "WEALTHFOLIO_TIMEOUT_SECONDS trebuie să fie număr întreg."
        ) from exc


def _parse_mcp_response(response: requests.Response) -> Dict[str, Any]:
    """Parse Wealthfolio MCP Streamable HTTP JSON/SSE responses."""
    content_type = (response.headers.get("content-type") or "").lower()
    body = response.text or ""

    if "application/json" in content_type:
        try:
            parsed = response.json()
        except ValueError as exc:
            raise WealthfolioPortfolioError(
                f"Wealthfolio a răspuns cu JSON invalid: {body[:500]}"
            ) from exc
        if not isinstance(parsed, dict):
            raise WealthfolioPortfolioError("Răspuns MCP JSON neașteptat.")
        return parsed

    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    raise WealthfolioPortfolioError(
        "Nu am putut extrage JSON-ul din răspunsul MCP Wealthfolio. "
        f"HTTP {response.status_code}; body={body[:500]!r}"
    )


def _post_mcp(
    session: requests.Session,
    *,
    url: str,
    token: str,
    payload: Dict[str, Any],
    session_id: Optional[str] = None,
    timeout: int,
) -> requests.Response:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["mcp-session-id"] = session_id

    try:
        response = session.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise WealthfolioPortfolioError(
            f"Nu m-am putut conecta la Wealthfolio MCP: {exc}"
        ) from exc

    if response.status_code >= 400:
        raise WealthfolioPortfolioError(
            f"Wealthfolio MCP HTTP {response.status_code}: "
            f"{(response.text or '')[:1000]}"
        )

    return response


def _initialize_mcp(
    session: requests.Session,
    *,
    url: str,
    token: str,
    timeout: int,
) -> str:
    response = _post_mcp(
        session,
        url=url,
        token=token,
        timeout=timeout,
        payload={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {
                    "name": "daily-stock-analysis",
                    "version": "1.0",
                },
            },
        },
    )

    payload = _parse_mcp_response(response)
    if payload.get("error"):
        raise WealthfolioPortfolioError(
            f"Initialize MCP a eșuat: {json.dumps(payload['error'], ensure_ascii=False)}"
        )

    session_id = (response.headers.get("mcp-session-id") or "").strip()
    if not session_id:
        raise WealthfolioPortfolioError(
            "Wealthfolio nu a returnat headerul mcp-session-id."
        )

    notify = _post_mcp(
        session,
        url=url,
        token=token,
        session_id=session_id,
        timeout=timeout,
        payload={
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        },
    )
    if notify.status_code not in (200, 202):
        raise WealthfolioPortfolioError(
            f"notifications/initialized a întors HTTP {notify.status_code}"
        )

    return session_id


def _call_get_holdings(
    session: requests.Session,
    *,
    url: str,
    token: str,
    session_id: str,
    timeout: int,
) -> Dict[str, Any]:
    response = _post_mcp(
        session,
        url=url,
        token=token,
        session_id=session_id,
        timeout=timeout,
        payload={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "get_holdings",
                "arguments": {"viewMode": "table"},
            },
        },
    )

    rpc = _parse_mcp_response(response)

    if rpc.get("error"):
        raise WealthfolioPortfolioError(
            "get_holdings a eșuat: "
            + json.dumps(rpc["error"], ensure_ascii=False)
        )

    result = rpc.get("result") or {}
    if result.get("isError") is True:
        raise WealthfolioPortfolioError(
            "Wealthfolio get_holdings a returnat isError=true: "
            + json.dumps(result, ensure_ascii=False)[:1500]
        )

    for item in result.get("content") or []:
        if not isinstance(item, dict):
            continue

        if item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str):
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    return parsed

        structured = item.get("structuredContent")
        if isinstance(structured, dict):
            return structured

    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured

    raise WealthfolioPortfolioError(
        "Răspunsul get_holdings nu conține payload-ul JSON așteptat."
    )


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_holding(raw: Dict[str, Any]) -> Optional[WealthfolioHolding]:
    symbol = str(raw.get("symbol") or "").strip().upper()
    holding_type = str(raw.get("holdingType") or "").strip().lower()
    quantity = _number(raw.get("quantity")) or 0.0

    if not symbol or symbol == "CASH":
        return None
    if holding_type and holding_type != "security":
        return None
    if quantity == 0:
        return None

    cost_basis = _number(raw.get("costBasisBase"))
    avg_cost = None
    if cost_basis is not None and quantity:
        avg_cost = cost_basis / quantity

    return WealthfolioHolding(
        symbol=symbol,
        name=(str(raw.get("name")).strip() if raw.get("name") else None),
        account=(str(raw.get("account")).strip() if raw.get("account") else None),
        quantity=quantity,
        currency=(str(raw.get("currency")).strip() if raw.get("currency") else None),
        market_value_base=_number(raw.get("marketValueBase")),
        cost_basis_base=cost_basis,
        avg_cost_base=avg_cost,
        unrealized_gain_pct=_number(raw.get("unrealizedGainPct")),
        total_gain_base=_number(raw.get("totalGainBase")),
        total_gain_pct=_number(raw.get("totalGainPct")),
        day_change_pct=_number(raw.get("dayChangePct")),
        weight=_number(raw.get("weight")),
    )


def load_wealthfolio_holdings(
    *,
    save_snapshot: bool = True,
    snapshot_path: str | Path = "reports/portfolio_holdings.json",
) -> List[WealthfolioHolding]:
    """Load current non-cash Wealthfolio holdings through MCP get_holdings."""
    url = _mcp_url()
    token = _token()
    timeout = _timeout()

    with requests.Session() as session:
        session_id = _initialize_mcp(
            session,
            url=url,
            token=token,
            timeout=timeout,
        )
        payload = _call_get_holdings(
            session,
            url=url,
            token=token,
            session_id=session_id,
            timeout=timeout,
        )

    raw_holdings = payload.get("holdings")
    if not isinstance(raw_holdings, list):
        raise WealthfolioPortfolioError(
            "Payload-ul Wealthfolio nu conține lista 'holdings'."
        )

    holdings: List[WealthfolioHolding] = []
    for raw in raw_holdings:
        if isinstance(raw, dict):
            holding = _normalize_holding(raw)
            if holding is not None:
                holdings.append(holding)

    if save_snapshot:
        destination = Path(snapshot_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "source": "wealthfolio",
            "url": url,
            "currency": payload.get("currency"),
            "account_scope": payload.get("accountScope"),
            "total_value": payload.get("totalValue"),
            "original_count": payload.get("originalCount"),
            "truncated": payload.get("truncated"),
            "holdings_count": len(holdings),
            "holdings": [asdict(item) for item in holdings],
        }
        destination.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if payload.get("truncated") and len(raw_holdings) >= 100:
        raise WealthfolioPortfolioError(
            "Wealthfolio a limitat get_holdings la 100 poziții; lista ar fi incompletă."
        )

    logger.info("Wealthfolio: %d poziții active încărcate.", len(holdings))
    return holdings


def load_wealthfolio_stock_codes() -> List[str]:
    """Return unique ticker symbols from the live Wealthfolio portfolio."""
    seen = set()
    result: List[str] = []

    for holding in load_wealthfolio_holdings():
        symbol = holding.symbol.strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        result.append(symbol)

    return result
