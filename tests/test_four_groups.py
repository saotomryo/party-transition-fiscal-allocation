import pandas as pd
import numpy as np
from analysis_view import four_group_amounts,GROUPS

def test_four_groups_average_same_municipalities_and_keep_missing_groups():
    panel=pd.DataFrame({'code':['a','a','b','b','c'], 'fiscal_year':[2020,2022,2020,2022,2020], 'population':[10,10,100,100,10], 'x':[100,80,2000,2400,100]})
    cohort=pd.DataFrame({'code':['a','b','c'],'election_year':[2021]*3,'eligible':[True]*3,'transition':[GROUPS[0]]*3})
    out=four_group_amounts(panel,cohort,2021,1,'x')
    assert out['区分'].tolist()==GROUPS
    assert out.iloc[0]['自治体数']==2
    assert out.iloc[0]['選挙前（円／人）']==15
    assert out.iloc[0]['選挙後（円／人）']==16
    assert out.iloc[0]['全体傾向']=='増加'
    assert np.isclose(out.iloc[0]['変化率（参考・%）'],100/15)
    assert out.iloc[1]['全体傾向']=='対象なし'
    assert pd.isna(out.iloc[1]['増減額（円／人）'])

def test_zero_baseline_has_no_percentage():
    panel=pd.DataFrame({'code':['a','a'],'fiscal_year':[2020,2022],'population':[10,10],'x':[0,10]})
    cohort=pd.DataFrame({'code':['a'],'election_year':[2021],'eligible':[True],'transition':[GROUPS[1]]})
    out=four_group_amounts(panel,cohort,2021,1,'x')
    assert out.iloc[1]['増減額（円／人）']==1
    assert pd.isna(out.iloc[1]['変化率（参考・%）'])
