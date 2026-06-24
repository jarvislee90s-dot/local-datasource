"""Quick connectivity test for the 4 target data sources."""

import sys
from datetime import datetime, timedelta


def test_akshare_a_stock():
    print("\n=== Testing akshare A-share (600519 MAOTAI) ===")
    import akshare as ak

    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    df = ak.stock_zh_a_hist(symbol="600519", period="daily", start_date=start, end_date=end, adjust="qfq")
    print(f"Rows: {len(df)}")
    print(df.head(3).to_string(index=False))
    assert len(df) > 0, "No A-share data returned"


def test_akshare_hk_stock():
    print("\n=== Testing akshare HK stock (00700 TENCENT) ===")
    import akshare as ak

    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    df = ak.stock_hk_hist(symbol="00700", period="daily", start_date=start, end_date=end, adjust="qfq")
    print(f"Rows: {len(df)}")
    print(df.head(3).to_string(index=False))
    assert len(df) > 0, "No HK stock data returned"


def test_yfinance_us_stock():
    print("\n=== Testing yfinance US stock (AAPL) ===")
    import yfinance as yf

    ticker = yf.Ticker("AAPL")
    df = ticker.history(period="1mo")
    print(f"Rows: {len(df)}")
    print(df.head(3).to_string())
    assert len(df) > 0, "No US stock data returned"


def test_yfinance_global_etf():
    print("\n=== Testing yfinance global ETF (SPY, GLD, SLV) ===")
    import yfinance as yf

    df = yf.download(["SPY", "GLD", "SLV"], period="1mo", progress=False)
    print(f"Rows: {len(df)}")
    print(df.head(3).to_string())
    assert len(df) > 0, "No ETF data returned"


def test_worldbank():
    print("\n=== Testing wbgapi World Bank (GDP, CHN/USA) ===")
    import wbgapi as wb

    df = wb.data.DataFrame("NY.GDP.MKTP.CD", ["CHN", "USA"], time=range(2020, 2024))
    print(f"Shape: {df.shape}")
    print(df.to_string())
    assert df.shape[0] > 0, "No World Bank data returned"


def test_arxiv():
    print("\n=== Testing arxiv search ===")
    import arxiv

    client = arxiv.Client()
    search = arxiv.Search(query="machine learning", max_results=3)
    papers = list(client.results(search))
    print(f"Papers: {len(papers)}")
    for p in papers:
        print(f"- {p.title}")
    assert len(papers) > 0, "No arxiv papers returned"


if __name__ == "__main__":
    tests = [
        test_akshare_a_stock,
        test_akshare_hk_stock,
        test_yfinance_us_stock,
        test_yfinance_global_etf,
        test_worldbank,
        test_arxiv,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"[PASS] {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"[FAIL] {t.__name__}: {e}")

    print(f"\n--- Result: {passed} passed, {failed} failed ---")
    sys.exit(0 if failed == 0 else 1)
