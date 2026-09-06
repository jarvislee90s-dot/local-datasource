"""中国境内债券(标债)数据 provider。

国债收益率曲线与交易所行情走 akshare;信用债发行信息直连中国货币网
(akshare 的 ``bond_info_cm`` 因货币网改版断裂,见 ``_bond_info_cm_direct``)。

已知限制(akshare 免费层):
- 中债估值 YTM / 全价:无(Wind/中债登付费)
- 标债赎回回售条款详情 / 票息 / 到期日 / 剩余期限:无(在募集说明书里)
- bond_info_detail_cm 接口有上游 bug,本期不调用
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from functools import lru_cache
from typing import Literal

import akshare as ak
import pandas as pd
import requests

from local_datasource.formatters import format_csv_output


BondKind = Literal["yield_curve", "issue_info", "credit_daily"]

# --- 中国货币网直连(issue_info) ---
# akshare 的 bond_info_cm 断裂根因(2026-09 实测):货币网改版后,列表接口
# BondMarketInfoList2 强制要求 bondType —— 不带时返回错误结构
# {total, pageTotalSize, errorMsg:'债券类型必选'},没有 pageTotal 键,
# akshare ≤1.18.94 读该键即 KeyError;其文档指向的查询页也已 403 下线,
# 最新 1.18.94 未修复。bondType 不支持多值/通配(实测 403),零结果返回正常
# 空结构。故直连接口:取类型字典后遍历全部类型查询再合并,输出列与原
# akshare 一致。
#
# 限流实测(家庭宽带 IPv6/IPv4 与手机热点三出口一致复现):WAF(openresty)按
# "IP × 窗口请求数"限流,阈值极低 —— 无间隔连发 5 个即触发 HTTP 421(报文
# "too many connections from your internet address"),20s/5s 间隔在配额耗尽
# 后也无效,窗口需静默数分钟恢复。策略:进程级共享单条 keep-alive 连接 +
# 每请求固定间隔(把 31 个请求摊进窗口) + 421 长退避一次后放弃并如实提示。
# 注:IPv4 边缘对 Python OpenSSL 指纹返回 403(curl/Schannel 可过),无法借
# IPv4 绕限流。
_CM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"
}
_CM_DICT_URL = "https://www.chinamoney.com.cn/ags/ms/cm-u-bond-md/BondBaseInfoSearchCondition"
_CM_LIST_URL = "https://www.chinamoney.com.cn/ags/ms/cm-u-bond-md/BondMarketInfoList2"
_CM_PAGE_SIZE = 15
_CM_REQUEST_INTERVAL = 2.5  # 相邻请求最小间隔(秒):窗口预算摊薄,30+ 个请求 ≈ 80s
_CM_RATE_LIMIT_BACKOFF = 240  # 421 后静默退避(秒),退避后重试一次再失败则报错

_CM_SESSION = requests.Session()
_CM_SESSION.headers.update(_CM_HEADERS)
_CM_LAST_REQUEST_AT = 0.0


class _CmRateLimited(Exception):
    """货币网窗口限流(HTTP 421):按 IP 限请求数,退避后可恢复。"""


def _cm_throttle() -> None:
    """相邻请求强制最小间隔,把请求数摊进 WAF 窗口。"""
    global _CM_LAST_REQUEST_AT
    wait = _CM_REQUEST_INTERVAL - (time.monotonic() - _CM_LAST_REQUEST_AT)
    if wait > 0:
        time.sleep(wait)
    _CM_LAST_REQUEST_AT = time.monotonic()


def _cm_post(url: str, data: dict) -> requests.Response:
    """货币网 POST(进程级单连接 keep-alive + 节流;421 判定在调用方)。"""
    _cm_throttle()
    return _CM_SESSION.post(url, data=data, timeout=30)

_CM_COLUMN_MAP = {
    "bondDefinedCode": "查询代码",
    "bondName": "债券简称",
    "bondCode": "债券代码",
    "issueStartDate": "发行日期",
    "bondType": "债券类型",
    "entyFullName": "发行人/受托机构",
    "debtRtng": "最新债项评级",
}
_CM_OUTPUT_COLUMNS = [
    "债券简称", "债券代码", "发行人/受托机构", "债券类型", "发行日期", "最新债项评级", "查询代码",
]


@lru_cache(maxsize=1)
def _cm_bond_type_codes() -> tuple[str, ...]:
    """货币网债券类型代码表(100001=国债 ... 100086=TLAC非资本债券,共 30 个)。

    代码表为站点静态配置,进程内缓存一次;失败报含"不可达"的网络指引。
    """
    try:
        r = _cm_post(_CM_DICT_URL, {})
        items = r.json()["data"]["bondType"]
        codes = tuple(str(it["bondTypeCode"]) for it in items)
    except Exception as e:
        raise ValueError(
            f"货币网债券类型字典请求失败: {e}。该源在当前网络不可达,请检查网络/代理后重试"
        ) from e
    if not codes:
        raise ValueError("货币网债券类型字典返回空,站点结构可能已变化")
    return codes


def _cm_fetch(bond_type: str, page_no: int, bond_code: str, bond_issue: str) -> dict:
    """查询单类型单页;网络异常重试一次(2s),421 长退避一次再失败即抛限流。

    HTTP 421 = WAF 窗口限流:先静默 4 分钟让窗口恢复,重试一次仍 421 则抛
    专用限流异常由上层中止并如实提示(绝不带着限流继续打)。
    """
    payload = {
        "pageNo": str(page_no),
        "pageSize": str(_CM_PAGE_SIZE),
        "bondName": "",
        "bondCode": bond_code,
        "issueEnty": bond_issue,
        "bondType": bond_type,
        "bondSpclPrjctVrty": "",
        "couponType": "",
        "issueYear": "",
        "entyDefinedCode": "",
        "rtngShrt": "",
    }
    rate_limited = False
    last_exc: Exception | None = None
    for attempt in range(2):  # attempt 0:正常;attempt 1:421 退避后或网络错误 2s 后
        if attempt:
            time.sleep(_CM_RATE_LIMIT_BACKOFF if rate_limited else 2)
        try:
            r = _cm_post(_CM_LIST_URL, payload)
            if r.status_code == 421:
                rate_limited = True
                continue
            data = r.json().get("data") or {}
            if "errorMsg" in data:
                raise ValueError(f"货币网拒绝查询({data['errorMsg']})")
            return data
        except _CmRateLimited:
            raise
        except Exception as e:  # noqa: BLE001 - 网络失败类型不定,统一重试后汇总
            last_exc = e
    if rate_limited:
        raise _CmRateLimited("货币网窗口限流(HTTP 421),退避重试后仍限流")
    raise ValueError(f"bondType={bond_type} 第{page_no}页: {last_exc}") from last_exc


def _fetch_one_type(bond_type: str, bond_code: str, bond_issue: str) -> list[dict]:
    """查询单类型全部页(首页满页时按 pageTotal 翻余页)。"""
    data = _cm_fetch(bond_type, 1, bond_code, bond_issue)
    rows = list(data.get("resultList") or [])
    for page in range(2, int(data.get("pageTotal") or 1) + 1):
        rows += _cm_fetch(bond_type, page, bond_code, bond_issue).get("resultList") or []
    return rows


def _bond_info_cm_direct(bond_code: str = "", bond_issue: str = "") -> pd.DataFrame:
    """直连货币网债券信息列表,输出与 akshare bond_info_cm 相同的 7 个中文列。

    串行遍历全部债券类型(进程级单条 keep-alive 连接 + 每请求节流),合并
    去重;任一类型重试后仍失败则整体报错并列出失败类型 —— 绝不静默返回缺
    类型的残缺结果。触发 WAF 窗口限流(HTTP 421)时先退避 4 分钟重试一次,
    仍限流则中止剩余请求并如实提示。
    """
    codes = _cm_bond_type_codes()
    failures: list[str] = []
    collected: list[dict] = []
    rate_limited = False
    for t in codes:
        try:
            collected += _fetch_one_type(t, bond_code, bond_issue)
        except _CmRateLimited:
            rate_limited = True
            break
        except Exception as e:  # noqa: BLE001 - 单类型失败汇总后统一报错
            failures.append(f"{t}({e})")
    if rate_limited:
        raise ValueError(
            "货币网窗口限流(HTTP 421,按 IP 限窗口内请求数,静默数分钟可恢复)。"
            "已自动退避重试一次仍限流:请稍候数分钟再试;同一会话内对同一"
            "发行人/代码的重复查询建议走 download 缓存"
        )
    if failures:
        raise ValueError(
            f"货币网债券信息查询有 {len(failures)}/{len(codes)} 个债券类型失败: "
            f"{'; '.join(failures)}。该源在当前网络不可达或不稳定,请重试;"
            f"若持续失败请检查网络/代理"
        )
    if not collected:
        return pd.DataFrame(columns=_CM_OUTPUT_COLUMNS)
    df = pd.DataFrame(collected).rename(columns=_CM_COLUMN_MAP)
    df = df.drop_duplicates(subset=["查询代码", "债券代码", "债券简称"])
    return df[_CM_OUTPUT_COLUMNS]


def _normalize_bond_code(code: str) -> str:
    """将债券代码归一为 akshare 所需格式。"""
    stripped = re.sub(r"\.(IB|SH|SZ|sh|sz|ib)$", "", code)
    if stripped.isdigit():
        return stripped
    if re.match(r"^(sh|sz|bj)\d+$", stripped, re.IGNORECASE):
        return stripped.lower()
    raise ValueError(f"Invalid bond code: {code}")


def _query_yield_curve(start_date: str, end_date: str) -> pd.DataFrame:
    """国债到期收益率曲线(bond_china_yield)。"""
    start_fmt = datetime.strptime(start_date, "%Y-%m-%d").strftime("%Y%m%d")
    end_fmt = datetime.strptime(end_date, "%Y-%m-%d").strftime("%Y%m%d")
    df = ak.bond_china_yield(start_date=start_fmt, end_date=end_fmt)
    if df.empty:
        raise ValueError(f"No yield curve data between {start_date} and {end_date}")
    return df


def _query_issue_info(bond_code: str) -> pd.DataFrame:
    """信用债发行信息(直连货币网),精确过滤排除子串误匹配。

    实测按代码查询会返回子串误命中(如 2180495 命中 112180495 的存单),
    必须精确匹配 df['债券代码']==code 后再返回。
    """
    code = _normalize_bond_code(bond_code)
    df = _bond_info_cm_direct(bond_code=code)
    if df.empty:
        raise ValueError(f"No bond found for code: {bond_code}")
    df = df[df["债券代码"].astype(str) == code].copy()
    if df.empty:
        raise ValueError(f"No exact match for bond code: {bond_code}")
    return df


def _query_issue_info_by_issuer(issuer: str) -> pd.DataFrame:
    """按发行人查,返回最新一只标债(按发行日期降序取首条)。

    用户场景:给发行人名 → 拿到一个债券代码 → 链路继续查债信息/财务。
    故只返回最新一只,不返回全部列表。无代码/无日期的注册类记录
    (债券代码='---')在降序排序中自然沉底,不会入选。
    """
    df = _bond_info_cm_direct(bond_issue=issuer)
    if df.empty:
        raise ValueError(f"No bond found for issuer: {issuer}")
    # 发行日期降序,取最新一只
    df = df.sort_values("发行日期", ascending=False).head(1).copy()
    return df


def _query_credit_daily(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """信用债交易所历史日行情(bond_zh_hs_daily),按日期过滤。"""
    if not re.match(r"^(sh|sz)\d+$", symbol, re.IGNORECASE):
        raise ValueError(f"credit_daily symbol must be like sh019623, got: {symbol}")
    df = ak.bond_zh_hs_daily(symbol=symbol.lower())
    if df.empty:
        raise ValueError(f"No data returned for {symbol}")
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df[(df["date"] >= start_date) & (df["date"] <= end_date)].copy()


def query_bond(
    kind: BondKind,
    file_path: str,
    start_date: str | None = None,
    end_date: str | None = None,
    bond_code: str | None = None,
    symbol: str | None = None,
    bond_issue: str | None = None,
) -> tuple[str, str]:
    """查询中国境内债券数据并输出 CSV。"""
    if kind == "yield_curve":
        if not start_date or not end_date:
            raise ValueError("yield_curve requires start_date and end_date")
        df = _query_yield_curve(start_date, end_date)
    elif kind == "issue_info":
        if bond_code and bond_issue:
            raise ValueError("issue_info: bond_code 与 bond_issue 互斥")
        if bond_code:
            df = _query_issue_info(bond_code)
        elif bond_issue:
            df = _query_issue_info_by_issuer(bond_issue)
        else:
            raise ValueError("issue_info requires bond_code or bond_issue")
    elif kind == "credit_daily":
        if not symbol or not start_date or not end_date:
            raise ValueError("credit_daily requires symbol, start_date, end_date")
        df = _query_credit_daily(symbol, start_date, end_date)
    else:
        raise ValueError(f"Unsupported bond kind: {kind}")

    if df.empty:
        raise ValueError(f"No data returned for bond kind={kind}")

    return format_csv_output(df, file_path)
