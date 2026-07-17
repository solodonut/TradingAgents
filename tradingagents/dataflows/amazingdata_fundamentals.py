"""AmazingData(银河证券)沪深财务报表与基本面。

经常驻服务 ``/financial`` 端点取三大报表(table=balance_sheet|income|cash_flow),
返回全历史(每期多种 STATEMENT_TYPE)。整形逻辑:优先合并报表(STATEMENT_TYPE=="1")、
按 REPORTING_PERIOD 降序去重、look-ahead 过滤 ACTUAL_ANN_DATE(缺则 ANN_DATE)、精选
核心科目并映射中文标签输出 CSV。ETF/基金走 ``/etf`` 的份额+IOPV 快照,报表返回
``not_applicable``,与 Tushare/AKShare 契约一致。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import pandas as pd

from .amazingdata_stock import _extract_records
from .amazingdata_utils import (
    cached_call,
    call_amazingdata,
    display_symbol,
    is_fund_symbol,
    to_ad_code,
)
from .errors import NoMarketDataError

_FUNDAMENTAL_TTL_SECONDS = 24 * 3600
_MAX_PERIODS = 12  # 最近 12 期(约 3 年季报),兼顾趋势与 token 预算

_STATEMENT_TABLES = {
    "balance_sheet": "balance_sheet",
    "income_statement": "income",
    "cashflow": "cash_flow",
}

# (中文标签, 字段名);只输出记录中实际存在且非空的科目。字段名经实测锁定。
_DATE_FIELDS = [("报告期", "REPORTING_PERIOD"), ("公告日", "ACTUAL_ANN_DATE")]
_BALANCE_FIELDS = _DATE_FIELDS + [
    ("货币资金", "CURRENCY_CAP"),
    ("应收账款", "ACCT_RECEIVABLE"),
    ("流动资产合计", "TOTAL_CUR_ASSETS"),
    ("固定资产", "FIXED_ASSETS"),
    ("资产总计", "TOTAL_ASSETS"),
    ("流动负债合计", "TOTAL_CUR_LIAB"),
    ("非流动负债合计", "TOTAL_NONCUR_LIAB"),
    ("负债合计", "TOTAL_LIAB"),
    ("归母股东权益", "TOT_SHARE_EQUITY_EXCL_MIN_INT"),
    ("股东权益合计", "TOT_SHARE_EQUITY_INCL_MIN_INT"),
    ("未分配利润", "UNDISTRIBUTED_PRO"),
]
_INCOME_FIELDS = _DATE_FIELDS + [
    ("营业总收入", "TOT_OPERA_REV"),
    ("营业收入", "OPERA_REV"),
    ("营业总成本", "TOT_OPERA_COST"),
    ("营业利润", "OPERA_PROFIT"),
    ("利润总额", "TOTAL_PROFIT"),
    ("净利润", "NET_PRO_INCL_MIN_INT_INC"),
    ("归母净利润", "NET_PRO_EXCL_MIN_INT_INC"),
    ("所得税", "INCOME_TAX"),
    ("基本EPS", "BASIC_EPS"),
    ("稀释EPS", "DILUTED_EPS"),
]
_CASHFLOW_FIELDS = _DATE_FIELDS + [
    ("经营现金流净额", "NET_CASH_FLOWS_OPERA_ACT"),
    ("投资现金流净额", "NET_CASH_FLOWS_INV_ACT"),
    ("筹资现金流净额", "NET_CASH_FLOWS_FIN_ACT"),
    ("现金净增加额", "NET_INCR_CASH_AND_CASH_EQU"),
    ("期末现金余额", "END_BAL_CASH_CASH_EQU"),
    ("净利润", "NET_PROFIT"),
    ("自由现金流", "FREE_CASH_FLOW"),
]
_FIELDS_BY_KIND = {
    "balance_sheet": _BALANCE_FIELDS,
    "income_statement": _INCOME_FIELDS,
    "cashflow": _CASHFLOW_FIELDS,
}


def _fetch_financial(table: str, ad_code: str) -> list:
    cache_key = f"financial/{table}/{ad_code}"

    def _fetch():
        return call_amazingdata(
            "/financial",
            method="POST",
            json={"table": table, "code_list": [ad_code]},
            timeout=90.0,
        )

    resp = cached_call(cache_key, _FUNDAMENTAL_TTL_SECONDS, _fetch)
    return _extract_records(resp, ad_code)


def _prepare_frame(records: list, curr_date: str | None) -> pd.DataFrame:
    """合并报表优选 + look-ahead 过滤 + 按报告期降序去重。返回已排序 DataFrame。"""
    df = pd.DataFrame(records)
    if df.empty:
        return df

    # 优先合并报表本期(STATEMENT_TYPE=="1");若该子集为空则保留全部。
    if "STATEMENT_TYPE" in df.columns:
        consolidated = df[df["STATEMENT_TYPE"].astype(str) == "1"]
        if not consolidated.empty:
            df = consolidated

    ann_col = "ACTUAL_ANN_DATE" if "ACTUAL_ANN_DATE" in df.columns else "ANN_DATE"
    df = df.copy()
    df["_ann"] = pd.to_datetime(df[ann_col].astype(str), format="%Y%m%d", errors="coerce")
    if curr_date:
        df = df[df["_ann"] <= pd.Timestamp(curr_date)]
    if df.empty:
        return df

    df["_period"] = pd.to_datetime(
        df["REPORTING_PERIOD"].astype(str), format="%Y%m%d", errors="coerce"
    )
    df = df.sort_values("_period", ascending=False)
    return df.drop_duplicates("REPORTING_PERIOD", keep="first")


def _project(df: pd.DataFrame, field_specs: list) -> pd.DataFrame:
    """按 (标签, 字段) 投影;只保留记录中存在的列。日期列格式化为 YYYY-MM-DD。"""
    out = {}
    for label, field in field_specs:
        if field not in df.columns:
            continue
        series = df[field]
        if field in ("REPORTING_PERIOD", "ANN_DATE", "ACTUAL_ANN_DATE"):
            series = pd.to_datetime(
                series.astype(str), format="%Y%m%d", errors="coerce"
            ).dt.strftime("%Y-%m-%d")
        out[label] = series.values
    return pd.DataFrame(out)


def _etf_statement_not_applicable(symbol: str, title: str, freq: str) -> str:
    label = display_symbol(symbol)
    header = f"# {title} for {label} (ETF/Fund, AmazingData / 银河证券, {freq})\n"
    header += "# Status: Not applicable to fund/ETF products\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return (
        header
        + "item,status,detail\n"
        + f"{title},not_applicable,"
        + "ETF/fund products do not publish operating-company financial statements; "
        + "use the AmazingData fund/ETF snapshot plus price and technical data.\n"
    )


def _statement_report(
    symbol: str, kind: str, title: str, freq: str, curr_date: str | None
) -> str:
    label = display_symbol(symbol)
    ad_code = to_ad_code(symbol)
    records = _fetch_financial(_STATEMENT_TABLES[kind], ad_code)
    if not records:
        raise NoMarketDataError(symbol, label, f"no AmazingData {kind} data")

    df = _prepare_frame(records, curr_date)
    if df.empty:
        raise NoMarketDataError(symbol, label, f"no {kind} periods on/before {curr_date}")

    out = _project(df.head(_MAX_PERIODS), _FIELDS_BY_KIND[kind])
    if out.empty:
        raise NoMarketDataError(symbol, label, f"no core {kind} fields available")

    header = f"# {title} for {label} (A-share, AmazingData / 银河证券, {freq})\n"
    header += "# 合并报表,金额单位:元(EPS 除外)\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return header + out.to_csv(index=False)


# ---- ETF/基金快照 -------------------------------------------------------


def _latest_record(table_records: list, date_field: str) -> dict:
    """取按 date_field 最新的一条记录。"""
    best, best_key = {}, ""
    for r in table_records:
        key = str(r.get(date_field) or "")
        if key >= best_key:
            best, best_key = r, key
    return best


def _fetch_etf(kind: str, ad_code: str) -> list:
    cache_key = f"etf/{kind}/{ad_code}"

    def _fetch():
        return call_amazingdata(
            "/etf",
            method="POST",
            json={"kind": kind, "code_list": [ad_code]},
            timeout=90.0,
        )

    resp = cached_call(cache_key, _FUNDAMENTAL_TTL_SECONDS, _fetch)
    return _extract_records(resp, ad_code)


def _fund_report(symbol: str, curr_date: str | None) -> str:
    label = display_symbol(symbol)
    ad_code = to_ad_code(symbol)

    share = _fetch_etf("share", ad_code)
    iopv = _fetch_etf("iopv", ad_code)
    if not share and not iopv:
        raise NoMarketDataError(symbol, label, "no AmazingData fund snapshot")

    share_latest = _latest_record(share, "CHANGE_DATE") if share else {}
    iopv_latest = _latest_record(iopv, "PRICE_DATE") if iopv else {}

    candidates = [
        ("最新份额(万份)", share_latest.get("FUND_SHARE")),
        ("总份额(万份)", share_latest.get("TOTAL_SHARE")),
        ("流通份额(万份)", share_latest.get("FLOAT_SHARE")),
        ("份额变动日", share_latest.get("CHANGE_DATE")),
        ("参考净值IOPV", iopv_latest.get("IOPV_NAV")),
        ("IOPV日期", iopv_latest.get("PRICE_DATE")),
    ]
    items = [
        {"指标": lbl, "数值": str(val)}
        for lbl, val in candidates
        if val not in (None, "", "nan")
    ]
    if not items:
        raise NoMarketDataError(symbol, label, "no fund snapshot fields")

    header = f"# Fund/ETF Fundamentals for {label} (AmazingData / 银河证券)\n"
    header += "# Instrument type: 沪深上市基金/ETF,非经营性公司\n"
    header += "# 份额规模 + 参考净值(IOPV)快照;持仓/主题请见 ETF 档案与静态配置\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return header + pd.DataFrame(items).to_csv(index=False)


# ---- 对外方法(与 Tushare/AKShare 同签名)--------------------------------


def get_fundamentals(
    ticker: Annotated[str, "Mainland ticker (600519, 159241, ...)"],
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
):
    if is_fund_symbol(ticker):
        return _fund_report(ticker, curr_date)

    label = display_symbol(ticker)
    ad_code = to_ad_code(ticker)
    income = _prepare_frame(_fetch_financial("income", ad_code), curr_date)
    balance = _prepare_frame(_fetch_financial("balance_sheet", ad_code), curr_date)
    cashflow = _prepare_frame(_fetch_financial("cash_flow", ad_code), curr_date)
    if income.empty and balance.empty and cashflow.empty:
        raise NoMarketDataError(ticker, label, "no AmazingData stock fundamentals")

    name = ""
    for frame in (income, balance, cashflow):
        if not frame.empty and "SECURITY_NAME" in frame.columns:
            name = str(frame.iloc[0].get("SECURITY_NAME") or "")
            break

    header = f"# Company Fundamentals for {label} {name} (A-share, AmazingData / 银河证券)\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    result = header
    result += _section("Income Statement (recent)", _project(income.head(4), _INCOME_FIELDS))
    result += _section("Balance Sheet (recent)", _project(balance.head(4), _BALANCE_FIELDS))
    result += _section("Cash Flow (recent)", _project(cashflow.head(4), _CASHFLOW_FIELDS))
    return result


def _section(title: str, data: pd.DataFrame) -> str:
    if data is None or data.empty:
        return ""
    return f"\n## {title}\n\n" + data.to_csv(index=False)


def get_balance_sheet(
    ticker: Annotated[str, "Mainland ticker (600519, 159241, ...)"],
    freq: Annotated[str, "frequency hint, accepted for API parity"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
):
    if is_fund_symbol(ticker):
        return _etf_statement_not_applicable(ticker, "Balance Sheet", freq)
    return _statement_report(ticker, "balance_sheet", "Balance Sheet", freq, curr_date)


def get_income_statement(
    ticker: Annotated[str, "Mainland ticker (600519, 159241, ...)"],
    freq: Annotated[str, "frequency hint, accepted for API parity"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
):
    if is_fund_symbol(ticker):
        return _etf_statement_not_applicable(ticker, "Income Statement", freq)
    return _statement_report(ticker, "income_statement", "Income Statement", freq, curr_date)


def get_cashflow(
    ticker: Annotated[str, "Mainland ticker (600519, 159241, ...)"],
    freq: Annotated[str, "frequency hint, accepted for API parity"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
):
    if is_fund_symbol(ticker):
        return _etf_statement_not_applicable(ticker, "Cash Flow", freq)
    return _statement_report(ticker, "cashflow", "Cash Flow", freq, curr_date)
