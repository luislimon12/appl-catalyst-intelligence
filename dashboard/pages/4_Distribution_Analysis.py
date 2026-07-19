"""
Page 4 — Distribution Analysis
AAPL & INTC Catalyst Intelligence Dashboard
Jul 2026: Statistical analysis of IV, Greeks, and Volume distributions
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas
import numpy as np
import streamlit as st
from scipy import stats

from utils import DARK_THEME_CSS, query, render_sidebar, render_page_header

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Distribution Analysis · Catalyst Intelligence",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)
st.markdown(DARK_THEME_CSS, unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
ticker, refresh_secs = render_sidebar("Distribution Analysis")

# ── Header ────────────────────────────────────────────────────────────────────
render_page_header("📊", "Distribution Analysis", "IV · Greeks · Volume · Stationarity Tests", ticker)

# ── Coming soon placeholder ───────────────────────────────────────────────────
st.info("🚧 Building this page step by step. Check back as sections are added.")
