"""Official municipal finance collection and descriptive comparisons."""
from pathlib import Path
import argparse, hashlib, io, json, re
from datetime import datetime, timezone
import duckdb
import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parent
BASE='https://www.e-stat.go.jp'
METRICS={'allocation_tax':'地方交付税','ordinary_tax':'普通交付税','special_tax':'特別交付税','reconstruction_tax':'震災復興特別交付税','national_grants':'国庫支出金'}

def fetch(url,path,log):
    """Cache official responses with SHA256 provenance; never require API secrets."""
    if not path.exists():
        r=requests.get(url,timeout=90);r.raise_for_status();path.write_bytes(r.content)
    b=path.read_bytes()
    log.append({'url':url,'file':str(path.relative_to(ROOT)),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'checked_at':datetime.now(timezone.utc).isoformat()})
    return b

def discover(year,stat,log):
    params={'layout':'dataset','toukei':stat,'year':str(year)+'0'}
    if stat=='00200251':params.update(tstat='000001077755',tclass1='000001077756',tclass2='000001077757')
    url=BASE+'/stat-search/files?'+requests.compat.urlencode(params)
    raw=ROOT/'data/raw';raw.mkdir(parents=True,exist_ok=True)
    html=fetch(url,raw/f'{stat}-{year}-index.html',log)
    found={}
    for a in BeautifulSoup(html,'html.parser').select('article'):
        title=a.select_one('.stat-resource_list-detail-item-text')
        if title:
            name=' '.join(title.stripped_strings)
            for link in a.select('a[href*="file-download"]'):
                href=link['href']
                kind='1' if stat=='00200251' else '0'
                if 'fileKind='+kind in href:found[name]=BASE+href
    return found

def read_finance(b):
    for enc in ['utf-8-sig','cp932']:
        try:d=pd.read_csv(io.BytesIO(b),encoding=enc,dtype=str);break
        except UnicodeDecodeError:continue
    d.columns=d.columns.str.strip()
    d=d[d['団体コード'].str.fullmatch(r'\d{5,6}',na=False) & d['団体区分'].isin(['1','2','3','4','5','8','9'])].copy()
    d['code']=d['団体コード'].str.zfill(6)
    d['fiscal_year']=pd.to_numeric(d['決算年度'],errors='raise').astype(int)
    return d

def column(d,label):
    matches=[c for c in d.columns if c.split(':',1)[-1]==label or (label=='財政力指数' and '財政力指数' in c)]
    if len(matches)!=1:raise ValueError(f'Column mismatch: {label}: {matches}')
    return pd.to_numeric(d[matches[0]].replace({'***':None,'-':None,'－':None}),errors='raise')

def normalize(revenue,cover,pop,year):
    r=read_finance(revenue);c=read_finance(cover)
    r=r[pd.to_numeric(r['行番号'],errors='raise').eq(1)].copy()
    if set(r.fiscal_year)!={year}:raise ValueError('Survey year differs from expected fiscal year')
    out=r[['code','fiscal_year','県名','団体名','団体区分']].rename(columns={'県名':'prefecture','団体名':'municipality','団体区分':'municipality_type'})
    for key,label in METRICS.items():out[key]=column(r,label)*1000 # source: thousand yen
    strengths=c[['code','fiscal_year']].copy();strengths['fiscal_strength']=column(c,'財政力指数')/100
    out=out.merge(strengths,on=['code','fiscal_year'],validate='one_to_one')
    p=pd.read_excel(io.BytesIO(pop),header=None,dtype=str)
    # Official workbook labels checked before accepting layout.
    expected_era=f'令和{year+1-2018}年' if year+1>=2020 else f'平成{year+1-1988}年'
    if expected_era not in str(p.iat[0,0]):raise ValueError('Population reference year changed')
    if not any(str(p.iat[i,5]).strip()=='計' for i in range(6)):raise ValueError('Population total column changed')
    p=p[p[0].str.fullmatch(r'\d{6}',na=False)]
    population=pd.DataFrame({'code':p[0],'population':pd.to_numeric(p[5].replace({'***':None}),errors='raise')})
    out=out.merge(population,on='code',how='left',validate='one_to_one')
    if out.population.isna().any():raise ValueError('Missing population matches')
    out['population_date']=f'{year+1}-01-01';out['population_definition']='住民基本台帳・総計（日本人＋外国人）'
    out['explanation_status']='説明未確認'
    if out.duplicated(['code','fiscal_year']).any():raise ValueError('Duplicate municipality/year')
    complete=out[['allocation_tax','ordinary_tax','special_tax','reconstruction_tax']].dropna()
    if not (complete.allocation_tax==complete.ordinary_tax+complete.special_tax+complete.reconstruction_tax).all():raise ValueError('Allocation tax breakdown mismatch')
    return out

