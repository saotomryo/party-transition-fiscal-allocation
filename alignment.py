"""Exploratory election-cohort fiscal comparisons, with auditable exclusions.

Election-day party observations are NOT continuous MP affiliation histories.
Estimates are adjusted associations; actual budget decisions and confounders
are not fully observed. Never interpret the result as political intervention.
"""
from datetime import date
import json
import numpy as np
import pandas as pd
import duckdb
from scipy import stats
from finance import ROOT,read_finance,column

COALITION={'start':'2012-12-26','end_exclusive':'2024-04-01','period_kind':'本分析の確認対象期間（連立終了日ではない）','parties':['自由民主党','公明党'],
'sources':['https://www.komei.or.jp/news/detail/20121226_9916','https://www.komei.or.jp/news/detail/20171102_26181','https://www.komei.or.jp/komeinews/p120939/','https://www.jimin.jp/news/press/202278.html','https://www.komei.or.jp/about/history/']}
OPPOSITION={'民主党','次世代の党','生活の党','維新の党','希望の党','立憲民主党','日本維新の会','国民民主党','社会民主党','日本共産党'}
OUTCOMES={'national_grants':'国庫支出金','special_tax':'特別交付税','ordinary_tax':'普通交付税（制度算定の比較用）','national_grants_adjusted':'国庫支出金（確認できたコロナ・災害復旧交付金控除）'}
CONTRASTS={'与党→野党':'与党→与党','野党→与党':'野党→野党'}
CAVEATS=['前回・今回の総選挙の当選時党派を比較。期中の離党・党籍変更・補選・比例復活は未反映。',
'選挙区の自治体構成が同じことを確認した範囲。地理的境界の完全照合は未実施。',
'人口・財政力指数・都道府県・団体区分を調整するが、災害の全容、年齢構成、申請額、採択率等は未調整。',
'人口1人当たりの名目円。自治体を等しく重み付け。全国の共通変動は継続群との差で比較。',
'コロナ・災害控除は確認できた国庫支出金の内訳に限る。関連支出すべてを除外するものではない。',
'95%区間は各推定の区間で同時信頼区間ではない。主分析の複数比較はBH法で補正。',
'事前傾向に差を検出しなくても平行トレンドは証明されない。因果効果・政治的介入・個人の影響力は結論しない。']

def affiliation(party,observed_date):
    if not COALITION['start']<=observed_date<COALITION['end_exclusive']:return '未判別'
    if party in COALITION['parties']:return '与党'
    if party in OPPOSITION:return '野党'
    return '未判別'

def transition(before,after):
    return f'{before}→{after}' if before in ['与党','野党'] and after in ['与党','野党'] else '未判別'

def cohorts(panel,links,winners):
    result=[]
    observations=winners.copy()
    observations['alignment']=observations.apply(lambda r:affiliation(r.certified_party,r.election_date),axis=1)
    for previous,current,year in [(47,48,2017),(48,49,2021)]:
        base=panel[panel.fiscal_year.eq(year)][['code','prefecture','municipality','municipality_type']].drop_duplicates('code')
        maps={};signatures={};unknown={}
        for kaiji in [previous,current]:
            m=links[links.kaiji.eq(kaiji)]
            maps[kaiji]={code:sorted(set(g.district)) for code,g in m.dropna(subset=['code']).groupby('code')}
            signatures[kaiji]={district:frozenset(g.code.dropna()) for district,g in m.groupby('district')}
            unknown[kaiji]={district:g.code.isna().any() for district,g in m.groupby('district')}
        win=observations.set_index(['kaiji','district'])
        for _,municipality in base.iterrows():
            row=municipality.to_dict();row.update(election_year=year,kaiji=current,previous_kaiji=previous,exclusion_reason='',transition='未判別',district_before=None,district_after=None,before_party=None,after_party=None,before_candidate=None,after_candidate=None)
            before=maps[previous].get(row['code'],[]);after=maps[current].get(row['code'],[])
            if not before or not after:row['exclusion_reason']='自治体・選挙区対応未確認'
            elif len(before)!=1 or len(after)!=1:row['exclusion_reason']='複数小選挙区の自治体'
            else:
                b,a=before[0],after[0];row.update(district_before=b,district_after=a)
                rb,ra=win.loc[(previous,b)],win.loc[(current,a)]
                row.update(before_party=rb.certified_party,after_party=ra.certified_party,before_candidate=rb.certified_candidate,after_candidate=ra.certified_candidate,
                           before_source=rb.certified_source_url,after_source=ra.certified_source_url)
                row['transition']=transition(rb.alignment,ra.alignment)
                if unknown[previous][b] or unknown[current][a]:row['exclusion_reason']='同じ選挙区に名称対応未確認の地域あり'
                elif b!=a or signatures[previous][b]!=signatures[current][a]:row['exclusion_reason']='選挙区の自治体構成変更・区割り未対応'
                elif row['transition']=='未判別':row['exclusion_reason']='無所属等の政権関係未判別'
            row['eligible']=not bool(row['exclusion_reason'])
            row['cluster']=row['district_after']
            row['affiliation_basis']='総選挙当選時の党派観測（期中の党籍未確認）'
            result.append(row)
    return pd.DataFrame(result),observations

