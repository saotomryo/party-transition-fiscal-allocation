"""Verify plurality leaders against the MIC national candidate outcome tables."""
import io,re,json
import pandas as pd
import pdfplumber
from elections import ROOT,ELECTIONS,get,clean,soup
from finance import BASE as ESTAT_BASE

PREFECTURES=pd.read_parquet(ROOT/'data/panel.parquet').prefecture.unique().tolist()
DISTRICT=re.compile('('+'|'.join(map(re.escape,PREFECTURES))+r')第(\d+)区')
VOTES=re.compile(r'(?<![\d.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{4,}(?:\.\d+)?)(?![\d.])')

def pdf_winners(b):
    winners=[];district=None
    with pdfplumber.open(io.BytesIO(b)) as pdf:
        for page_number,page in enumerate(pdf.pages,1):
            boundary=page.width*.49
            for side in [0,1]:
                part=page.filter(lambda obj:(obj.get('x0',0)<boundary) if side==0 else (obj.get('x0',0)>=boundary))
                for line in (part.extract_text() or '').splitlines():
                    text=clean(line)
                    m=DISTRICT.search(text)
                    if m:district=m[1]+'第'+m[2]+'区'
                    # A candidate row must start with the official 当 mark; not 当落 header.
                    if re.match(r'^[\d.]*当',text) and '候補者氏名' not in text:
                        text=text[text.index('当'):]
                        nums=VOTES.findall(line)
                        if len(nums)!=1:continue
                        if district is None:raise ValueError('Winner before district header')
                        identity=re.match(r'^当(.*?)(?:男|女)?(\d{2,3})(.*)',text)
                        if identity is None:raise ValueError(f'Cannot parse certified identity {district}')
                        name=identity[1];rest=identity[3]
                        parties=sorted({clean(p).strip('()') for p in pd.read_parquet(ROOT/'data/elections/election_candidates.parquet').party} | {'無所属'},key=len,reverse=True)
                        party=next((p for p in parties if rest.startswith(p) or rest.startswith('('+p+')')),None)
                        if party is None:raise ValueError(f'Unknown official winner party {district}: {rest}')
                        winners.append({'certified_candidate':name,'certified_party':party,'district':district,'certified_votes':float(nums[0].replace(',','')),'certified_page':page_number,'certified_row':text})
    return winners

def xls_winners(b):
    d=pd.read_excel(io.BytesIO(b),header=None);ends=[i for i in range(len(d)) if clean(d.iat[i,0]).startswith('(注)1')]
    if not ends:raise ValueError('Missing official table page boundaries')
    out=[];start=0;district=None
    for end in ends+[len(d)]:
        for offset in [0,10]:
            for i in range(start,end):
                first=clean(d.iat[i,offset]);m=DISTRICT.search(first)
                if m:district=m[1]+'第'+m[2]+'区'
                if first=='当':
                    out.append({'certified_candidate':clean(d.iat[i,offset+1]),'certified_party':clean(d.iat[i,offset+4]).strip('()'),'district':district,'certified_votes':float(d.iat[i,offset+7]),'certified_page':None,'certified_row':clean(d.iat[i,offset+1])+':'+clean(d.iat[i,offset+4])})
        start=end+1
    return out

def certify():
    raw=ROOT/'data/elections/raw';events=pd.read_parquet(ROOT/'data/elections/election_events.parquet');leaders=pd.read_parquet(ROOT/'data/elections/election_districts.parquet');log=[];all_winners=[]
    for _,event in events.iterrows():
        url=event.certified_results_url
        b=get(url,raw,log)
        rows=xls_winners(b) if url.endswith('.xls') else pdf_winners(b)
        w=pd.DataFrame(rows)
        expected=295 if event.kaiji==47 else 289
        if len(w)!=expected or w.district.duplicated().any():raise ValueError(f'Incomplete certified winners {event.kaiji}: {len(w)} / {expected}')
        w['kaiji']=event.kaiji;w['certified_source_url']=url;all_winners.append(w)
        print(json.dumps({'kaiji':int(event.kaiji),'certified_winners':len(w)}),flush=True)
    official=pd.concat(all_winners,ignore_index=True)
    merged=leaders.drop(columns=[c for c in leaders.columns if c.startswith('certified_') or c in ['winner_verification','candidate_name_status']],errors='ignore').merge(official,on=['kaiji','district'],how='left',validate='one_to_one')
    merged['winner_verification']=merged.leading_votes.sub(merged.certified_votes).abs().lt(.001).map({True:'公式当選表示・得票と一致',False:'公式当選表示の得票と不一致（要照合）'})
    missing_name=merged.certified_candidate.eq('')
    merged['candidate_name_status']='公式当選表から取得'
    supplement=missing_name & merged.winner_verification.eq('公式当選表示・得票と一致')
    merged.loc[supplement,'certified_candidate']=merged.loc[supplement,'leading_candidate']
    merged.loc[supplement,'candidate_name_status']='公式当選表の氏名抽出不可・同一得票の市区町村別表から補完'
    merged['result_status']='小選挙区当選（公式当選表から取得）'
    merged.loc[merged.winner_verification.ne('公式当選表示・得票と一致'),'result_status']='小選挙区当選表を採用・市区町村別表の得票と不一致（要照合）'
    merged.to_parquet(ROOT/'data/elections/election_districts.parquet',index=False)
    import duckdb
    with duckdb.connect(str(ROOT/'data/finance.duckdb')) as con:
        con.register('verified',merged);con.execute('CREATE OR REPLACE TABLE election_districts AS SELECT * FROM verified')
    report={'sources':log,'verified':int(merged.winner_verification.eq('公式当選表示・得票と一致').sum()),'unverified':merged[merged.winner_verification.ne('公式当選表示・得票と一致')][['kaiji','district','leading_votes','certified_votes']].to_dict('records')}
    (ROOT/'data/elections/certification-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'verified':report['verified'],'unverified':len(report['unverified'])}))

if __name__=='__main__':certify()
