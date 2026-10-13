"""Official Lower House election facts and descriptive fiscal event views.

No ruling/opposition or interference inference. Plurality leaders are distinct
from certified election results. Municipality mapping retains split districts.
"""
from pathlib import Path
from datetime import date, datetime, timezone
from urllib.parse import urljoin,urlparse
import argparse, hashlib, io, json, re, unicodedata
import duckdb
import pandas as pd
import requests
from bs4 import BeautifulSoup
from finance import ROOT

ELECTIONS={47:'2014-12-14',48:'2017-10-22',49:'2021-10-31',50:'2024-10-27'}
BASE='https://www.soumu.go.jp'

def clean(x):
    return '' if pd.isna(x) else re.sub(r'\s+','',unicodedata.normalize('NFKC',str(x)))

def fiscal_phase(year,election_date):
    dt=date.fromisoformat(election_date);ey=dt.year-(dt.month<4)
    return '選挙前の通年年度' if year<ey else ('選挙実施年度' if year==ey else '選挙後の通年年度')

def rank_changes(d,metric,threshold,min_yen):
    rows=d[d[metric+'_pct'].abs().ge(threshold)&d[metric+'_change'].abs().ge(min_yen)].copy()
    return rows.assign(_abs_rate=rows[metric+'_pct'].abs()).sort_values(['_abs_rate',metric+'_change'],ascending=False).drop(columns='_abs_rate')

def event_comparison(panel,code,election_date,metric):
    dt=date.fromisoformat(election_date);ey=dt.year-(dt.month<4)
    before=ey-1;after=ey+1;d=panel[panel.code.eq(code)].set_index('fiscal_year')
    result={'before_year':before,'election_year':ey,'after_year':after,'status':'選挙前後の通年データ不足','before':None,'after':None,'change':None,'pct':None}
    for key,y in [('before',before),('after',after)]:
        if y in d.index and pd.notna(d.loc[y,metric]):result[key]=float(d.loc[y,metric])
    if result['before'] is not None and result['after'] is not None:
        result.update(status='記述的な前後比較（因果効果ではない）',change=result['after']-result['before'])
        if result['before']!=0:result['pct']=(result['after']/result['before']-1)*100
    # Avoid floating-point display noise.
    if result['pct'] is not None:result['pct']=round(result['pct'],10)
    return result

def match_municipality(label,prefecture,reference):
    label=clean(label).replace('ヶ','ケ').replace('檮','梼').replace('桧','檜').replace('鰺','鯵');ref=reference[reference.prefecture.eq(prefecture)].drop_duplicates('code')
    exact=ref[ref.municipality.map(lambda n:clean(n).replace('ヶ','ケ').replace('檮','梼').replace('桧','檜').replace('鰺','鯵')).eq(label)]
    if len(exact)==1:return exact.iloc[0].code,'名称完全一致'
    if len(exact)>1:return None,'同名自治体のため未確定'
    # Full city names followed by administrative ward / split notation only.
    city=ref[ref.municipality.map(lambda n:clean(n).replace('ヶ','ケ').replace('檮','梼').replace('桧','檜').replace('鰺','鯵')).map(lambda n:n.endswith('市') and label.startswith(n) and bool(re.match(r'.*区|\(|第\d+',label[len(n):])))]
    if len(city)==1:return city.iloc[0].code,'政令市の行政区・一部地域を市に集約'
    partial=ref[ref.municipality.map(lambda n:clean(n).replace('ヶ','ケ').replace('檮','梼').replace('桧','檜').replace('鰺','鯵')).map(lambda n:label.startswith(n) and bool(re.match(r'(?:\(|第?\d+区|の一部)',label[len(n):])))]
    if len(partial)==1:return partial.iloc[0].code,'自治体名＋一部地域表記'
    # Ward aliases built exclusively from official population workbook.
    ward_map=reference.attrs.get('ward_map',{})
    stripped=re.sub(r'(?:\(.*|第\d+区)$','',label)
    alias=ward_map.get((prefecture,stripped))
    if alias:return alias,'住民基本台帳の行政区名から親市を確認'
    # County prefix only when municipality name is unique within prefecture.
    suffix=ref[ref.municipality.map(lambda n:clean(n).replace('ヶ','ケ').replace('檮','梼').replace('桧','檜').replace('鰺','鯵')).map(lambda n:label.endswith(n) and '郡' in label[:-len(n)])]
    if len(suffix)==1:return suffix.iloc[0].code,'郡名付き表記'
    return None,'名称対応未確認'

def get(url,raw,log):
    if urlparse(url).hostname!='www.soumu.go.jp':raise ValueError('Only official MIC URLs accepted')
    path=raw/(urlparse(url).path.replace('/','_').strip('_'))
    cached=path.exists()
    if not cached:
        response=requests.get(url,timeout=60);response.raise_for_status();path.write_bytes(response.content)
    b=path.read_bytes();log.append({'url':url,'file':str(path.relative_to(ROOT)),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b),'cached':cached,'checked_at':datetime.now(timezone.utc).isoformat()})
    return b