def components(panel):
    rows=[]
    covid_labels=['新型コロナウイルス感染症対応地方創生臨時交付金','その他新型コロナウイルス感染症対策関係交付金等']
    for year in sorted(panel.fiscal_year.unique()):
        raw=read_finance((ROOT/f'data/raw/{year}-revenue.csv').read_bytes())
        raw=raw[pd.to_numeric(raw['行番号']).eq(1)]
        out=raw[['code','fiscal_year']].copy()
        out['identified_covid_grants']=0.0
        for label in covid_labels:
            if year>=2020:out['identified_covid_grants']+=column(raw,label)
        out['disaster_recovery_grants']=column(raw,'災害復旧事業費支出金')
        out[['identified_covid_grants','disaster_recovery_grants']]*=1000
        out['component_status']='コロナ項目は制度対象前' if year<2020 else '公開表の指定親項目を取得（全関連支出ではない）'
        rows.append(out)
    parts=pd.concat(rows,ignore_index=True)
    d=panel.merge(parts,on=['code','fiscal_year'],how='left',validate='one_to_one')
    d['national_grants_adjusted']=d.national_grants-d.identified_covid_grants-d.disaster_recovery_grants
    if d.national_grants_adjusted.lt(-1).any():raise ValueError('Component totals exceed national grants')
    return d,parts

def aggregate_window(panel,years,metric):
    d=panel[panel.fiscal_year.isin(years)].copy()
    if d.duplicated(['code','fiscal_year']).any():raise ValueError('Duplicate municipality/year')
    d['outcome']=d[metric]/d.population.where(d.population.gt(0))
    grouped=d.groupby('code').agg(outcome=('outcome','mean'),valid_years=('outcome','count'),population=('population','mean'))
    return grouped[grouped.valid_years.eq(len(years))].reset_index()

def design_matrix(d):
    x=pd.DataFrame({'constant':np.ones(len(d)),'treated':d.treated.to_numpy(),'log_population':np.log(d.population_pre.to_numpy()),'fiscal_strength':d.strength_pre.to_numpy()},index=d.index)
    categorical=pd.get_dummies(d[['prefecture','municipality_type']].astype(str),drop_first=True,dtype=float)
    x=pd.concat([x,categorical],axis=1)
    keep=['constant','treated']+[c for c in x if c not in ['constant','treated'] and x[c].std()>1e-12]
    full=x[keep].to_numpy(dtype=float)
    others=np.delete(full,1,axis=1)
    remaining=full[:,1]-others@np.linalg.lstsq(others,full[:,1],rcond=None)[0]
    if np.linalg.norm(remaining)<1e-8:raise ValueError('Treatment indistinguishable from regional controls')
    # Keep the intercept and treatment; remove redundant nuisance columns.
    # A full-rank design gives an unambiguous coefficient and CR1 correction.
    indices=[];orthogonal=[]
    for j in range(full.shape[1]):
        vector=full[:,j].copy()
        for _ in range(2):
            for basis in orthogonal:vector-=basis*np.dot(basis,vector)
        norm=np.linalg.norm(vector)
        if norm>1e-10*max(np.linalg.norm(full[:,j]),1):
            indices.append(j);orthogonal.append(vector/norm)
    return full[:,indices],[keep[j] for j in indices]

