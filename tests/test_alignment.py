import numpy as np
import pandas as pd
from alignment import affiliation,transition,cluster_ols,bh_adjust,aggregate_window

def test_affiliation_is_date_scoped_and_independent_is_unknown():
    assert affiliation('自由民主党','2017-10-22')=='与党'
    assert affiliation('公明党','2021-10-31')=='与党'
    assert affiliation('日本維新の会','2021-10-31')=='野党'
    assert affiliation('無所属','2021-10-31')=='未判別'
    assert affiliation('自由民主党','2026-10-13')=='未判別'

def test_transition_unknown_not_opposition():
    assert transition('与党','野党')=='与党→野党'
    assert transition('未判別','与党')=='未判別'

def test_cluster_regression_recovers_known_difference():
    rng=np.random.default_rng(4);n=200
    d=pd.DataFrame({'treated':np.repeat([0,1],n//2),'cluster':np.repeat(np.arange(40),5)})
    d['population_pre']=rng.uniform(1000,10000,n);d['strength_pre']=rng.uniform(.2,.8,n)
    d['prefecture']='同県';d['municipality_type']='5'
    d['change']=20+5*d.treated+2*np.log(d.population_pre)+rng.normal(0,.2,n)
    r=cluster_ols(d,'change')
    assert abs(r['estimate']-5)<.2
    assert r['cluster_count']==40 and r['se']>0

def test_clusters_not_rows_define_uncertainty():
    rng=np.random.default_rng(2)
    d=pd.DataFrame({'treated':np.repeat([0,1],20),'cluster':np.repeat(np.arange(8),5),'population_pre':1000,'strength_pre':.5,'prefecture':'A','municipality_type':'5','change':rng.normal(0,1,40)})
    r=cluster_ols(d,'change');assert r['cluster_count']==8 and r['treated_clusters']==4
    assert r['small_sample']

def test_bh_multiple_testing():
    assert np.allclose(bh_adjust([.01,.04,.03]),[.03,.04,.04])

def test_missing_year_not_silently_averaged():
    d=pd.DataFrame({'code':['a','a','b'],'fiscal_year':[2015,2016,2015],'population':[100]*3,'x':[100,200,100]})
    w=aggregate_window(d,[2015,2016],'x');assert list(w.code)==['a']
    assert w.outcome.iloc[0]==1.5

def test_real_cohorts_have_auditable_exclusions():
    from finance import ROOT
    c=pd.read_parquet(ROOT/'data/analysis/alignment_cohorts.parquet')
    assert len(c)==3482 and not c.duplicated(['code','election_year']).any()
    assert c[c.eligible].transition.ne('未判別').all()
    assert c[~c.eligible].exclusion_reason.ne('').all()
    assert not ((c.code=='011002')&c.eligible).any()
    r=pd.read_parquet(ROOT/'data/analysis/alignment_estimates.parquet')
    one=r[(r.election_year==2017)&r.contrast.eq('野党→与党')]
    assert one.status.eq('推定不可').all() and one.estimate.isna().all()

def test_official_component_no_double_counting():
    from finance import ROOT,read_finance,column
    p=pd.read_parquet(ROOT/'data/analysis/grant_components.parquet')
    raw=read_finance((ROOT/'data/raw/2022-revenue.csv').read_bytes());row=raw[raw.code.eq('011002') & pd.to_numeric(raw['行番号']).eq(1)]
    expected=(column(row,'新型コロナウイルス感染症対応地方創生臨時交付金')+column(row,'その他新型コロナウイルス感染症対策関係交付金等')).iloc[0]*1000
    assert p[(p.code=='011002')&(p.fiscal_year==2022)].identified_covid_grants.iloc[0]==expected
    assert p[p.fiscal_year.lt(2020)].identified_covid_grants.eq(0).all()

def test_all_real_models_match_statsmodels():
    import statsmodels.api as sm
    from statsmodels.stats.sandwich_covariance import cov_cluster
    from finance import ROOT
    from alignment import design_matrix
    samples=pd.read_parquet(ROOT/'data/analysis/alignment_samples.parquet')
    for _,d in samples.groupby(['election_year','window','metric','contrast']):
        x,_=design_matrix(d);fit=sm.OLS(d.change.to_numpy(),x).fit();cov=cov_cluster(fit,d.cluster.to_numpy(),use_correction=True)
        ours=cluster_ols(d,'change')
        assert np.isclose(ours['estimate'],fit.params[1],atol=1e-5,rtol=1e-9)
        assert np.isclose(ours['se'],np.sqrt(cov[1,1]),atol=1e-4,rtol=1e-8)

def test_new_ui_period_change_and_insufficient_case():
    from finance import ROOT
    from streamlit.testing.v1 import AppTest
    a=AppTest.from_file(str(ROOT/'app.py'),default_timeout=30).run()
    assert not a.exception
    assert any('期中の党籍' in w.value for w in a.warning)
    a.main.selectbox[2].set_value('national_grants_adjusted').run()
    assert not a.exception
    a.main.selectbox[0].set_value(2017).run()
    a.main.selectbox[1].set_value('野党→与党').run()
    assert not a.exception and any('推定値を算出していません' in e.value for e in a.error)
