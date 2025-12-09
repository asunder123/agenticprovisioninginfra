from typing import List
from .stages import DEFAULT_STAGES
import streamlit as st


def init_pipeline_state():
    if "pipeline_stages" not in st.session_state:
        st.session_state.pipeline_stages = [s.copy() for s in DEFAULT_STAGES]


def reset_pipeline_state():
    st.session_state.pipeline_stages = [s.copy() for s in DEFAULT_STAGES]
