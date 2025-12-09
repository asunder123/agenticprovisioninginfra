import traceback
import streamlit as st

from services.aws import (
    get_boto3_session,
    check_identity,
    list_buckets,
)

from services.bedrock import call_claude
from services.langgraph import (
    load_langgraph_definition,
    validate_graph_with_claude,
    provision_langgraph,
)

from services.terraform_gen import generate_terraform
from services.terraform_exec import run_terraform

from pipeline.stages import DEFAULT_STAGES


# ===================================================================
# GLOBAL MEMORY FOR LANGGRAPH + TF
# ===================================================================

LANGGRAPH_MEMORY = {
    "graph": None,
    "terraform_prompt": None,
    "terraform_generated": None,
}


# ===================================================================
# UPLOAD HOOK FOR YAML/JSON LANGGRAPH FILES
# ===================================================================

def inject_uploaded_graph(upload):
    graph = load_langgraph_definition(upload)
    LANGGRAPH_MEMORY["graph"] = graph
    return graph


# ===================================================================
# CORE PIPELINE EXECUTION ENGINE
# ===================================================================

def run_pipeline(region: str, mode: str):

    # Ensure pipeline stages exist
    if "pipeline_stages" not in st.session_state:
        st.error("Pipeline state not initialized")
        return []

    session = get_boto3_session(region)

    # -------------------------------------------------------------------
    # CHAT → LANGGRAPH → TERRAFORM HOOK
    # -------------------------------------------------------------------
    if st.session_state.get("trigger_langgraph_from_chat"):

        user_prompt = st.session_state.get("terraform_prompt")

        # 1️⃣ Claude generates Terraform
        terraform_code = generate_terraform(region, user_prompt)
        LANGGRAPH_MEMORY["terraform_prompt"] = user_prompt
        LANGGRAPH_MEMORY["terraform_generated"] = terraform_code

        # 2️⃣ Auto-generate a simple LangGraph runtime definition
        LANGGRAPH_MEMORY["graph"] = {
            "metadata": {"name": "terraform_deployment_graph"},
            "nodes": [
                {"id": "tf_generate", "type": "task", "description": "Generate TF"},
                {"id": "tf_apply", "type": "task", "description": "Apply TF"},
            ],
            "edges": [
                {"source": "tf_generate", "target": "tf_apply"}
            ]
        }

        # Reset trigger
        st.session_state["trigger_langgraph_from_chat"] = False


    # ===================================================================
    # EXECUTE PIPELINE STAGES
    # ===================================================================
    for idx, stage in enumerate(st.session_state.pipeline_stages):

        # Skip logic
        if mode == "failed_only" and stage.status != "FAILED":
            continue
        if mode == "from_first_pending" and stage.status == "SUCCESS":
            continue

        try:
            stage.status = "RUNNING"
            st.session_state.pipeline_stages[idx] = stage

            # ===========================================================
            #  STAGE IMPLEMENTATIONS
            # ===========================================================

            # 1. Identity Check
            if stage.id == "check_identity":
                stage.last_output = check_identity(session)

            # 2. List S3 Buckets
            elif stage.id == "list_s3_buckets":
                stage.last_output = list_buckets(session)

            # 3. Bedrock Ping
            elif stage.id == "bedrock_ping":
                stage.last_output = call_claude(region, "Say hello from AWS pipeline.")

            # 4. LANGGRAPH PROVISIONING (NEW!)
            elif stage.id == "langgraph_provision":

                graph = LANGGRAPH_MEMORY.get("graph")
                tf_code = LANGGRAPH_MEMORY.get("terraform_generated")

                if not graph:
                    raise Exception("No LangGraph definition provided or generated")

                # Validate graph using Claude
                validation = validate_graph_with_claude(region, graph)

                # Provision graph (local simulation)
                lg_result = provision_langgraph(region, graph)

                # Terraform apply (if exists)
                if tf_code:
                    terraform_out = run_terraform(tf_code)
                else:
                    terraform_out = "No Terraform code generated."

                stage.last_output = {
                    "graph_validation": validation,
                    "langgraph_provisioning": lg_result,
                    "terraform_generated": tf_code,
                    "terraform_output": terraform_out,
                }

            # ===========================================================
            #  SUCCESS CASE
            # ===========================================================
            stage.status = "SUCCESS"
            st.session_state.pipeline_stages[idx] = stage

        except Exception as e:
            # ===========================================================
            #  FAILURE CASE (SELF-HEALING)
            # ===========================================================
            traceback_str = traceback.format_exc()

            stage.status = "FAILED"
            stage.error = traceback_str

            heal_prompt = f"""
            AWS Self-Healing Pipeline Stage Failure

            Stage ID: {stage.id}
            Stage Name: {stage.name}

            Error:
            {traceback_str}

            Provide:
            - Root cause (bullet points)
            - Specific AWS fixes
            - Terraform/IaC fixes (if related)
            - Any code changes required
            """

            stage.fix_suggestion = call_claude(region, heal_prompt)

            st.session_state.pipeline_stages[idx] = stage

            # Stop pipeline on failure
            break

    return st.session_state.pipeline_stages
