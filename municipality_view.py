"""Preserved municipality view; not linked from the public application."""
from pathlib import Path
import pandas as pd
import plotly.express as px
import streamlit as st
from finance import METRICS, peers
from elections import rank_changes, event_comparison, fiscal_phase

TABLE_LABELS={'code':'自治体コード','prefecture':'都道府県','municipality':'自治体','fiscal_year':'決算年度','population':'人口','fiscal_strength':'財政力指数','explanation_status':'変動理由','distance':'比較距離','district':'小選挙区','leading_candidate':'当選者／最多得票者','leading_party':'党派（選挙時）','leading_votes':'得票数','candidate':'候補者','party':'党派（選挙時）','votes':'得票数','votes_status':'得票の確認状況','local_label':'原本の地域表記','mapping_status':'自治体対応','result_status':'結果の確認状況','vote_sum_status':'得票合計の整合性','election_date':'選挙日','certified_candidate':'当選者','certified_party':'党派（選挙時）','certified_votes':'当選得票数','candidate_name_status':'氏名の確認状況','winner_verification':'別表との照合','certified_source_url':'公式当選資料','source_url':'公式得票資料'}
for key,name in METRICS.items():
    TABLE_LABELS.update({key:name+'（円）',key+'_change':'前年との差額（円）',key+'_pct':'前年比（%）',key+'_per_capita':'人口1人当たり（円）'})

def table(frame,**kwargs):
    labels={c:TABLE_LABELS.get(c,c) for c in frame.columns}
    configs={labels[c]:st.column_config.LinkColumn(labels[c]) for c in frame.columns if c.endswith('source_url')}
    st.dataframe(frame.rename(columns=labels),hide_index=True,column_config=configs,**kwargs)

st.set_page_config(page_title='市町村財政配分の変動',layout='wide')
st.title('市町村財政配分の変動')
st.info('公開決算の変動を確認するための画面です。抽出された変動の説明は未確認です。政治的介入を推定・断定するものではありません。')
p=Path(__file__).parent/'data/panel.parquet'
if not p.exists():st.error('先にREADMEの収集手順を実行してください。');st.stop()
d=pd.read_parquet(p)
metric=st.sidebar.selectbox('財政項目',list(METRICS),format_func=METRICS.get)
year=st.sidebar.selectbox('決算年度',sorted(d.fiscal_year.unique()),index=len(d.fiscal_year.unique())-1)
threshold=st.sidebar.slider('前年比変動率の絶対値（%）',0,200,30)
amount=st.sidebar.number_input('前年比変動額の絶対値（百万円）',0.,value=0.)
k=st.sidebar.slider('比較自治体数',3,50,20)
current=d[d.fiscal_year.eq(year)]
st.caption(f'決算年度 {d.fiscal_year.min()}–{d.fiscal_year.max()} / {d.code.nunique():,}自治体。金額は円。人口は各決算年度の翌年1月1日の住民基本台帳総計。財政力指数は3年度平均。')
st.plotly_chart(px.histogram(current,x=metric+'_pct',nbins=100,labels={metric+'_pct':'前年比変動率（%）'}),width='stretch')
flags=rank_changes(current,metric,threshold,amount*1e6)
cols=['code','prefecture','municipality','fiscal_year',metric,metric+'_change',metric+'_pct','population','fiscal_strength','explanation_status']
st.subheader(f'確認対象 {len(flags):,}件');table(flags[cols])
st.download_button('確認対象CSV',flags[cols].to_csv(index=False).encode('utf-8-sig'),'review.csv')
labels=d[['code','prefecture','municipality']].drop_duplicates('code').set_index('code')
scope=st.radio('自治体の選択範囲',['変化率が高い確認対象から選ぶ','全自治体から選ぶ'],horizontal=True)
options=flags.code.tolist() if scope=='変化率が高い確認対象から選ぶ' and not flags.empty else labels.index.tolist()
if scope=='変化率が高い確認対象から選ぶ' and flags.empty:st.caption('該当する確認対象がないため全自治体を表示します。')
code=st.selectbox('自治体',options,format_func=lambda c:f'{c} {labels.loc[c,"prefecture"]} {labels.loc[c,"municipality"]}')
selected_fiscal=current[current.code.eq(code)]
if not selected_fiscal.empty:
    row=selected_fiscal.iloc[0]
    prior_value=row[metric]-row[metric+'_change'] if pd.notna(row[metric+'_change']) else None
    st.write(f'{year}年度の{METRICS[metric]}：{row[metric]:,.0f}円')
    if prior_value is not None:st.caption(f'前年額 {prior_value:,.0f}円 → 当年額 {row[metric]:,.0f}円 / 前年比 {row[metric+"_pct"]:.2f}%（前年額が小さいほど率が大きくなりやすいため、金額も確認してください）')
fig=px.line(d[d.code.eq(code)],x='fiscal_year',y=metric,markers=True,labels={'fiscal_year':'決算年度',metric:METRICS[metric]+'（円）'})
ep=Path(__file__).parent/'data/elections'
if (ep/'election_events.parquet').exists():
    events=pd.read_parquet(ep/'election_events.parquet')
    for _,ev in events.iterrows():
        ey=int(ev.election_date[:4])
        if d.fiscal_year.min()<=ey<=d.fiscal_year.max():fig.add_vline(x=ey,line_dash='dot',annotation_text=f'{ey}衆院選（年度内）')
