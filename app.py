import streamlit as st
from pipeline.state import init_pipeline_state, reset_pipeline_state
from ui.pipeline_view import render_pipeline_section
from ui.chat_view import render_chat_section


def aws_credentials_ui():
    st.sidebar.header("🔐 AWS Credentials")

    st.sidebar.markdown(
        "Enter your AWS Access Key and Secret Key. "
        "These are used ONLY for this session and never saved."
    )

    # Store only in session_state
    st.session_state.aws_access_key = st.sidebar.text_input(
        "Access Key ID",
        value=st.session_state.get("aws_access_key", ""),
        placeholder="AWS_ACCESS_KEY_ID"
    )

    st.session_state.aws_secret_key = st.sidebar.text_input(
        "Secret Access Key",
        value=st.session_state.get("aws_secret_key", ""),
        type="password",
        placeholder="AWS_SECRET_ACCESS_KEY"
    )

    st.session_state.aws_region = st.sidebar.selectbox(
        "AWS Region",
        ["us-east-1", "us-west-2", "eu-west-1", "ap-south-1"],
        index=0 if not st.session_state.get("aws_region")
               else ["us-east-1","us-west-2","eu-west-1","ap-south-1"]
               .index(st.session_state.aws_region)
    )


def main():
    st.set_page_config(page_title="AWS Self-Healing Pipeline", layout="wide")
    st.title("AWS Self-Healing Pipeline ⚙️ + Claude (Bedrock)")

    # Render login section
    aws_credentials_ui()

    # Init pipeline state
    init_pipeline_state()

    # Reset pipeline
    if st.sidebar.button("🔄 Reset Pipeline"):
        reset_pipeline_state()
        st.rerun()

    # Pipeline output
    render_pipeline_section(region=st.session_state.get("aws_region"))

    st.divider()

    # Chat UI
    render_chat_section(region=st.session_state.get("aws_region"))


if __name__ == "__main__":
    main()
