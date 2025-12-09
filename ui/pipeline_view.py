import streamlit as st
from pipeline.engine import run_pipeline


def render_pipeline_section(region: str):
    st.subheader("1️⃣ AWS Self-Healing Pipeline")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("▶ Run pipeline (continue from first non-success)"):
            run_pipeline(region, "from_first_pending")

    with c2:
        if st.button("♻ Retry failed stages only"):
            run_pipeline(region, "failed_only")

    st.markdown("### Pipeline Summary")

    table = [
        {
            "ID": s.id,
            "Stage": s.name,
            "Status": s.status,
            "Description": s.description,
        }
        for s in st.session_state.pipeline_stages
    ]

    st.dataframe(table, hide_index=True, use_container_width=True)

    # Expanded details
    for stage in st.session_state.pipeline_stages:
        with st.expander(f"{stage.name} — {stage.status}"):
            st.write(stage.description)

            if stage.last_output:
                st.markdown("**Output:**")
                st.json(stage.last_output)

            if stage.error:
                st.markdown("**Error:**")
                st.code(stage.error)

            if stage.fix_suggestion:
                st.markdown("**Self-Healing Suggestion:**")
                st.markdown(stage.fix_suggestion)

import streamlit as st
from pipeline.engine import inject_uploaded_graph


def render_pipeline_section(region: str):
    st.subheader("1️⃣ AWS Self-Healing Pipeline")

    # -------------------------------
    # Upload LangGraph Definition
    # -------------------------------
    st.markdown("### Upload LangGraph Definition (YAML / JSON)")
    upload = st.file_uploader("Upload graph", type=["yaml", "yml", "json"])

    if upload:
        inject_uploaded_graph(upload)
        st.success("LangGraph loaded successfully!")

    # (existing pipeline run buttons + display)

