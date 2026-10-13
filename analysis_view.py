"""Japanese UI for the pre-specified exploratory cohort comparisons."""
from pathlib import Path
import io,json,zipfile
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from alignment import OUTCOMES,CONTRASTS,CAVEATS,aggregate_window
from finance import ROOT

@st.cache_data
def load_analysis(signature):
    folder=ROOT/'data/analysis'
    return {name:pd.read_parquet(folder/f'{name}.parquet') for name in ['alignment_estimates','alignment_cohorts','alignment_samples','alignment_trends','alignment_balances','party_observations']}

GROUPS=['与党→与党','与党→野党','野党→与党','野党→野党']

def four_group_amounts(panel,cohort,year,width,metric):
    """Describe complete eligible municipalities with equal municipality weights."""
    before=aggregate_window(panel,list(range(year-width,year)),metric)[['code','outcome']].rename(columns={'outcome':'before'})
    after=aggregate_window(panel,list(range(year+1,year+width+1)),metric)[['code','outcome']].rename(columns={'outcome':'after'})
    d=cohort[cohort.election_year.eq(year)&cohort.eligible].merge(before,on='code',validate='one_to_one').merge(after,on='code',validate='one_to_one')
    rows=[]
    for group in GROUPS:
        g=d[d.transition.eq(group)];pre=g.before.mean();post=g.after.mean();change=post-pre
        rows.append({'区分':group,'自治体数':len(g),'選挙前（円／人）':pre,'選挙後（円／人）':post,'増減額（円／人）':change,'全体傾向':'対象なし' if g.empty else ('増加' if change>0 else '減少' if change<0 else '横ばい'),'変化率（参考・%）':100*change/pre if pd.notna(pre) and pre!=0 else np.nan})
    return pd.DataFrame(rows)

@st.cache_data
def load_overview_panel(signature):
    panel=pd.read_parquet(ROOT/'data/panel.parquet')
    parts=pd.read_parquet(ROOT/'data/analysis/grant_components.parquet')
    panel=panel.merge(parts,on=['code','fiscal_year'],validate='one_to_one')
    panel['national_grants_adjusted']=panel.national_grants-panel.identified_covid_grants-panel.disaster_recovery_grants
    return panel

