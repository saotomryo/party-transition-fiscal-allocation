import pandas as pd
from finance import changes,peers,METRICS

def panel():
    d=pd.DataFrame({'code':['011002']*3,'fiscal_year':[2020,2021,2023],'population':[100]*3,'fiscal_strength':[.7]*3,'municipality_type':['1']*3})
    for m in METRICS:d[m]=[0,100,200]
    return d

def test_gap_and_zero():
    d=changes(panel())
    assert pd.isna(d.iloc[1].allocation_tax_pct)
    assert d.iloc[1].allocation_tax_change==100
    assert pd.isna(d.iloc[2].allocation_tax_change)

def test_rate():
    d=panel().iloc[:2].copy()
    for m in METRICS:d[m]=[100,150]
    assert changes(d).iloc[1].allocation_tax_pct==50

def test_peer_exclusion():
    d=panel().iloc[:1].copy();other=d.copy();other['code']='012025'
    assert list(peers(pd.concat([d,other]),'011002',2020,'allocation_tax').code)==['012025']

def test_official_panel():
    from finance import ROOT
    d=pd.read_parquet(ROOT/'data/panel.parquet')
    assert len(d)==17410
    assert d.groupby('fiscal_year').size().eq(1741).all()
    assert not d.duplicated(['code','fiscal_year']).any()
    assert d.code.str.fullmatch(r'\d{6}').all()
    assert d.population.gt(0).all()
    assert d[(d.code=='011002')&(d.fiscal_year==2024)].fiscal_strength.iloc[0]==.7
    assert '012025' in set(d.code) # core city must not be omitted
    assert d.groupby('fiscal_year').allocation_tax_pct.count().iloc[0]==0

def test_streamlit():
    from finance import ROOT
    from streamlit.testing.v1 import AppTest
    a=AppTest.from_file(str(ROOT/'municipality_view.py'),default_timeout=30).run()
    assert not a.exception
    a.sidebar.slider[0].set_value(60).run()
    assert not a.exception
    a.main.selectbox[0].select_index(10).run()
    a.sidebar.selectbox[0].set_value('special_tax').run()
    a.sidebar.selectbox[1].set_value(2015).run()
    assert not a.exception
