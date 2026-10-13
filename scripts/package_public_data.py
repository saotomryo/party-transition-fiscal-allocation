"""Package only processed numeric data required by the national dashboard."""
from pathlib import Path
import hashlib,json,shutil
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]

def main():
    dest=ROOT/'public_data';(dest/'analysis').mkdir(parents=True,exist_ok=True)
    files=[]
    columns=['code','fiscal_year','population','national_grants','special_tax','ordinary_tax']
    panel=pd.read_parquet(ROOT/'data/panel.parquet')[columns]
    panel.to_parquet(dest/'panel.parquet',index=False)
    names=['alignment_estimates','alignment_cohorts','alignment_samples','alignment_trends','alignment_balances','party_observations','grant_components']
    for name in names:
        shutil.copy2(ROOT/f'data/analysis/{name}.parquet',dest/f'analysis/{name}.parquet')
    shutil.copy2(ROOT/'data/analysis/analysis-report.json',dest/'analysis/analysis-report.json')
    for p in sorted(dest.rglob('*')):
        if p.is_file() and p.name!='manifest.json':files.append({'path':str(p.relative_to(dest)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    (dest/'manifest.json').write_text(json.dumps({'snapshot_date':'2026-10-13','source':'総務省・政府統計の総合窓口(e-Stat)の公開統計・衆院選結果を加工','processed_by':'party-transition-fiscal-allocation','files':files},ensure_ascii=False,indent=2))
    print(f'Packaged {len(files)} files, {sum(x["bytes"] for x in files):,} bytes')
if __name__=='__main__':main()