def changes(d):
    d=d.sort_values(['code','fiscal_year']).copy();g=d.groupby('code')
    contiguous=d.fiscal_year.sub(g.fiscal_year.shift()).eq(1)
    for m in METRICS:
        prev=g[m].shift().where(contiguous)
        d[m+'_change']=d[m]-prev
        d[m+'_pct']=((d[m]/prev.where(prev.ne(0)))-1)*100
        d[m+'_per_capita']=d[m]/d.population.where(d.population.gt(0))
    return d

def peers(d,code,year,metric,k=20):
    current=d[d.fiscal_year.eq(year)].copy();target=current[current.code.eq(code)]
    if target.empty:return current.iloc[:0]
    t=target.iloc[0]
    current=current[current.municipality_type.eq(t.municipality_type) & current.code.ne(code) & current.population.gt(0) & current.fiscal_strength.notna()].copy()
    # Explicit exploratory distance: log population and fiscal strength / 0.2.
    current['distance']=np.sqrt(np.log(current.population/t.population)**2+((current.fiscal_strength-t.fiscal_strength)/.2)**2)
    return current.nsmallest(k,'distance')

def collect(start,end):
    log=[];frames=[];failures=[]
    for year in range(start,end+1):
        try:
            files=discover(year+1,'00200251',log);popfiles=discover(year+1,'00200241',log)
            def load(mapping,needle,ext):
                hits=[v for n,v in mapping.items() if needle(n)]
                if len(hits)!=1:raise ValueError(f'Table discovery failed: {hits}')
                return fetch(hits[0],ROOT/f'data/raw/{year}-{ext}',log)
            r=load(files,lambda n:bool(re.fullmatch(r'0?4 歳入内訳',n)),'revenue.csv')
            c=load(files,lambda n:n in ['表紙','00 表紙'],'cover.csv')
            p=load(popfiles,lambda n:'【総計】市区町村別人口、人口動態及び世帯数' in n,'population.xlsx')
            frame=normalize(r,c,p,year);frames.append(frame)
            print(json.dumps({'fiscal_year':year,'success':True,'rows':len(frame)},ensure_ascii=False),flush=True)
        except Exception as e:
            failures.append({'fiscal_year':year,'error':str(e)});print(json.dumps(failures[-1],ensure_ascii=False),flush=True)
    report={'sources':log,'failures':failures,'requested_years':[start,end],'successful_years':[int(f.fiscal_year.iloc[0]) for f in frames]}
    (ROOT/'data/collection-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    if failures:raise RuntimeError('Incomplete collection; report saved, existing panel unchanged')
    d=changes(pd.concat(frames,ignore_index=True))
    d.to_parquet(ROOT/'data/panel.parquet',index=False)
    with duckdb.connect(str(ROOT/'data/finance.duckdb')) as con:
        con.register('panel',d);con.execute('CREATE OR REPLACE TABLE municipal_finance AS SELECT * FROM panel')
    print(json.dumps({'rows':len(d),'municipalities':d.code.nunique(),'years':sorted(d.fiscal_year.unique().tolist())}))

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--start',type=int,default=2015);a.add_argument('--end',type=int,default=2024);args=a.parse_args()
    if args.start>args.end:a.error('start must not exceed end')
    collect(args.start,args.end)
