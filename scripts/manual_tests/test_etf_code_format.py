"""
测试 ETF 代码在巨潮资讯中的格式
"""

import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from services.data.symbol_resolver import SymbolResolver

def test_etf_code_format():
    """测试 ETF 代码格式"""
    symbol_resolver = SymbolResolver()
    
    etf_codes = ["510300", "158001", "512880", "515050"]
    
    for code in etf_codes:
        print(f"\n测试代码: {code}")
        resolved = symbol_resolver.resolve(code)
        print(f"  解析结果:")
        print(f"    plain_code: {resolved['plain_code']}")
        print(f"    normalized_symbol: {resolved['normalized_symbol']}")
        print(f"    exchange: {resolved['exchange']}")
        print(f"    asset_type: {resolved['asset_type']}")
        print(f"    cninfo_code: {resolved['cninfo_code']}")
        
        # 测试巨潮资讯 API
        try:
            import akshare as ak
            end_date = date.today()
            start_date = end_date - timedelta(days=30)

            # 测试不同的代码格式
            test_codes = [
                resolved["plain_code"],
                resolved["normalized_symbol"],
                resolved["cninfo_code"],
            ]

            for test_code in test_codes:
                print(f"\n  测试巨潮资讯 API (symbol={test_code}):")
                try:
                    df = ak.stock_zh_a_disclosure_report_cninfo(
                        symbol=test_code,
                        market="沪深京",
                        keyword="",
                        category="",
                        start_date=start_date.strftime("%Y%m%d"),
                        end_date=end_date.strftime("%Y%m%d"),
                    )
                    print(f"    结果: {len(df)} 条记录" if not df.empty else f"    结果: 空结果")
                except Exception as e:
                    print(f"    错误: {e}")
        except ImportError:
            print("  警告: 无法导入 akshare")
        except Exception as e:
            print(f"  错误: {e}")

if __name__ == "__main__":
    test_etf_code_format()
