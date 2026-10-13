import pandas as pd
from elections import fiscal_phase, rank_changes, match_municipality, event_comparison

def test_fiscal_phase():
    assert fiscal_phase(2021,'2021-10-31')=='選挙実施年度'
    assert fiscal_phase(2022,'2021-10-31')=='選挙後の通年年度'
    assert fiscal_phase(2020,'2021-10-31')=='選挙前の通年年度'
    assert fiscal_phase(2024,'2024-10-27')=='選挙実施年度'

def test_match_split_city_and_ambiguity():
    ref=pd.DataFrame({'code':['011002','010101','010102'],'prefecture':['北海道']*3,'municipality':['札幌市','同名町','同名町']})
    assert match_municipality('札幌市北区第１区','北海道',ref)==('011002','政令市の行政区・一部地域を市に集約')
    assert match_municipality('同名町','北海道',ref)[0] is None

def test_rank_absolute_rate_and_amount():
    d=pd.DataFrame({'x_pct':[-100,200,None],'x_change':[1,2,100]})
    assert list(rank_changes(d,'x',30,0).index)==[1,0]
    assert list(rank_changes(d,'x',30,1.5).index)==[1]

def test_event_compare_does_not_use_election_year_as_after():
    d=pd.DataFrame({'code':['a']*3,'fiscal_year':[2020,2021,2022],'allocation_tax':[100,900,120]})
    result=event_comparison(d,'a','2021-10-31','allocation_tax')
    assert result['before_year']==2020 and result['after_year']==2022
    assert result['pct']==20

def test_future_after_is_missing():
    d=pd.DataFrame({'code':['a'],'fiscal_year':[2024],'allocation_tax':[100]})
    assert event_comparison(d,'a','2024-10-27','allocation_tax')['status']=='選挙前後の通年データ不足'

def test_official_election_counts_and_split_mapping():
    from finance import ROOT
    ds=pd.read_parquet(ROOT/'data/elections/election_districts.parquet')
    assert ds.groupby('kaiji').size().to_dict()=={47:295,48:289,49:289,50:289}
    assert not ds.duplicated(['kaiji','district']).any()
    mappings=pd.read_parquet(ROOT/'data/elections/municipality_districts.parquet')
    assert mappings[mappings.kaiji.eq(50)].code.nunique()==1741
    assert mappings[mappings.code.eq('011002')&mappings.kaiji.eq(50)].district.nunique()>1
    # 落合姓 must not be confused with the 当落 header in official PDFs.
    tokyo=ds[ds.district.eq('東京都第6区')&ds.kaiji.isin([49,50])]
    assert len(tokyo)==2 and tokyo.winner_verification.eq('公式当選表示・得票と一致').all()
    fukui=ds[ds.district.eq('福井県第1区')&ds.kaiji.eq(48)]
    assert fukui.vote_sum_status.str.contains('不一致').all()
    aichi=ds[ds.district.eq('愛知県第11区')&ds.kaiji.eq(47)]
    assert aichi.certified_votes.iloc[0]==126498
    osaka=ds[ds.district.eq('大阪府第19区')&ds.kaiji.eq(49)]
    assert osaka.certified_votes.iloc[0]==68209 and osaka.leading_votes.iloc[0]==13295
    assert osaka.winner_verification.str.contains('不一致').all()

def test_election_ui_data_gap_and_year_switch():
    from finance import ROOT
    from streamlit.testing.v1 import AppTest
    a=AppTest.from_file(str(ROOT/'municipality_view.py'),default_timeout=30).run()
    assert not a.exception
    assert any('選挙後の通年決算がない' in w.value for w in a.warning)
    a.main.selectbox[1].set_value(49).run()
    assert not a.exception
    assert not any('選挙後の通年決算がない' in w.value for w in a.warning)
    next(r for r in a.radio if r.label=='自治体の選択範囲').set_value('全自治体から選ぶ').run()
    a.main.selectbox[0].set_value('011002').run()
    assert not a.exception
    assert any('複数の小選挙区' in v.value for v in a.info)