def render():
    folder=ROOT/'data/analysis';p=folder/'alignment_estimates.parquet'
    st.caption('近年の衆院選：2017年・2021年')
    st.caption('2017年・2021年の選挙について、変動の小さい自治体も含めて比較します。財政データは2015〜2024年度です。')
    st.warning('これは総選挙当選時の党派による探索的比較です。議員の期中の党籍変更・補選・比例復活は未反映で、予算決定時点の所属まで確認した因果検証には至っていません。')
    if not p.exists():st.info('分析データは未作成です。READMEの全国比較手順を実行してください。');return
    data=load_analysis(p.stat().st_mtime_ns);results=data['alignment_estimates'];cohort=data['alignment_cohorts']
    c1,c2=st.columns(2)
    year=c1.selectbox('比較する衆院選',[2017,2021],index=1,key='study_year')
    target=c2.selectbox('比較する党派交代',list(CONTRASTS),key='study_contrast')
    c3,c4=st.columns(2)
    metric=c3.selectbox('全国比較の財政項目',list(OUTCOMES),format_func=OUTCOMES.get,key='study_metric')
    width=c4.selectbox('選挙前後の集計期間',[2,1],format_func=lambda x:f'前後それぞれ{x}年度の平均',key='study_window')
    chosen=results[(results.election_year==year)&(results.window==width)&(results.metric==metric)&(results.contrast==target)].iloc[0]
    st.write(f'**{target}** の地域を、**{CONTRASTS[target]}** が継続した地域と比較します。')
    st.caption(f'選挙前：{chosen.pre_years}年度 / 選挙後：{chosen.post_years}年度。{year}年度は選挙実施年度として計算から分けます。')
    st.subheader('4分類の全体傾向：増加か減少か')
    panel=load_overview_panel(((ROOT/'data/panel.parquet').stat().st_mtime_ns,(folder/'grant_components.parquet').stat().st_mtime_ns))
    overview=four_group_amounts(panel,cohort,year,width,metric)
    st.dataframe(overview,hide_index=True,width='stretch',column_config={name:st.column_config.NumberColumn(format='%.1f') for name in ['選挙前（円／人）','選挙後（円／人）','増減額（円／人）','変化率（参考・%）']})
    bars=px.bar(overview,x='区分',y='増減額（円／人）',color='全体傾向',color_discrete_map={'増加':'#2463A6','減少':'#D16A46','横ばい':'#888'},text_auto=',.0f')
    bars.add_hline(y=0,line_color='#777');bars.update_layout(height=320,showlegend=False)
    st.plotly_chart(bars,width='stretch')
    st.caption('各自治体の年度別一人当たり配分を前後の期間で平均し、自治体を同じ重みで集計。4分類とも前後全年度のデータが揃った自治体を使用します。人口で重み付けした全国住民平均ではありません。変化率は分類ごとの平均額の増減率です。')
    st.caption('ここは条件調整前の全体傾向です。区割り変更・未判別などの除外後の比較候補を使い、下の条件調整分析とは対象自治体数が異なります。減少・増加の表示は政治的影響を示す判定ではありません。')
    st.download_button('4分類の全体傾向を保存',overview.to_csv(index=False).encode('utf-8-sig'),f'four-groups-{year}-{width}-{metric}.csv',key='four_group_download')
    st.subheader('選択した党派交代の条件調整比較')
    a,b=st.columns(2)
    a.metric('交代群',f'{int(chosen.treated_count):,}自治体',help='同じ選挙区の自治体は独立した交代事例として数えません。')
    b.metric('継続群',f'{int(chosen.control_count):,}自治体')
    st.caption(f'独立した選挙区：交代群 {int(chosen.treated_clusters)}区 / 継続群 {int(chosen.control_clusters)}区。市町村数が多くても交代事例が多いとは限りません。')
    if chosen.status=='推定不可':
        st.error('推定値を算出していません：'+str(chosen.get('reason','比較条件不足')))
    else:
        st.metric('条件調整後の配分変化の差',f'{chosen.estimate:+,.0f}円／人')
        st.write(f'95%区間：**{chosen.ci_low:+,.0f} 〜 {chosen.ci_high:+,.0f} 円／人**')
        st.caption('プラスは継続群より増加、マイナスは継続群より減少。人口・財政力指数・都道府県・団体区分の差を調整しています。名目額で、物価・年齢構成・災害全容は未調整です。')
        if chosen.small_sample:st.warning('交代群または継続群の選挙区数が10未満です。推定値と区間は参考値として表示しています。')
        plot=go.Figure(go.Scatter(x=[chosen.estimate],y=['調整後の差'],mode='markers',error_x={'type':'data','array':[chosen.ci_high-chosen.estimate],'arrayminus':[chosen.estimate-chosen.ci_low]},marker={'size':13,'color':'#2463A6'}))
        plot.add_vline(x=0,line_dash='dot',line_color='#777');plot.update_layout(height=220,xaxis_title='配分変化の差（円／人）',margin={'t':15,'b':30})
        st.plotly_chart(plot,width='stretch')
        st.subheader('比較群の選挙前後の金額')
        amount=pd.DataFrame({'区分':[target,CONTRASTS[target]],'選挙前（円／人）':[chosen.treated_before,chosen.control_before],'選挙後（円／人）':[chosen.treated_after,chosen.control_after]})
        amount['増減額（円／人）']=amount['選挙後（円／人）']-amount['選挙前（円／人）']
        amount['変化率（参考・%）']=100*amount['増減額（円／人）']/amount['選挙前（円／人）'].replace(0,np.nan)
        st.dataframe(amount,hide_index=True,width='stretch')
        st.caption(f'上表は調整前の平均です。調整前の増減差は {chosen.unadjusted_difference:+,.0f}円／人。条件調整後の差とは別の値です。')
        t=data['alignment_trends'];t=t[(t.election_year==year)&(t.window==width)&(t.metric==metric)&(t.contrast==target)].copy()
        baselines=t[t.relative_year.eq(-1)].set_index('group').mean_yen_per_person
        t['選挙前年からの増減（円／人）']=t.mean_yen_per_person-t.group.map(baselines)
        line=px.line(t,x='relative_year',y='選挙前年からの増減（円／人）',color='group',markers=True,labels={'relative_year':'選挙実施年度からの年数','group':'地域群'})
        line.add_vline(x=0,line_dash='dot',annotation_text='選挙実施年度');line.update_xaxes(dtick=1)
        st.subheader('選挙前後の年次推移')
        st.plotly_chart(line,width='stretch')
        st.caption('同じ分析対象の調整前平均を、選挙前年＝0として表示。年0の金額は参考表示で、前後推定に使いません。傾きが同じでも因果関係を証明しません。')
        if pd.notna(chosen.get('pre_estimate')):
            st.write(f'選挙前2年度の増減差（調整後）：{chosen.pre_estimate:+,.0f}円／人。95%区間 {chosen.pre_ci_low:+,.0f}〜{chosen.pre_ci_high:+,.0f}円／人。')
        with st.expander('不確実性と複数比較の確認'):
            st.write(f'単独比較のp値：{chosen.p_value:.4f} / 多重比較補正後：{chosen.q_value:.4f}')
            st.caption('あらかじめ定義した32比較のうち推定できた24比較をBH法で補正。95%区間は各比較の区間で、同時信頼区間ではありません。標準誤差は選挙区単位で計算し、自治体同士の相関を考慮します。')
            st.write('予算決定日・議員個人の連続党籍履歴は未確認です。小さいp値だけで議員の影響や政治的介入を判断しません。')
    selected_cohort=cohort[cohort.election_year.eq(year)]
    counts=selected_cohort.groupby(['eligible','transition','exclusion_reason']).size().reset_index(name='自治体数')
    with st.expander('全国データからの分類と除外理由'):
        st.dataframe(counts.rename(columns={'eligible':'分析候補','transition':'党派交代','exclusion_reason':'除外理由'}),hide_index=True)
        st.caption('候補からさらに、財政データ完備・同じ都道府県と団体区分に交代群と継続群の両方があることを要求します。無所属を野党扱いせず、複数選挙区や区割り構成の変化は主分析から外します。')
        st.download_button('分類・除外の一覧CSV',selected_cohort.to_csv(index=False).encode('utf-8-sig'),f'cohort-{year}.csv',key='cohort_download')
    sample=data['alignment_samples'];sample=sample[(sample.election_year==year)&(sample.window==width)&(sample.metric==metric)&(sample.contrast==target)]
    if not sample.empty:
        with st.expander('分析に使用した自治体と出典'):
            names={'code':'自治体コード','prefecture':'都道府県','municipality':'自治体','transition':'党派交代','before_party':'前回当選時党派','after_party':'今回当選時党派','cluster':'小選挙区','before':'選挙前（円／人）','after':'選挙後（円／人）','before_source':'前回当選資料','after_source':'今回当選資料'}
            shown=sample[list(names)].rename(columns=names)
            st.dataframe(shown,hide_index=True,column_config={'前回当選資料':st.column_config.LinkColumn(),'今回当選資料':st.column_config.LinkColumn()})
        with st.expander('比較群の人口・財政力指数'):
            balance=data['alignment_balances'];balance=balance[(balance.election_year==year)&(balance.window==width)&(balance.metric==metric)&(balance.contrast==target)].copy()
            balance['variable']=balance.variable.map({'population_pre':'選挙前人口','strength_pre':'選挙前財政力指数'})
            st.dataframe(balance[['variable','treated_mean','control_mean','standardized_difference']].rename(columns={'variable':'項目','treated_mean':'交代群の平均','control_mean':'継続群の平均','standardized_difference':'調整前の標準化差'}),hide_index=True)
            st.caption('回帰調整前の差です。大きな差がある場合、調整後推定への依存が強くなります。')
    with st.expander('分析範囲・政権判定の根拠'):
        for caveat in CAVEATS:st.write('・'+caveat)
        st.write('今回の2015〜2023年度の比較期間では、自民党・公明党を連立参加政党として判定。期間外への自動延長はしません。')
        for label,url in [('2012年の連立合意','https://www.komei.or.jp/news/detail/20121226_9916'),('2017年の内閣発足','https://www.komei.or.jp/news/detail/20171102_26181'),('2020年の連立合意','https://www.komei.or.jp/komeinews/p120939/'),('2021年の首相会見','https://www.jimin.jp/news/press/202278.html'),('公明党の公式沿革','https://www.komei.or.jp/about/history/')]:st.link_button(label,url)
    package=io.BytesIO()
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('four-group-overview.csv',overview.to_csv(index=False))
        archive.writestr('four-group-method.txt','前後全年度が揃う分類可能な自治体の等重み平均。条件調整分析とは標本が異なる。変化率は群平均額の増減率。政治的影響の判定ではない。')
        archive.writestr('selected-estimate.csv',pd.DataFrame([chosen]).to_csv(index=False))
        archive.writestr('municipalities.csv',sample.to_csv(index=False))
        archive.writestr('methodology.json',(folder/'analysis-report.json').read_text())
        archive.writestr('readme.txt','探索的関連の確認用。議員の因果的影響・政治的介入の証明ではありません。\n'+'\n'.join(CAVEATS))
    st.download_button('結果・使用データ・注意点をまとめて保存',package.getvalue(),f'alignment-{year}-{metric}.zip',mime='application/zip')