def soup(b):
    try:return BeautifulSoup(b.decode('utf-8'),'html.parser')
    except UnicodeDecodeError:return BeautifulSoup(b.decode('cp932'),'html.parser')

def official_files(kaiji,raw,log):
    index=f'{BASE}/senkyo/senkyo_s/data/shugiin{kaiji}/index.html'
    top=soup(get(index,raw,log))
    municipal=[urljoin(index,a['href']) for a in top.select('a[href]') if '市区町村別得票数' in clean(a.get_text())]
    if len(municipal)!=1:raise ValueError('Missing municipal index')
    pdf=[urljoin(index,a['href']) for a in top.select('a[href]') if '候補者別得票数(小選挙区)' in clean(a.get_text())]
    page=municipal[0];s=soup(get(page,raw,log));files={}
    # 2024 direct prefecture files; earlier elections separate prefecture pages.
    for a in s.select('a[href]'):
        name=clean(a.get_text());url=urljoin(page,a['href'])
        if re.search(r'\.(?:xls|xlsx)$',url) and re.fullmatch(r'.+(?:都|道|府|県)',name):files[name]=url
        if re.search(r'shikuchouson_\d+\.html$',url):
            sub=soup(get(url,raw,log))
            links=[urljoin(url,x['href']) for x in sub.select('a[href]') if clean(x.get_text())=='小選挙区']
            if len(links)!=1:raise ValueError(f'Missing prefecture file: {name}')
            files[name]=links[0]
    if len(files)!=47:raise ValueError(f'Expected 47 prefectures, got {len(files)}')
    return files,index,pdf[0] if len(pdf)==1 else index

def parse_workbook(b,kaiji,prefecture,url,reference):
    workbook=pd.ExcelFile(io.BytesIO(b));districts=[];mapping=[];candidates=[];issues=[]
    for sheet in workbook.sheet_names:
        d=pd.read_excel(workbook,sheet_name=sheet,header=None)
        first=d.iloc[:,0].map(clean)
        head=[i for i,v in enumerate(first) if v=='候補者名']
        if not head:
            if any('第' in v and '区' in v for v in first):raise ValueError(f'Unparsed district sheet: {sheet}')
            continue
        if len(head)!=1:raise ValueError(f'Multiple headers: {sheet}')
        h=head[0];district=clean(d.iat[h-1,0]);columns=[j for j in range(1,d.shape[1]) if clean(d.iat[h,j]) and '計' not in clean(d.iat[h,j])]
        totals=[i for i,v in enumerate(first) if district in v and ('合計' in v or v.endswith('計'))]
        if not totals:raise ValueError(f'Missing district total {district}')
        total_row=totals[-1];votes=[];missing_totals=[]
        for j in columns:
            v=pd.to_numeric(d.iat[total_row,j],errors='coerce')
            total_status='公式選挙区計'
            if pd.isna(v):
                local_values=pd.to_numeric(d.iloc[h+2:total_row,j],errors='coerce')
                if local_values.notna().sum()==0:raise ValueError(f'Missing all votes {district}')
                v=local_values.sum();missing_totals.append(j);total_status='選挙区計欠測・市区町村得票から算出'
                issues.append({'issue_type':'missing_candidate_total','kaiji':kaiji,'prefecture':prefecture,'district':district,'source_url':url,'candidate':clean(d.iat[h,j]),'derived_votes':float(v)})
            votes.append(float(v));candidates.append({'kaiji':kaiji,'election_date':ELECTIONS[kaiji],'prefecture':prefecture,'district':district,'candidate':clean(d.iat[h,j]),'party':clean(d.iat[h+1,j]) or '党派欄空白（未確認）','votes':float(v),'votes_status':total_status,'source_url':url,'sheet':sheet})
        maximum=max(votes)
        winners=[j for j,v in zip(columns,votes) if v==maximum]
        if len(winners)!=1:raise ValueError(f'Tied maximum {district}; do not infer result')
        j=winners[0]
        districts.append({'kaiji':kaiji,'election_date':ELECTIONS[kaiji],'prefecture':prefecture,'district':district,'leading_candidate':clean(d.iat[h,j]),'leading_party':clean(d.iat[h+1,j]) or '党派欄空白（未確認）','leading_votes':maximum,'result_status':('選挙区計欠測候補あり・市区町村得票合算を使用（当選表示の照合未実施）' if missing_totals else '公式得票から算出した最多得票者（当選表示の照合未実施）'),'source_url':url,'sheet':sheet})
        # Validate each candidate total against all local rows, preserving postal votes.
        local=d.iloc[h+2:total_row]
        mismatches=[]
        for col,total in zip(columns,votes):
            vals=pd.to_numeric(local.iloc[:,col],errors='coerce')
            if abs(vals.sum()-total)>.1:mismatches.append({'candidate_column':col,'local_sum':float(vals.sum()),'district_total':total})
        districts[-1]['vote_sum_status']=('選挙区計欠測を市区町村計から算出（要照合）' if missing_totals else '一致') if not mismatches else '原本内の市区町村計と選挙区計が不一致（要照合）'
        if mismatches:issues.append({'issue_type':'vote_sum_mismatch','kaiji':kaiji,'prefecture':prefecture,'district':district,'source_url':url,'details':mismatches})
        for i in range(h+2,total_row):
            label=clean(d.iat[i,0])
            if not label or '計' in label or '在外' in label or 'その他' in label:continue
            code,status=match_municipality(label,prefecture,reference)
            row={'kaiji':kaiji,'election_date':ELECTIONS[kaiji],'prefecture':prefecture,'district':district,'local_label':label,'code':code,'mapping_status':status,'source_url':url,'sheet':sheet}
            mapping.append(row)
            if code is None:issues.append(row)
    return districts,mapping,candidates,issues