def cluster_ols(d,outcome):
    if d.treated.nunique()!=2:raise ValueError('Both treated and control groups are required')
    x,names=design_matrix(d);y=d[outcome].to_numpy(dtype=float)
    if not np.isfinite(x).all() or not np.isfinite(y).all():raise ValueError('Non-finite regression input')
    n=len(d);rank=np.linalg.matrix_rank(x);clusters=d.cluster.to_numpy();unique=np.unique(clusters);g=len(unique)
    if g<3 or n<=rank:raise ValueError('Too few independent districts or residual degrees of freedom')
    other=np.delete(x,1,axis=1)
    residual_t=x[:,1]-other@np.linalg.lstsq(other,x[:,1],rcond=None)[0]
    if np.linalg.norm(residual_t)<1e-8:raise ValueError('Treatment indistinguishable from regional controls')
    coef=np.linalg.lstsq(x,y,rcond=None)[0];residual=y-x@coef;bread=np.linalg.pinv(x.T@x)
    scores=np.vstack([x[clusters==cluster].T@residual[clusters==cluster] for cluster in unique])
    cov=bread@(scores.T@scores)@bread*(g/(g-1))*((n-1)/(n-rank))
    se=float(np.sqrt(max(cov[1,1],0)));estimate=float(coef[1]);critical=float(stats.t.ppf(.975,g-1))
    treated_g=d[d.treated.eq(1)].cluster.nunique();control_g=d[d.treated.eq(0)].cluster.nunique()
    if min(treated_g,control_g)<3:raise ValueError('比較する片側の独立選挙区が3未満のため不確実性を推定しない')
    p=float(2*stats.t.sf(abs(estimate/se),g-1)) if se>0 else None
    return {'estimate':estimate,'se':se,'ci_low':estimate-critical*se,'ci_high':estimate+critical*se,'p_value':p,
            'municipality_count':n,'treated_count':int(d.treated.sum()),'control_count':int((1-d.treated).sum()),'cluster_count':g,
            'treated_clusters':treated_g,'control_clusters':control_g,'small_sample':min(treated_g,control_g)<10,
            'design_rank':rank,'design_columns':len(names)}

def bh_adjust(values):
    p=np.asarray(values,dtype=float);out=np.full(len(p),np.nan);valid=np.where(np.isfinite(p))[0]
    order=valid[np.argsort(p[valid])];q=p[order]*len(valid)/np.arange(1,len(valid)+1)
    out[order]=np.minimum(1,np.minimum.accumulate(q[::-1])[::-1]);return out

def analysis_sample(panel,cohort,year,width,metric,target,control):
    pre=list(range(year-width,year));post=list(range(year+1,year+width+1))
    before=aggregate_window(panel,pre,metric).rename(columns={'outcome':'before'})
    after=aggregate_window(panel,post,metric).rename(columns={'outcome':'after'})
    baseline=panel[panel.fiscal_year.eq(year-1)][['code','population','fiscal_strength']].rename(columns={'population':'population_pre','fiscal_strength':'strength_pre'})
    eligible=cohort[cohort.election_year.eq(year)&cohort.eligible&cohort.transition.isin([target,control])]
    d=eligible.merge(before[['code','before']],on='code',validate='one_to_one').merge(after[['code','after']],on='code',validate='one_to_one').merge(baseline,on='code',validate='one_to_one')
    d=d.dropna(subset=['population_pre','strength_pre','before','after']);d=d[d.population_pre.gt(0)].copy()
    d['treated']=d.transition.eq(target).astype(int);d['change']=d.after-d.before
    # Require some treated and some control municipalities within the same
    # prefecture/type stratum, rather than extrapolating wholly unmatched strata.
    overlap=d.groupby(['prefecture','municipality_type']).treated.transform('nunique').eq(2)
    d=d[overlap].copy()
    # Diagnose pre-election drift on the SAME matched/complete-case sample.
    old=aggregate_window(panel,[year-2],metric).set_index('code').outcome
    recent=aggregate_window(panel,[year-1],metric).set_index('code').outcome
    d['pre_change']=d.code.map(recent)-d.code.map(old)
    return d,pre,post,len(eligible)

