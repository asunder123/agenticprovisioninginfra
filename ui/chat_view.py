# ui/chat_view.py

import streamlit as st
from services.bedrock import call_claude
from services.terraform_gen import generate_terraform
from services.terraform_exec import run_terraform


def render_chat_section(region: str):

    st.subheader("2️⃣ Chat with Claude (with optional Terraform provisioning)")

    # ---------------------------------------------------------------------
    # Initialize persistent session state values
    # ---------------------------------------------------------------------
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    if "last_tf_code" not in st.session_state:
        st.session_state.last_tf_code = None
    if "last_tf_stdout" not in st.session_state:
        st.session_state.last_tf_stdout = None
    if "last_tf_stderr" not in st.session_state:
        st.session_state.last_tf_stderr = None
    if "last_tf_file" not in st.session_state:
        st.session_state.last_tf_file = None

    # ---------------------------------------------------------------------
    # Render chat history
    # ---------------------------------------------------------------------
    for msg in st.session_state.chat_history:
        role = msg["role"]
        content = msg["content"]

        if role == "user":
            st.markdown(f"**You:** {content}")
        else:
            st.markdown(f"**Claude:** {content}")

    st.markdown("---")

    # ---------------------------------------------------------------------
    # Chat input widgets
    # ---------------------------------------------------------------------
    user_prompt = st.text_area(
        "Type your request:",
        key="chat_input",
        height=100,
        placeholder="e.g. 'Create an S3 bucket with versioning using Terraform'",
    )

    trigger_tf = st.checkbox(
        "Trigger Terraform provisioning from this prompt?",
        value=False,
        help="If checked, Claude will generate Terraform code and terraform init/apply will run automatically."
    )

    # ---------------------------------------------------------------------
    # Chat Form (fixes Streamlit button reliability)
    # ---------------------------------------------------------------------
    with st.form("chat_form", clear_on_submit=True):
        submitted = st.form_submit_button("💬 Ask Claude")

        if submitted:

            if not user_prompt.strip():
                st.warning("Please enter a prompt.")
                return

            # Save user message
            st.session_state.chat_history.append({
                "role": "user",
                "content": user_prompt
            })

            # -----------------------------------------------------------------
            # 1️⃣ Claude response
            # -----------------------------------------------------------------
            with st.spinner("Claude is thinking..."):
                try:
                    answer = call_claude(region, user_prompt, max_tokens=500)
                except Exception as e:
                    answer = f"⚠️ Claude call failed: {e}"

            st.session_state.chat_history.append({
                "role": "assistant",
                "content": answer
            })

            # -----------------------------------------------------------------
            # 2️⃣ Terraform generation + execution (if checkbox enabled)
            # -----------------------------------------------------------------
            if trigger_tf:

                # Generate clean Terraform from Claude
                with st.spinner("Generating Terraform from Claude..."):
                    tf_code = generate_terraform(region, user_prompt)

                st.session_state.last_tf_code = tf_code

                # Run Terraform
                with st.spinner("Running terraform init/apply..."):
                    stdout, stderr, tf_file_path = run_terraform(tf_code)

                st.session_state.last_tf_stdout = stdout
                st.session_state.last_tf_stderr = stderr
                st.session_state.last_tf_file = tf_file_path

            # Rerun UI
            st.experimental_rerun()

    # ---------------------------------------------------------------------
    # Terraform results section
    # ---------------------------------------------------------------------
    if st.session_state.last_tf_code:
        st.markdown("### 🧩 Terraform Code (main.tf)")
        with st.expander("Show Terraform File", expanded=False):
            st.code(st.session_state.last_tf_code, language="hcl")

        # Download button
        if st.session_state.last_tf_file:
            try:
                with open(st.session_state.last_tf_file, "rb") as f:
                    st.download_button(
                        label="⬇ Download main.tf",
                        data=f,
                        file_name="main.tf",
                        mime="text/plain",
                    )
            except:
                st.warning("Could not load generated Terraform file.")

    # ---------------------------------------------------------------------
    # Terraform execution output
    # ---------------------------------------------------------------------
    if st.session_state.last_tf_stdout or st.session_state.last_tf_stderr:
        st.markdown("### 🛠 Terraform Execution Output")

        if st.session_state.last_tf_stdout:
            st.markdown("**STDOUT:**")
            st.code(st.session_state.last_tf_stdout, language="bash")

        if st.session_state.last_tf_stderr:
            st.markdown("**STDERR:**")
            st.code(st.session_state.last_tf_stderr, language="bash")
