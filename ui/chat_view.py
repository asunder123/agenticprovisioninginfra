
# ui/chat_view.py

import os
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
        role = msg.get("role", "assistant")
        content = msg.get("content", "")
        st.markdown(f"**{role.capitalize()}:** {content}")

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
            if not (user_prompt or "").strip():
                st.warning("Please enter a prompt.")
                return

            # Save chat
            st.session_state.chat_history.append({"role": "user", "content": user_prompt})

            # Claude response
            try:
                with st.spinner("Claude is thinking..."):
                    answer = call_claude(region, user_prompt, max_tokens=500)
            except Exception as e:
                answer = f"Sorry, Claude could not process the request. Error: {e}"

            st.session_state.chat_history.append({"role": "assistant", "content": answer})

            # -----------------------------------------------------------------
            # Self-healing Terraform pipeline
            # -----------------------------------------------------------------
            if trigger_tf:
                try:
                    with st.spinner("Generating Terraform (Claude)…"):
                        tf_code = generate_terraform(region, user_prompt)
                except Exception as e:
                    tf_code = None
                    st.error(f"Terraform generation failed: {e}")

                try:
                    if tf_code is not None:
                        with st.spinner("Running Self-Healing Terraform…"):
                            results = run_terraform(tf_code)
                    else:
                        results = {"success": False, "attempts": [], "error": "No Terraform code generated."}
                except Exception as e:
                    results = {"success": False, "attempts": [], "error": f"Terraform execution failed: {e}"}

                st.session_state.tf_heal_results = results

            st.experimental_rerun()

    # -------------------------------------------------------------------------
    # Display Self-Healing Terraform Results
    # -------------------------------------------------------------------------
    results = st.session_state.tf_heal_results
    if isinstance(results, dict) and results:
        st.markdown("## 🤖 Self-Healing Terraform Results")

        # Overall success/failure
        if results.get("success", False):
            st.success("Terraform applied successfully after self-healing!")
        else:
            st.error("Terraform failed after all healing attempts.")
            if results.get("error"):
                st.warning(f"Pipeline error: {results['error']}")

        # Downloadable TF code (final)
        tf_file = results.get("tf_file")
        if tf_file:
            try:
                if os.path.exists(tf_file):
                    with open(tf_file, "rb") as f:
                        st.download_button(
                            "⬇ Download Final main.tf",
                            f,
                            file_name="main.tf",
                            mime="text/plain"
                        )
                else:
                    st.warning(f"Terraform file not found at: {tf_file}")
            except Exception as e:
                st.warning(f"Could not load final Terraform file: {e}")

        st.markdown("### 🔍 Healing Attempts")
        attempts = results.get("attempts") or []

        if not attempts:
            st.info("No healing attempts were recorded.")
        else:
            # -----------------------------------------------------------------
            # Loop through attempts safely
            # -----------------------------------------------------------------
            for idx, att in enumerate(attempts, start=1):
                # Safe extraction with defaults
                stage = att.get("stage", "unknown")
                success = bool(att.get("success", False))
                stdout = att.get("stdout") or ""
                stderr = att.get("stderr") or ""

                # 'tf' key might be missing → fallback to 'terraform' or empty
                tf_code = att.get("tf") or att.get("terraform") or ""

                st.markdown(f"---\n## 🩺 Healing Attempt #{idx}")

                # Attempt status
                if success:
                    st.success(f"Attempt #{idx}: SUCCESS at stage `{stage}` 🎉")
                else:
                    st.error(f"Attempt #{idx}: FAILED at stage `{stage}`")

                # Terraform code used in attempt
                st.markdown("### 🧩 Terraform Code Used in This Attempt")
                with st.expander("Show Terraform (attempt version)", expanded=False):
                    if tf_code.strip():
                        st.code(tf_code, language="hcl")
                    else:
                        st.code("(no terraform code captured for this attempt)")

                # Logs
                st.markdown("### 📄 STDOUT")
                st.code(stdout if stdout.strip() else "(empty)")

                if stderr and stderr.strip():
                    st.markdown("### ⚠️ STDERR")
                    st.code(stderr)

                # If failure → show healing context
                if not success and idx != len(attempts):
                    st.info("Claude attempted to repair the Terraform code for the next retry.")

    st.markdown("---")