def run():
    folder=ROOT/'data/analysis';folder.mkdir(parents=True,exist_ok=True)
    panel=pd.read_parquet(ROOT/'data/panel.parquet');panel,parts=components(panel)
    links=pd.read_parquet(ROOT/'data/elections/municipality_districts.parquet');winners=pd.read_parquet(ROOT/'data/elections/election_districts.parquet')
    cohort,observations=cohorts(panel,links,winners);results=[];samples=[];trends=[];balances=[]
    for year in [2017,2021]:
        for width in [1,2]:
            for metric in OUTCOMES:
                for target,control in CONTRASTS.items():
                    d,pre,post,eligible=analysis_sample(panel,cohort,year,width,metric,target,control)
                    base={'election_year':year,'window':width,'metric':metric,'contrast':target,'control':control,'pre_years':','.join(map(str,pre)),'post_years':','.join(map(str,post)),'eligible_before_finance':eligible,'sample_size':len(d),'treated_count':int(d.treated.sum()),'control_count':int((1-d.treated).sum()),'treated_clusters':d[d.treated.eq(1)].cluster.nunique(),'control_clusters':d[d.treated.eq(0)].cluster.nunique(),'status':'推定不可'}
                    try:
                        fitted=cluster_ols(d,'change');base.update(fitted,status='探索的な調整後関連（因果結論は保留）')
                        groups=d.groupby('treated')[['before','after','change']].mean()
                        base['unadjusted_difference']=float(groups.loc[1,'change']-groups.loc[0,'change'])
                        base['control_before']=float(groups.loc[0,'before']);base['treated_before']=float(groups.loc[1,'before'])
                        base['control_after']=float(groups.loc[0,'after']);base['treated_after']=float(groups.loc[1,'after'])
                        valid_pre=d.dropna(subset=['pre_change'])
                        try:
                            placebo=cluster_ols(valid_pre,'pre_change');base.update(pre_estimate=placebo['estimate'],pre_p_value=placebo['p_value'],pre_ci_low=placebo['ci_low'],pre_ci_high=placebo['ci_high'],pre_n=len(valid_pre))
                        except ValueError as error:base['pre_status']=str(error)
                        d=d.assign(metric=metric,window=width,contrast=target)
                        samples.append(d)
                        for variable in ['population_pre','strength_pre']:
                            treated=d[d.treated.eq(1)][variable];untreated=d[d.treated.eq(0)][variable]
                            pooled=np.sqrt((treated.var()+untreated.var())/2)
                            balances.append({'election_year':year,'window':width,'metric':metric,'contrast':target,'variable':variable,'treated_mean':treated.mean(),'control_mean':untreated.mean(),'standardized_difference':(treated.mean()-untreated.mean())/pooled if pooled>0 else None})
                        for relative in [-2,-1,0,1,2]:
                            values=panel[panel.fiscal_year.eq(year+relative)][['code',metric,'population']].copy();values['yen_per_person']=values[metric]/values.population
                            joined=d[['code','treated','cluster']].merge(values[['code','yen_per_person']],on='code',validate='one_to_one')
                            for group,g in joined.groupby('treated'):
                                trends.append({'election_year':year,'window':width,'metric':metric,'contrast':target,'relative_year':relative,'group':target if group else control,'mean_yen_per_person':g.yen_per_person.mean(),'municipalities':len(g),'districts':g.cluster.nunique()})
                    except ValueError as error:base['reason']=str(error)
                    results.append(base)
    res=pd.DataFrame(results)
    res['q_value']=bh_adjust(res.p_value)
    if 'pre_p_value' in res:res['pre_q_value']=bh_adjust(res.pre_p_value)
    res['interpretation']='現データでは明確な差を確認できず（影響なしの証明ではない）'
    for i,r in res.iterrows():
        if r.status=='推定不可':res.loc[i,'interpretation']='比較条件・独立選挙区数が不足'
        elif r.small_sample:res.loc[i,'interpretation']='交代した選挙区が少ないため判断保留'
        elif pd.notna(r.pre_q_value) and r.pre_q_value<.05:res.loc[i,'interpretation']='選挙前の傾向に差があり解釈保留'
        elif r.q_value<.05:
            expected=-1 if r.contrast=='与党→野党' else 1
            res.loc[i,'interpretation']='仮説と同方向の探索的関連（因果結論は保留）' if r.estimate*expected>0 else '仮説と逆方向の探索的関連（因果結論は保留）'
    frames={'alignment_cohorts':cohort,'party_observations':observations,'grant_components':parts,'alignment_estimates':res,'alignment_samples':pd.concat(samples,ignore_index=True) if samples else pd.DataFrame(), 'alignment_trends':pd.DataFrame(trends),'alignment_balances':pd.DataFrame(balances)}
    for name,frame in frames.items():frame.to_parquet(folder/f'{name}.parquet',index=False)
    with duckdb.connect(str(ROOT/'data/finance.duckdb')) as con:
        for name,frame in frames.items():
            con.register('frame',frame);con.execute(f'CREATE OR REPLACE TABLE {name} AS SELECT * FROM frame');con.unregister('frame')
    report={'date':'2026-10-13','coalition_periods':[COALITION],'elections':[2017,2021],'metric_labels':OUTCOMES,'caveats':CAVEATS,'cohort_counts':cohort.groupby(['election_year','transition','exclusion_reason']).size().reset_index(name='municipalities').to_dict('records'),'models':len(res),'estimated_models':int(res.status.ne('推定不可').sum()),'multiple_testing_family':'32 planned contrasts: 2 elections × 2 windows × 4 outcomes × 2 hypotheses. BH across estimable tests; pretrend family separately.','files':{name:len(frame) for name,frame in frames.items()},'party_history_status':'選挙時党派観測と政権参加期間を整備。議員個人の連続党籍履歴は未整備。'}
    (folder/'analysis-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str));res.to_csv(folder/'estimates.csv',index=False)
    print(json.dumps({'models':len(res),'estimated':int(res.status.ne('推定不可').sum()),'cohort_rows':len(cohort)},ensure_ascii=False))
    print(res[['election_year','window','metric','contrast','sample_size','estimate','ci_low','ci_high','q_value','treated_clusters','interpretation']].to_string(index=False))

if __name__=='__main__':run()