def collect():
    raw=ROOT/'data/elections/raw';raw.mkdir(parents=True,exist_ok=True)
    panel=pd.read_parquet(ROOT/'data/panel.parquet');log=[];districts=[];mapping=[];candidates=[];issues=[];failures=[];events=[]
    for kaiji,dt in ELECTIONS.items():
        try:
            files,index,result_url=official_files(kaiji,raw,log)
            reference=panel[panel.fiscal_year.eq(max(2015,date.fromisoformat(dt).year))][['code','prefecture','municipality']]
            pop_year=max(2015,date.fromisoformat(dt).year)
            pop=pd.read_excel(ROOT/f'data/raw/{pop_year}-population.xlsx',header=None,dtype=str)
            wards={}
            for _,row in pop.iterrows():
                if pd.notna(row[2]) and re.fullmatch(r'\d{6}',str(row[0])):
                    name=clean(row[2]);pref=clean(row[1])
                    parents=reference[reference.prefecture.eq(pref)&reference.municipality.map(lambda n:clean(n).endswith('市') and name.startswith(clean(n)) and name!=clean(n))]
                    if len(parents)==1:
                        parent=parents.iloc[0];ward=name[len(clean(parent.municipality)):]
                        key=(pref,ward)
                        wards[key]=parent.code if key not in wards or wards[key]==parent.code else None
            reference.attrs['ward_map']=wards
            ev={'kaiji':kaiji,'election_date':dt,'name':f'第{kaiji}回衆議院議員総選挙','source_url':index,'certified_results_url':result_url}
            local_d=[];local_m=[];local_c=[];local_i=[]
            for pref,url in files.items():
                ds,ms,cs,ins=parse_workbook(get(url,raw,log),kaiji,pref,url,reference)
                local_d+=ds;local_m+=ms;local_c+=cs;local_i+=ins
            expected=295 if kaiji==47 else 289
            if len(local_d)!=expected:raise ValueError(f'Expected {expected} districts got {len(local_d)}')
            districts+=local_d;mapping+=local_m;candidates+=local_c;issues+=local_i;events.append(ev)
            print(json.dumps({'kaiji':kaiji,'districts':len(local_d),'mapping_rows':len(local_m),'unresolved':sum(m['code'] is None for m in local_m),'vote_sum_issues':sum('vote_sum_mismatch'==i.get('issue_type') for i in local_i),'status':'success'},ensure_ascii=False),flush=True)
        except Exception as e:
            failures.append({'kaiji':kaiji,'error':str(e)});print(json.dumps(failures[-1],ensure_ascii=False),flush=True)
    report={'sources':log,'failures':failures,'mapping_issues':issues,'completed_elections':[e['kaiji'] for e in events]}
    (ROOT/'data/elections/collection-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    if failures:raise RuntimeError('Incomplete collection; existing normalized files unchanged')
    frames={'election_events':pd.DataFrame(events),'election_districts':pd.DataFrame(districts),'municipality_districts':pd.DataFrame(mapping),'election_candidates':pd.DataFrame(candidates)}
    if frames['election_districts'].duplicated(['kaiji','district']).any():raise ValueError('Duplicate district')
    for name,frame in frames.items():frame.to_parquet(ROOT/f'data/elections/{name}.parquet',index=False)
    with duckdb.connect(str(ROOT/'data/finance.duckdb')) as con:
        for name,frame in frames.items():
            con.register('input_frame',frame);con.execute(f'CREATE OR REPLACE TABLE {name} AS SELECT * FROM input_frame');con.unregister('input_frame')
    (ROOT/'data/elections/summary.json').write_text(json.dumps({name:len(f) for name,f in frames.items()},indent=2))

if __name__=='__main__':
    collect()