st.plotly_chart(fig,width='stretch')
if (ep/'election_events.parquet').exists():
    st.subheader(f'{labels.loc[code,"prefecture"]} {labels.loc[code,"municipality"]}：衆議院選挙の前後')
    st.caption('小選挙区の結果を表示します。比例代表での復活当選・補欠選挙・選挙後の党籍変更は含みません。')
    events=events.sort_values('election_date')
    eligible=events[events.election_date.str[:4].astype(int).le(year)]
    default=int(eligible.kaiji.iloc[-1]) if not eligible.empty else int(events.kaiji.iloc[0])
    kaiji=st.selectbox('確認する衆議院選挙',events.kaiji.tolist(),index=events.kaiji.tolist().index(default),format_func=lambda v:events.set_index('kaiji').loc[v,'name']+' '+events.set_index('kaiji').loc[v,'election_date'])
    ev=events[events.kaiji.eq(kaiji)].iloc[0]
    st.write(f'選択中の{year}年度：{fiscal_phase(year,ev.election_date)}')
    result=event_comparison(d,code,ev.election_date,metric)
    st.write(result['status'])
    before_col,after_col=st.columns(2)
    before_col.metric(f"{result['before_year']}年度（選挙前）",'未収録' if result['before'] is None else f"{result['before']:,.0f}円")
    after_col.metric(f"{result['after_year']}年度（選挙後）",'未収録' if result['after'] is None else f"{result['after']:,.0f}円")
    if result['change'] is not None:
        rate='前年額ゼロのため算出不可' if result['pct'] is None else f"{result['pct']:+.2f}%"
        st.write(f"前後差額：{result['change']:+,.0f}円 / 前後変化率：{rate}")
    st.caption(f"{result['election_year']}年度は選挙実施年度として前後比較から分けています。")
    if result['after'] is None:st.warning('選挙後の通年決算がないため、選挙後の増減は評価できません。選挙実施年度を選挙後データとして扱いません。')
    links=pd.read_parquet(ep/'municipality_districts.parquet')
    district_results=pd.read_parquet(ep/'election_districts.parquet')
    national=links[links.kaiji.eq(kaiji)]
    st.caption(f'自治体と選挙区の対応確認：{national.code.nunique():,}自治体。原本地域名の対応未確認：{national.code.isna().sum()}行。')
    local=links[links.code.eq(code)].drop_duplicates(['kaiji','district'])
    shown=local.merge(district_results,on=['kaiji','district'],suffixes=('_mapping',''),validate='many_to_one')
    current_results=shown[shown.kaiji.eq(kaiji)]
    if current_results.empty:st.warning('この自治体の選挙区対応は未確認です。未確認を「変化なし」とは扱いません。')
    else:
        if len(current_results)>1:st.info('この自治体には複数の小選挙区があります。すべての対応選挙区を表示します。')
        table(current_results[['district','certified_candidate','certified_party','certified_votes','certified_source_url']])
        table(current_results[['district','vote_sum_status','winner_verification','candidate_name_status','result_status']])
        with st.expander('自治体と選挙区の対応根拠'):
            table(current_results[['district','local_label','mapping_status','source_url']])
        previous=events[events.election_date.lt(ev.election_date)]
        if not previous.empty:
            prior=shown[shown.kaiji.eq(previous.kaiji.iloc[-1])]
            st.write('前回選挙の対応選挙区')
            table(prior[['election_date','district','certified_candidate','certified_party','result_status','certified_source_url']])
            st.caption('選挙区番号は区割り改定で地域範囲が変わるため、同番号を機械的に同一地域とみなしません。候補者名の表記差も人物交代と断定しません。')
        candidate_data=pd.read_parquet(ep/'election_candidates.parquet')
        with st.expander('対応選挙区の全候補者・党派・得票を見る'):
            selected=candidate_data[candidate_data.kaiji.eq(kaiji)&candidate_data.district.isin(current_results.district)]
            table(selected[['district','candidate','party','votes','votes_status','source_url']].sort_values(['district','votes'],ascending=[True,False]))
    st.link_button('総務省の選挙結果一覧',ev.source_url)
    st.link_button('当選表示を含む公式候補者別結果',ev.certified_results_url)
    st.caption('当選表示・得票の照合状況は選挙区ごとに表示します。政党名から与党・野党を自動判定しません。政治的関係と財政変動の因果関係は評価していません。')
else:
    st.info('衆院選データは未収集です。READMEの選挙収集手順を実行してください。')
comparison=peers(d,code,year,metric,k)
st.subheader('人口規模・財政力指数・団体区分が近い自治体')
st.caption('同じ団体区分で、人口比の対数と財政力指数差÷0.2の距離が小さい自治体を選択。総務省の公式類似団体分類ではなく、因果比較でもありません。')
table(comparison[['code','municipality','population','fiscal_strength','distance',metric+'_per_capita',metric+'_pct']])
if not comparison.empty:st.write('比較自治体の前年比変動率の中央値（%）',comparison[metric+'_pct'].median())
st.caption('合併・境界変更は未補正。前年のない自治体と前年額ゼロの変動率は欠測。災害・事業計画・申請額・制度改正等の説明資料は未結合。衆院選小選挙区の公式得票を確認できます。首長選挙は未結合です。')
