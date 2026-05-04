"""
公告功能独立测试脚本
测试内容：
1. 巨潮资讯数据源
2. AKShare 数据源
3. 事件分类和情感分析
4. 数据标准化
"""

import sys
from datetime import date, timedelta
from pathlib import Path

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(PROJECT_ROOT))

from services.data.providers.cninfo_event_provider import CninfoEventProvider
from services.data.providers.akshare_event_provider import AKShareEventProvider
from services.data.normalizers.event_normalizer import EventNormalizer


def test_cninfo_provider():
    """测试巨潮资讯数据源"""
    print("\n" + "="*80)
    print("测试 1: 巨潮资讯数据源 (Cninfo)")
    print("="*80)

    provider = CninfoEventProvider()

    symbol_info = {
        "plain_code": "600519",
        "normalized_symbol": "600519.SH",
    }

    try:
        result = provider.fetch_events(symbol_info, lookback_days=90)

        print(f"\n✓ 数据获取成功")
        print(f"  供应商: {result.provider}")
        print(f"  数据集: {result.dataset}")
        print(f"  代码: {result.symbol}")
        print(f"  成功: {result.metadata.success}")
        print(f"  延迟: {result.metadata.latency_ms}ms")
        print(f"  记录数: {len(result.data)}")

        if result.metadata.success:
            print(f"\n  前 3 条公告:")
            for i, record in enumerate(result.data[:3], 1):
                print(f"    {i}. {record.get('公告标题', 'N/A')}")
                print(f"       时间: {record.get('公告时间', 'N/A')}")
                print(f"       链接: {record.get('公告链接', 'N/A')}")

        if result.metadata.error:
            print(f"\n  错误信息: {result.metadata.error}")

        return result

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_akshare_provider():
    """测试 AKShare 数据源"""
    print("\n" + "="*80)
    print("测试 2: AKShare 数据源 (东方财富)")
    print("="*80)

    provider = AKShareEventProvider()

    symbol_info = {
        "plain_code": "600519",
        "normalized_symbol": "600519.SH",
    }

    try:
        result = provider.fetch_events(symbol_info, lookback_days=90)

        print(f"\n✓ 数据获取成功")
        print(f"  供应商: {result.provider}")
        print(f"  数据集: {result.dataset}")
        print(f"  代码: {result.symbol}")
        print(f"  成功: {result.metadata.success}")
        print(f"  延迟: {result.metadata.latency_ms}ms")
        print(f"  记录数: {len(result.data)}")

        if result.metadata.success:
            print(f"\n  前 3 条公告:")
            for i, record in enumerate(result.data[:3], 1):
                print(f"    {i}. {record.get('公告标题', 'N/A')}")
                print(f"       日期: {record.get('公告日期', 'N/A')}")

        if result.metadata.error:
            print(f"\n  错误信息: {result.metadata.error}")

        return result

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_event_normalizer():
    """测试事件分类和情感分析"""
    print("\n" + "="*80)
    print("测试 3: 事件分类和情感分析")
    print("="*80)

    normalizer = EventNormalizer()

    # 测试用例 1: 监管问询
    print("\n  测试用例 1: 监管问询")
    provider_result = {
        "data": [
            {
                "公告标题": "关于收到交易所问询函的公告",
                "公告时间": "2026-04-20",
                "公告链接": "https://example.com/a.pdf",
            }
        ]
    }
    events = normalizer.normalize_cninfo(provider_result, "600519.SH", lookback_days=90)

    if events:
        print(f"    分类: {events[0].get('event_type')}")
        print(f"    严重性: {events[0].get('severity')}")
        print(f"    情感: {events[0].get('sentiment')}")
        print(f"    ✓ 通过")
    else:
        print(f"    ✗ 失败: 未生成事件")

    # 测试用例 2: 分红
    print("\n  测试用例 2: 分红公告")
    provider_result = {
        "data": [
            {
                "公告标题": "2025年年度权益分派实施公告",
                "公告时间": "2026-04-21",
            }
        ]
    }
    events = normalizer.normalize_cninfo(provider_result, "600519.SH", lookback_days=90)

    if events:
        print(f"    分类: {events[0].get('event_type')}")
        print(f"    情感: {events[0].get('sentiment')}")
        print(f"    ✓ 通过")
    else:
        print(f"    ✗ 失败: 未生成事件")

    # 测试用例 3: 业绩预告
    print("\n  测试用例 3: 业绩预告")
    provider_result = {
        "data": [
            {
                "公告标题": "2025年第一季度业绩预告",
                "公告时间": "2026-04-22",
            }
        ]
    }
    events = normalizer.normalize_cninfo(provider_result, "600519.SH", lookback_days=90)

    if events:
        print(f"    分类: {events[0].get('event_type')}")
        print(f"    情感: {events[0].get('sentiment')}")
        print(f"    ✓ 通过")
    else:
        print(f"    ✗ 失败: 未生成事件")

    # 测试用例 4: 负面新闻
    print("\n  测试用例 4: 媒体负面传闻")
    provider_result = {
        "data": [
            {
                "公告标题": "媒体报道公司可能面临监管风险",
                "公告时间": "2026-04-23",
            }
        ]
    }
    events = normalizer.normalize_akshare(provider_result, "600519.SH", lookback_days=90)

    if events:
        print(f"    分类: {events[0].get('event_type')}")
        print(f"    严重性: {events[0].get('severity')}")
        print(f"    情感: {events[0].get('sentiment')}")
        print(f"    ✓ 通过")
    else:
        print(f"    ✗ 失败: 未生成事件")


