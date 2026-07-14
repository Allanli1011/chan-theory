# -*- coding: utf-8 -*-
"""缠论核心算法单元测试 (pytest)。验证各步骤的几何不变量。"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chanlun.bi import build_bis
from chanlun.cmerge import merge_klines, _included
from chanlun.data import from_dataframe, make_sample
from chanlun.fractal import find_fractals
from chanlun.models import (BSPType, Bi, BuySellPoint, Direction, Fractal,
                            FractalType, RawKLine, Segment, TrendType,
                            ZhongShu)
from chanlun.plot import plot_analysis
from chanlun.segment import build_segments
from chanlun.signals import classify_trend, find_buy_sell_points, find_signals
from chanlun.zhongshu import find_expansions, find_zhongshus
from chanlun.macd import compute_macd, MacdHelper
from chanlun.analyzer import ChanAnalyzer
from scripts.analyze_yahoo_futures import (
    chart_cache_path,
    fetch_chart_cached,
    merge_chart_frames,
    trim_chart_range,
)
from scripts.scan_latest_futures_signals import find_new_signals, signal_code


@pytest.fixture(scope="module")
def sample():
    return make_sample(420, seed=7)


@pytest.fixture(scope="module")
def merged(sample):
    return merge_klines(sample)


@pytest.fixture(scope="module")
def fractals(sample, merged):
    return find_fractals(merged, sample)


@pytest.fixture(scope="module")
def bis(sample, merged, fractals):
    return build_bis(fractals, merged, sample)


# --------------------------------------------------------------------------- #
def test_inclusion_predicate():
    assert _included(10, 5, 9, 6)        # 第二根被第一根包含
    assert _included(9, 6, 10, 5)        # 反向
    assert not _included(10, 5, 12, 8)   # 仅部分重叠, 非包含


def test_merge_removes_inclusion(merged):
    """合并后相邻K线不应再存在包含关系 (课62)。"""
    for a, b in zip(merged, merged[1:]):
        assert not _included(a.high, a.low, b.high, b.low), \
            "存在未消除的包含关系"
    assert all(k.high >= k.low for k in merged)


def test_fractals_are_extrema(fractals, merged):
    """顶分型中心为相邻三者最高, 底分型为最低 (课62)。"""
    for f in fractals:
        a, b, c = merged[f.left_idx], merged[f.m_idx], merged[f.right_idx]
        if f.kind is FractalType.TOP:
            assert b.high > a.high and b.high > c.high
            assert b.low > a.low and b.low > c.low
        else:
            assert b.high < a.high and b.high < c.high
            assert b.low < a.low and b.low < c.low


def test_bis_alternate_and_spacing(bis):
    """笔严格一顶一底交替, 且中心距 >= 4 (标准笔, 课62)。"""
    assert len(bis) >= 3
    for prev, cur in zip(bis, bis[1:]):
        assert prev.direction is not cur.direction      # 方向交替
        assert cur.fx_a is prev.fx_b                     # 首尾相接
    for b in bis:
        assert b.fx_a.kind is not b.fx_b.kind
        assert b.m_end - b.m_start >= 4
        assert b.high > b.low


def test_bis_direction_matches_fractals(bis):
    for b in bis:
        if b.direction is Direction.UP:
            assert b.fx_a.kind is FractalType.BOTTOM and b.fx_b.kind is FractalType.TOP
        else:
            assert b.fx_a.kind is FractalType.TOP and b.fx_b.kind is FractalType.BOTTOM


def test_segments_alternate_and_minlen(bis):
    segs = build_segments(bis)
    assert len(segs) >= 1
    for prev, cur in zip(segs, segs[1:]):
        assert prev.direction is not cur.direction       # 线段方向交替
    # 除可能未完成的末段外, 线段至少三笔
    for s in segs[:-1]:
        assert len(s.bis) >= 3
        assert s.completed
    assert not segs[-1].completed or len(segs[-1].bis) >= 3


def _fx(kind, m_idx, value):
    return Fractal(kind=kind, m_idx=m_idx, high=value, low=value,
                   left_idx=m_idx - 1, right_idx=m_idx + 1,
                   raw_idx=m_idx, dt=m_idx)


def _bi(direction, idx, start_value, end_value):
    if direction is Direction.UP:
        a = _fx(FractalType.BOTTOM, idx * 2, start_value)
        b = _fx(FractalType.TOP, idx * 2 + 1, end_value)
    else:
        a = _fx(FractalType.TOP, idx * 2, start_value)
        b = _fx(FractalType.BOTTOM, idx * 2 + 1, end_value)
    return Bi(direction=direction, fx_a=a, fx_b=b,
              m_start=a.m_idx, m_end=b.m_idx,
              raw_start=a.raw_idx, raw_end=b.raw_idx, idx=idx)


def test_segment_range_uses_internal_bis():
    seg = Segment(Direction.DOWN, [
        _bi(Direction.DOWN, 0, 180, 160),
        _bi(Direction.UP, 1, 160, 198),
        _bi(Direction.DOWN, 2, 198, 124),
        _bi(Direction.UP, 3, 124, 170),
    ])
    assert seg.high == pytest.approx(198)
    assert seg.low == pytest.approx(124)


def test_zhongshu_formula(bis):
    """中枢 ZG=min(成员高), ZD=max(成员低), 且 ZG>ZD (课18)。"""
    zss = find_zhongshus(bis)
    for z in zss:
        assert z.ZG > z.ZD
        assert z.ZG == pytest.approx(min(e.high for e in z.elements))
        assert z.ZD == pytest.approx(max(e.low for e in z.elements))
        assert z.GG >= z.ZG >= z.ZD >= z.DD
        assert len(z.elements) >= 3


def test_zhongshu_same_level_mode_does_not_extend():
    units = [
        _bi(Direction.UP, 0, 0, 10),
        _bi(Direction.DOWN, 1, 9, 1),
        _bi(Direction.UP, 2, 2, 8),
        _bi(Direction.DOWN, 3, 7, 3),
    ]
    extended = find_zhongshus(units, mode="extension")
    same_level = find_zhongshus(units, mode="same_level")
    assert len(extended) == 1
    assert len(extended[0].elements) == 4
    assert len(same_level) == 1
    assert len(same_level[0].elements) == 3


def test_zhongshu_extension_upgrade_at_nine_elements():
    """延伸达9段(3段成枢+6段延伸)标记为更大级别中枢 (课33)。"""
    units = []
    for i in range(10):
        if i % 2 == 0:
            units.append(_bi(Direction.UP, i, 1, 9))
        else:
            units.append(_bi(Direction.DOWN, i, 9, 1))
    zss = find_zhongshus(units, mode="extension")
    assert len(zss) == 1
    assert len(zss[0].elements) == 10
    assert zss[0].upgraded

    short = find_zhongshus(units[:8], mode="extension")
    assert len(short) == 1 and not short[0].upgraded


def test_zhongshu_expansion_merges_overlapping_neighbors():
    """相邻区间重叠的同级别中枢扩展为更高一级中枢 (课29/36)。"""
    def zs(zd, zg, dd, gg, rs, re, idx):
        return ZhongShu(elements=[_bi(Direction.UP, idx, zd, zg)],
                        ZG=zg, ZD=zd, GG=gg, DD=dd,
                        direction=Direction.UP, raw_start=rs, raw_end=re, idx=idx)

    a = zs(10, 12, 9, 13, 0, 5, 0)
    b = zs(11, 14, 10, 15, 6, 10, 1)    # 与 a 区间重叠 -> 扩展
    c = zs(20, 22, 19, 23, 11, 15, 2)   # 与 b 趋势排列 -> 不并入
    exps = find_expansions([a, b, c])
    assert len(exps) == 1
    e = exps[0]
    assert e.expanded
    assert e.elements == [a, b]
    assert e.ZG == pytest.approx(13)    # min(GG)
    assert e.ZD == pytest.approx(10)    # max(DD)
    assert e.GG == pytest.approx(15) and e.DD == pytest.approx(9)
    assert e.raw_start == 0 and e.raw_end == 10
    assert find_expansions([b, c]) == []


def test_macd_shapes(sample):
    close = [r.close for r in sample]
    dif, dea, macd = compute_macd(close)
    assert len(dif) == len(dea) == len(macd) == len(close)
    h = MacdHelper(close)
    red, green = h.area(10, 50)
    assert red >= 0 and green >= 0


def test_macd_and_analyzer_handle_empty_input():
    dif, dea, macd = compute_macd([])
    assert len(dif) == len(dea) == len(macd) == 0
    ana = ChanAnalyzer([]).run()
    assert ana.raws == []
    assert ana.merged == []
    assert ana.bsps == []


def test_classify_trend_logic():
    class FakeZS:
        def __init__(self, zd, zg):
            self.ZD, self.ZG = zd, zg
    # 依次升高且不重叠 -> 上涨
    up = [FakeZS(10, 12), FakeZS(13, 15), FakeZS(16, 18)]
    assert classify_trend(up) is TrendType.UP
    down = [FakeZS(16, 18), FakeZS(13, 15), FakeZS(10, 12)]
    assert classify_trend(down) is TrendType.DOWN
    overlapping_up = [FakeZS(10, 12), FakeZS(11, 13), FakeZS(14, 16)]
    overlapping_down = [FakeZS(14, 16), FakeZS(13, 15), FakeZS(10, 12)]
    assert classify_trend(overlapping_up) is TrendType.CONSOLIDATION
    assert classify_trend(overlapping_down) is TrendType.CONSOLIDATION
    assert classify_trend([FakeZS(10, 12)]) is TrendType.CONSOLIDATION


class FakeMacd:
    def __init__(self, areas):
        self.areas = areas

    def directional_area(self, i0, i1, going_up):
        return self.areas.get((i0, i1, going_up), 0)


def test_single_zhongshu_beichi_is_pz_not_first_class():
    """单一中枢的背驰是盘整背驰, 不构成一类买卖点 (课24/27)。"""
    units = [
        _bi(Direction.DOWN, 0, 10, 5),
        _bi(Direction.UP, 1, 5, 8),
        _bi(Direction.DOWN, 2, 8, 4),
    ]
    macd = FakeMacd({
        (units[0].raw_start, units[0].raw_end, False): 10,
        (units[2].raw_start, units[2].raw_end, False): 4,
    })
    raws = [RawKLine(i, i, 1, 1, 1, 1) for i in range(8)]
    assert find_buy_sell_points(units, [], macd, raws) == []

    zs = ZhongShu(elements=units[:3], ZG=8, ZD=5, GG=10, DD=4,
                  direction=Direction.DOWN, raw_start=0, raw_end=5, idx=0)
    bsps, pzbcs = find_signals(units, [zs], macd, raws)
    assert bsps == []
    assert [b.bsp_type for b in pzbcs] == [BSPType.PZBUY]
    assert pzbcs[0].src_raw_start == units[2].raw_start


def test_trend_beichi_with_two_descending_zhongshus_is_first_class():
    """趋势背驰: 关联中枢前存在依次同向的前中枢 -> 一类买点 (课17/24/27)。"""
    filler = [_bi(Direction.DOWN, 0, 30, 20)]
    z0 = ZhongShu(elements=filler, ZG=26, ZD=20, GG=30, DD=18,
                  direction=Direction.DOWN, raw_start=0, raw_end=5, idx=0)
    units = [
        _bi(Direction.DOWN, 5, 16, 12),   # raw 10..11
        _bi(Direction.UP, 6, 12, 13),     # raw 12..13
        _bi(Direction.DOWN, 7, 13, 9),    # raw 14..15, 创新低且离开 z1
    ]
    z1 = ZhongShu(elements=[units[0]], ZG=14, ZD=10, GG=16, DD=9,
                  direction=Direction.DOWN, raw_start=8, raw_end=13, idx=1)
    macd = FakeMacd({
        (units[0].raw_start, units[0].raw_end, False): 10,
        (units[2].raw_start, units[2].raw_end, False): 4,
    })
    raws = [RawKLine(i, i, 1, 1, 1, 1) for i in range(16)]
    bsps, pzbcs = find_signals(units, [z0, z1], macd, raws)
    assert [b.bsp_type for b in bsps] == [BSPType.BUY1]
    assert pzbcs == []
    assert bsps[0].src_raw_start == units[2].raw_start


def test_third_class_points_scan_first_leave_and_pullback():
    units = [
        _bi(Direction.UP, 0, 0, 10),
        _bi(Direction.DOWN, 1, 10, 2),
        _bi(Direction.UP, 2, 2, 9),
        _bi(Direction.DOWN, 3, 9, 4),   # still inside zhongshu
        _bi(Direction.UP, 4, 4, 13),    # first real leave
        _bi(Direction.DOWN, 5, 13, 11), # first pullback, does not re-enter
    ]
    zs = ZhongShu(elements=units[:3], ZG=9, ZD=2, GG=10, DD=0,
                  direction=Direction.UP, raw_start=0, raw_end=5, idx=0)
    raws = [RawKLine(i, i, 1, 1, 1, 1) for i in range(16)]
    bsps = find_buy_sell_points(units, [zs], FakeMacd({}), raws)
    assert [b.bsp_type for b in bsps] == [BSPType.BUY3]
    assert bsps[0].price > bsps[0].ref_zs_zg
    assert bsps[0].ref_zs_idx == 0
    assert bsps[0].ref_zs_zd == pytest.approx(2)
    assert bsps[0].ref_zs_zg == pytest.approx(9)


def test_third_sell_points_are_below_reference_zhongshu():
    units = [
        _bi(Direction.DOWN, 0, 10, 0),
        _bi(Direction.UP, 1, 0, 8),
        _bi(Direction.DOWN, 2, 8, 1),
        _bi(Direction.UP, 3, 1, 7),     # still inside zhongshu
        _bi(Direction.DOWN, 4, 7, -3),  # first real leave
        _bi(Direction.UP, 5, -3, -1),   # first pullback, does not re-enter
    ]
    zs = ZhongShu(elements=units[:3], ZG=8, ZD=1, GG=10, DD=0,
                  direction=Direction.DOWN, raw_start=0, raw_end=5, idx=0)
    raws = [RawKLine(i, i, 1, 1, 1, 1) for i in range(16)]
    bsps = find_buy_sell_points(units, [zs], FakeMacd({}), raws)

    assert [b.bsp_type for b in bsps] == [BSPType.SELL3]
    assert bsps[0].price < bsps[0].ref_zs_zd
    assert bsps[0].ref_zs_idx == 0
    assert bsps[0].ref_zs_zd == pytest.approx(1)
    assert bsps[0].ref_zs_zg == pytest.approx(8)


def test_end_to_end(sample):
    ana = ChanAnalyzer(sample).run()
    assert len(ana.merged) <= len(ana.raws)
    assert len(ana.bis) >= 3
    assert len(ana.fractals) >= len(ana.bis)
    # 买卖点 raw_idx 落在序列范围内
    for b in ana.bsps + ana.pzbcs + ana.seg_bsps + ana.seg_pzbcs:
        assert 0 <= b.raw_idx < len(ana.raws)
    # 级别标注正确
    assert all(b.level == "bi" for b in ana.bsps + ana.pzbcs)
    assert all(b.level == "seg" for b in ana.seg_bsps + ana.seg_pzbcs)
    # 盘整背驰只含 PZ 类型, 买卖点只含三类
    assert all(b.bsp_type in {BSPType.PZBUY, BSPType.PZSELL} for b in ana.pzbcs)
    assert all(b.bsp_type not in {BSPType.PZBUY, BSPType.PZSELL} for b in ana.bsps)
    # summary 不抛异常
    assert "缠论分析摘要" in ana.summary()
    assert all(s.completed for z in ana.seg_zhongshus for s in z.elements)
    # 扩展中枢几何不变量
    for e in ana.bi_zs_expansions + ana.seg_zs_expansions:
        assert e.expanded and e.ZG > e.ZD and len(e.elements) >= 2


def _load_aapl_daily():
    """AAPL 日线 (仓库自带 data/AAPL.csv, ~1256 根), 用于需要足够长历史
    才能在周线级别产生背驰信号的区间套测试 (420根合成样本重采样到周线
    后仅剩数根笔, 不足以构成背驰上下文)。"""
    import pandas as pd

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "data", "AAPL.csv")
    return pd.read_csv(path)


def test_nest_refine_uses_right_edge_label_window():
    """nest_refine 须按 pandas resample('W'/'ME') 的【右边界】标签语义取窗口:
    粗K线 i 覆盖 (label[i-1], label[i]], 而不是 [label[i], label[i+1])。

    构造: 周线 bar0 覆盖(-inf,01-08], bar1 覆盖(01-08,01-15]; 粗级别背驰段
    [src_raw_start=0, raw_idx=1] 真实覆盖到 01-15 为止。细级别候选 01-05
    落在该范围内应被选中; 01-16 落在下一周(bar2)范围外, 不应被选中。
    若误按左边界处理 (旧实现), 会反过来漏掉01-05、错选01-16。
    """
    import pandas as pd

    from chanlun.analyzer import nest_refine

    class FakeAna:
        def __init__(self, raws, bsps=None, pzbcs=None):
            self.raws = raws
            self.bsps = bsps or []
            self.pzbcs = pzbcs or []

    def rk(i, d):
        return RawKLine(idx=i, dt=pd.Timestamp(d), open=1, high=1, low=1, close=1)

    coarse = FakeAna([rk(0, "2023-01-08"), rk(1, "2023-01-15"), rk(2, "2023-01-22")])
    coarse_bsp = BuySellPoint(BSPType.BUY1, raw_idx=1, dt=pd.Timestamp("2023-01-15"),
                              price=1.0, src_raw_start=0)

    fine_raws = [rk(i, d) for i, d in enumerate(
        ["2023-01-02", "2023-01-05", "2023-01-09", "2023-01-16", "2023-01-20"])]
    fine_in_window = BuySellPoint(BSPType.BUY1, raw_idx=1, dt=pd.Timestamp("2023-01-05"),
                                  price=1.0, src_raw_start=0)
    fine_out_of_window = BuySellPoint(BSPType.BUY1, raw_idx=3, dt=pd.Timestamp("2023-01-16"),
                                      price=1.0, src_raw_start=2)
    fine = FakeAna(fine_raws, bsps=[fine_in_window, fine_out_of_window])

    picked = nest_refine(coarse, fine, coarse_bsp)
    assert picked is fine_in_window


def test_interval_nest_chain_is_time_consistent():
    """区间套 (课27): 细级别背驰点须落在粗级别背驰段【真实覆盖的日期范围】内。

    pandas resample('W') 默认右边界打标签(一周标为该周最后一天), 而非左边界;
    这里显式按该周实际覆盖的日历日校验, 而不仅仅是弱化的下界检查, 用以覆盖
    nest_refine 对右标签重采样数据的窗口计算是否正确 (而不是想当然按左边界处理)。
    """
    from chanlun.analyzer import interval_nest, resample
    import pandas as pd

    df = _load_aapl_daily()
    weekly = resample(df, "W")
    # 粗K线 i 实际覆盖的日历范围 = (前一周标签, 当前周标签]
    week_labels = [pd.Timestamp(d) for d in weekly["date"]]

    recs = interval_nest(df, {"日线": None, "周线": "W"})
    assert isinstance(recs, list)
    assert recs   # AAPL 周线上应产生至少一条链, 否则本测试没有覆盖到目标代码路径
    checked_fine = 0
    for rec in recs:
        chain = rec["chain"]
        assert chain[0][0] == "周线"
        coarse_bsp = rec["bsp"]
        assert coarse_bsp.bsp_type in {BSPType.BUY1, BSPType.SELL1,
                                       BSPType.PZBUY, BSPType.PZSELL}
        if len(chain) > 1:
            name, fine_bsp = chain[1]
            assert name == "日线"
            assert fine_bsp.bsp_type.is_buy == coarse_bsp.bsp_type.is_buy
            # 真实时间一致性: 细级别点须落在粗级别背驰段实际覆盖的周区间内
            lo_i = coarse_bsp.src_raw_start - 1
            lo = week_labels[lo_i] if lo_i >= 0 else None
            hi = week_labels[coarse_bsp.raw_idx]
            fine_dt = pd.Timestamp(fine_bsp.dt)
            if lo is not None:
                assert fine_dt > lo
            assert fine_dt <= hi
            checked_fine += 1
    assert checked_fine > 0


def test_nest_bi_in_seg_api(sample):
    # 级内区间套 API 可用
    ana = ChanAnalyzer(sample).run()
    pairs = ana.nest_bi_in_seg()
    for sb, fb in pairs:
        assert sb.level == "seg"
        if fb is not None:
            assert fb.level == "bi"
            assert sb.src_raw_start <= fb.raw_idx <= sb.raw_idx
            assert fb.bsp_type.is_buy == sb.bsp_type.is_buy


def test_interval_nest_accepts_non_date_column_name():
    """interval_nest 的日期列探测须与 from_dataframe 支持的列名一致
    (date/datetime/time/trade_date), 且探测到的列要真正传给 resample(),
    不能仍旧硬编码 'date' 导致重采样 KeyError。"""
    from chanlun.analyzer import interval_nest

    df = _load_aapl_daily().rename(columns={"date": "datetime"})
    assert "date" not in df.columns
    recs = interval_nest(df, {"日线": None, "周线": "W"})
    assert isinstance(recs, list)
    assert recs


def test_buy_sell_points_have_valid_types(sample):
    ana = ChanAnalyzer(sample).run()
    for b in ana.bsps:
        assert b.bsp_type in set(BSPType)
        assert b.price > 0


def test_from_dataframe_rejects_invalid_ohlc():
    import pandas as pd

    df = pd.DataFrame({
        "date": ["2024-01-01"],
        "open": [1.0],
        "high": [0.5],
        "low": [1.2],
        "close": [1.0],
    })
    with pytest.raises(ValueError, match="high"):
        from_dataframe(df)

    df.loc[0, "high"] = 2.0
    df.loc[0, "close"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        from_dataframe(df)


def test_plot_rejects_empty_window(sample):
    ana = ChanAnalyzer(sample).run()
    with pytest.raises(ValueError, match="empty"):
        plot_analysis(ana, start=10, end=10)


class FakeAnalyzer:
    def __init__(self, raw_count, bsps):
        self.raws = [object()] * raw_count
        self.bsps = bsps


def test_daily_signal_delta_detects_newly_visible_signal():
    previous = FakeAnalyzer(9, [
        BuySellPoint(BSPType.BUY1, 5, "2024-01-05", 100.0),
    ])
    current = FakeAnalyzer(10, [
        BuySellPoint(BSPType.BUY1, 5, "2024-01-05", 100.0),
        BuySellPoint(BSPType.SELL3, 8, "2024-01-08", 110.0),
    ])

    signals = find_new_signals(current, previous, max_signal_age_bars=20)

    assert [signal_code(signal.bsp_type) for signal in signals] == ["3S"]


def test_daily_signal_delta_filters_stale_reclassified_signal():
    previous = FakeAnalyzer(50, [])
    current = FakeAnalyzer(51, [
        BuySellPoint(BSPType.BUY2, 20, "2024-01-20", 90.0),
        BuySellPoint(BSPType.BUY3, 49, "2024-02-18", 96.0),
    ])

    signals = find_new_signals(current, previous, max_signal_age_bars=5)

    assert [signal_code(signal.bsp_type) for signal in signals] == ["3B"]


def test_chart_cache_path_sanitizes_symbol(tmp_path):
    path = chart_cache_path(tmp_path, "ES=F", "5y")

    assert path == tmp_path / "1d" / "5y" / "ES_F.csv"


def test_merge_chart_frames_deduplicates_by_latest_date():
    import pandas as pd

    cached = pd.DataFrame({
        "date": ["2024-01-01", "2024-01-02"],
        "open": [1, 2],
        "high": [2, 3],
        "low": [0, 1],
        "close": [1.5, 2.5],
        "volume": [10, 20],
    })
    recent = pd.DataFrame({
        "date": ["2024-01-02", "2024-01-03"],
        "open": [22, 3],
        "high": [23, 4],
        "low": [21, 2],
        "close": [22.5, 3.5],
        "volume": [220, 30],
    })

    merged = merge_chart_frames(cached, recent)

    assert list(merged["date"]) == ["2024-01-01", "2024-01-02", "2024-01-03"]
    assert merged.loc[merged["date"] == "2024-01-02", "open"].item() == 22


def test_trim_chart_range_keeps_recent_window():
    import pandas as pd

    df = pd.DataFrame({
        "date": ["2022-01-01", "2023-01-01", "2024-01-01"],
        "open": [1, 2, 3],
        "high": [1, 2, 3],
        "low": [1, 2, 3],
        "close": [1, 2, 3],
        "volume": [1, 2, 3],
    })

    trimmed = trim_chart_range(df, "1y")

    assert list(trimmed["date"]) == ["2023-01-01", "2024-01-01"]


def test_fetch_chart_cached_refreshes_recent_data(tmp_path, monkeypatch):
    import pandas as pd
    import scripts.analyze_yahoo_futures as futures

    calls = []

    def fake_fetch(session, symbol, range_, timeout):
        calls.append((symbol, range_))
        if range_ == "5y":
            return pd.DataFrame({
                "date": ["2024-01-01", "2024-01-02"],
                "open": [1, 2],
                "high": [2, 3],
                "low": [0, 1],
                "close": [1.5, 2.5],
                "volume": [10, 20],
            })
        return pd.DataFrame({
            "date": ["2024-01-02", "2024-01-03"],
            "open": [22, 3],
            "high": [23, 4],
            "low": [21, 2],
            "close": [22.5, 3.5],
            "volume": [220, 30],
        })

    monkeypatch.setattr(futures, "fetch_chart", fake_fetch)

    first = fetch_chart_cached(None, "ES=F", "5y", 1,
                               cache_dir=tmp_path, refresh_range="10d")
    second = fetch_chart_cached(None, "ES=F", "5y", 1,
                                cache_dir=tmp_path, refresh_range="10d")

    assert calls == [("ES=F", "5y"), ("ES=F", "10d")]
    assert list(first["date"]) == ["2024-01-01", "2024-01-02"]
    assert list(second["date"]) == ["2024-01-01", "2024-01-02", "2024-01-03"]
    assert second.loc[second["date"] == "2024-01-02", "open"].item() == 22
