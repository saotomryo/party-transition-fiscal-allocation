"""Public national comparison entry point."""
import streamlit as st
from analysis_view import render

st.set_page_config(page_title='党派交代と財政配分の全国比較',layout='wide')
st.title('党派交代と財政配分の全国比較')
render()