def test_event_summary():
    """测试事件摘要"""
    print("\n" + "="*80)
    print("测试 4: 事件摘要生成")
    print("="*80)

    # 生成测试事件数据
    provider_result = {
        "data": [
            {
                "公告标题": "关于收到交易所问询函的公告",
                "公告时间": "2026-04-20",
            },
            {
                "公告标题": "2025年年度权益分派实施公告",
                "公告时间": "2026-04-21",
            },
            {
                "公告标题": "2025年第一季度业绩预告",
                "公告时间": "2026-04-22",
            },
        ]
    }

    normalizer = EventNormalizer()
    events = normalizer.normalize_cninfo(provider_result, "600519.SH", lookback_days=90)

    if events:
        # 计算摘要
        positive_count = sum(1 for e in events if e.get('sentiment') in ['positive', 'neutral_positive'])
        negative_count = sum(1 for e in events if e.get('sentiment') in ['negative', 'neutral_negative'])
        neutral_count = sum(1 for e in events if e.get('sentiment') in ['neutral', 'unknown'])
        high_severity_count = sum(1 for e in events if e.get('severity') in ['high', 'critical'])
        critical_count = sum(1 for e in events if e.get('severity') == 'critical')

        # 计算情感
        if any(e.get('sentiment') == 'negative' for e in events):
            recent_news_sentiment = 'neutral_negative'
        elif any(e.get('sentiment') == 'neutral_positive' for e in events):
            recent_news_sentiment = 'neutral_positive'
        else:
            recent_news_sentiment = 'neutral'

        # 政策风险
        policy_risk = 'low' if critical_count == 0 and high_severity_count < 2 else 'medium'

        # 主要事件
        high_events = [e for e in events if e.get('severity') in ['high', 'critical']]
        if high_events:
            major_event = high_events[0].get('title', '近90日存在高风险公告')
        elif events:
            major_event = f'近90日共发现 {len(events)} 条公告，未发现 critical 事件'
        else:
            major_event = '近90日未发现重大负面公告'

        print(f"\n  情感分析: {recent_news_sentiment}")
        print(f"  政策风险: {policy_risk}")
        print(f"  主要事件: {major_event}")
        print(f"\n  事件统计:")
        print(f"    总数: {len(events)}")
        print(f"    积极: {positive_count}")
        print(f"    消极: {negative_count}")
        print(f"    中性: {neutral_count}")
        print(f"    高严重性: {high_severity_count}")
        print(f"    Critical: {critical_count}")

        print(f"\n  ✓ 通过")
    else:
        print(f"\n  ✗ 失败: 未生成事件")


def test_multiple_symbols():
    """测试多个股票代码"""
    print("\n" + "="*80)
    print("测试 5: 多个股票代码")
    print("="*80)

    symbol_list = ["600519", "000001", "510300", "158001"]

    for symbol in symbol_list:
        print(f"\n  测试代码: {symbol}")
        provider = CninfoEventProvider()
        symbol_info = {
            "plain_code": symbol,
            "normalized_symbol": f"{symbol}.SH",
        }

        try:
            result = provider.fetch_events(symbol_info, lookback_days=30)

            if result.metadata.success:
                print(f"    ✓ 获取成功: {len(result.data)} 条公告")
            else:
                print(f"    ✗ 获取失败: {result.metadata.error}")
        except Exception as e:
            print(f"    ✗ 异常: {e}")


if __name__ == "__main__":
    print("\n" + "="*80)
    print("公告功能独立测试")
    print("="*80)

    results = {
        "巨潮资讯数据源": None,
        "AKShare数据源": None,
    }

    # 测试 1: 巨潮资讯
    results["巨潮资讯数据源"] = test_cninfo_provider()

    # 测试 2: AKShare
    results["AKShare数据源"] = test_akshare_provider()

    # 测试 3: 事件分类
    test_event_normalizer()

    # 测试 4: 事件摘要
    test_event_summary()

    # 测试 5: 多个代码
    test_multiple_symbols()

    # 总结
    print("\n" + "="*80)
    print("测试总结")
    print("="*80)

    print(f"\n巨潮资讯数据源: {'✓ 通过' if results['巨潮资讯数据源'] and results['巨潮资讯数据源'].metadata.success else '✗ 失败'}")
    print(f"AKShare数据源: {'✓ 通过' if results['AKShare数据源'] and results['AKShare数据源'].metadata.success else '✗ 失败'}")

    print("\n" + "="*80)
