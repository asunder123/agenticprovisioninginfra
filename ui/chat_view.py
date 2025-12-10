# ui/chat_view.py

import streamlit as st
from services.bedrock import call_claude
from services.terraform_gen import generate_terraform
from services.terraform_exec import run_terraform


def render_chat_section(region: str):

    st.subheader("💬 Claude Chat + Self-Healing Terraform Agent")

    # -------------------------------------------------------------------------
    # Init session state
    # -------------------------------------------------------------------------
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    if "tf_heal_results" not in st.session_state:
        st.session_state.tf_heal_results = None

    # -------------------------------------------------------------------------
    # Display chat history
    # -------------------------------------------------------------------------
    for msg in st.session_state.chat_history:
        role = msg["role"]
        st.markdown(f"**{role.capitalize()}:** {msg['content']}")

    st.markdown("---")

    # -------------------------------------------------------------------------
    # Chat input section
    # -------------------------------------------------------------------------
    user_prompt = st.text_area(
        "Type your request:",
        height=120,
        placeholder="e.g. Deploy an S3 bucket with versioning using Terraform"
    )

    trigger_tf = st.checkbox(
        "Trigger Self-Healing Terraform agent?",
        value=False,
        help="Claude will generate Terraform, validate it, self-heal errors, and apply infra automatically."
    )

    # -------------------------------------------------------------------------
    # Chat submit button
    # -------------------------------------------------------------------------
    with st.form("chat_form", clear_on_submit=True):
        submitted = st.form_submit_button("💬 Ask Claude")

        if submitted:
            if not user_prompt.strip():
                st.warning("Please enter a prompt.")
                return

            # Save chat
            st.session_state.chat_history.append({"role": "user", "content": user_prompt})

            # Claude response
            with st.spinner("Claude is thinking..."):
                answer = call_claude(region, user_prompt, max_tokens=500)

            st.session_state.chat_history.append({"role": "assistant", "content": answer})

            # -----------------------------------------------------------------
            # Self-healing Terraform pipeline
            # -----------------------------------------------------------------
            if trigger_tf:
                with st.spinner("Generating Terraform (Claude)…"):
                    tf_code = generate_terraform(region, user_prompt)

                with st.spinner("Running Self-Healing Terraform…"):
                    results = run_terraform(tf_code)

                st.session_state.tf_heal_results = results

            st.experimental_rerun()

    # -------------------------------------------------------------------------
    # Display Self-Healing Terraform Results
    # -------------------------------------------------------------------------
    if st.session_state.tf_heal_results:

        results = st.session_state.tf_heal_results

        st.markdown("## 🤖 Self-Healing Terraform Results")

        if results["success"]:
            st.success("Terraform applied successfully after self-healing!")
        else:
            st.error("Terraform failed after all healing attempts.")

        # Downloadable TF code
        if results["tf_file"]:
            try:
                with open(results["tf_file"], "rb") as f:
                    st.download_button(
                        "⬇ Download Final main.tf",
                        f,
                        file_name="main.tf",
                        mime="text/plain"
                    )
            except:
                st.warning("Could not load final Terraform file.")

        st.markdown("### 🔍 Healing Attempts")
        attempts = results["attempts"]

        # ---------------------------------------------------------------------
        # Loop through attempts
        # ---------------------------------------------------------------------
        for idx, att in enumerate(attempts, start=1):
            stage = att["stage"]
            success = att["success"]
            stdout = att["stdout"]
            stderr = att["stderr"]
            tf_code = att["tf"]

            st.markdown(f"---\n## 🩺 Healing Attempt #{idx}")

            # Attempt status
            if success:
                st.success(f"Attempt #{idx}: SUCCESS at stage `{stage}` 🎉")
            else:
                st.error(f"Attempt #{idx}: FAILED at stage `{stage}`")

            st.markdown("### 🧩 Terraform Code Used in This Attempt")
            with st.expander("Show Terraform (attempt version)", expanded=False):
                st.code(tf_code, language="hcl")

            # Logs
            st.markdown("### 📄 STDOUT")
            st.code(stdout or "(empty)")

            if stderr:
                st.markdown("### ⚠️ STDERR")
                st.code(stderr)

            # If failure → show healing context
            if not success and idx != len(attempts):
                st.info("Claude attempted to repair the Terraform code for the next retry.")

    st.markdown("---")
