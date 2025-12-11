
# services/terraform_exec.py

import subprocess
import tempfile
import os
import shutil
from pathlib import Path
import streamlit as st

from services.terraform_auto_installer import auto_install_terraform
from services.terraform_cleaner import clean_terraform_code
from services.bedrock import call_claude
from services.logger import get_logger

# Agentic helpers
from services.langgraph import build_default_terraform_graph, execute_graph

logger = get_logger()

GENERATED_DIR = Path("generated")
GENERATED_DIR.mkdir(exist_ok=True)

MAX_HEALING_ATTEMPTS = 6


# ---------------------------------------------------------------------
#  Find Terraform Binary
# ---------------------------------------------------------------------
def find_terraform_binary():
    override = st.session_state.get("terraform_path_override")
    if override and Path(override).exists():
        logger.info(f"Using Terraform override path: {override}")
        return override

    auto_found = shutil.which("terraform")
    if auto_found:
        logger.info(f"Terraform found on PATH: {auto_found}")
        return auto_found

    fixed = [
        "/usr/local/bin/terraform",
        "/usr/bin/terraform",
        "C:\\terraform\\terraform.exe",
        "C:\\Program Files\\Terraform\\terraform.exe",
    ]
    for p in fixed:
        if Path(p).exists():
            logger.info(f"Terraform found at known path: {p}")
            return p

    logger.warning("Terraform not found. It will be installed automatically.")
    return None


# ---------------------------------------------------------------------
#  Save Terraform File
# ---------------------------------------------------------------------
def save_tf_file(tf_code: str) -> Path:
    tf_path = GENERATED_DIR / "main.tf"
    tf_path.write_text(tf_code, encoding="utf-8")
    logger.info(f"Saved Terraform code to {tf_path}")
    return tf_path


# ---------------------------------------------------------------------
#  Run a Terraform stage (init/plan/apply)
# ---------------------------------------------------------------------
def run_stage(cmd, cwd, env, stage_name, tf_code):
    logger.info(f"Running Terraform stage: {stage_name}")
    logger.debug(f"Command: {cmd}")

    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env
    )

    stdout = proc.stdout
    stderr = proc.stderr
    ok = proc.returncode == 0

    if ok:
        logger.info(f"{stage_name} SUCCESS")
    else:
        logger.error(f"{stage_name} FAILED")

    logger.debug(f"{stage_name} STDOUT:\n{stdout}")
    logger.debug(f"{stage_name} STDERR:\n{stderr}")

    # Normalize for UI: always expose 'tf'
    return {
        "stage": stage_name,
        "success": ok,
        "stdout": stdout,
        "stderr": stderr,
        "tf": tf_code
    }


# ========================================================================================
#  LANGGRAPH CALLBACKS — per-stage functions (init/plan/apply/heal)
# ========================================================================================
def make_callbacks(workdir: Path, env: dict):
    """
    Creates node callbacks bound to a working directory and environment.
    Each callback reads/writes `context["tf"]`.
    """

    def init_cb(context):
        tf_code = context.get("tf", "")
        tf_file = Path(workdir, "main.tf")
        tf_file.write_text(tf_code, encoding="utf-8")

        init_done = st.session_state.get("terraform_init_done", False)
        if init_done:
            logger.info("Terraform init previously completed. Skipping init stage.")
            return {
                "stage": "init",
                "success": True,
                "stdout": "Init skipped (already done in this session).",
                "stderr": "",
                "tf": tf_code
            }

        terraform_bin = st.session_state.get("terraform_path_override")
        if not terraform_bin:
            terraform_bin = find_terraform_binary() or auto_install_terraform()
            st.session_state["terraform_path_override"] = terraform_bin

        result = run_stage([terraform_bin, "init", "-input=false"], workdir, env, "init", tf_code)
        if result["success"]:
            st.session_state["terraform_init_done"] = True
            logger.info("Terraform init completed (will not run again this session).")
        return result

    def plan_cb(context):
        tf_code = context.get("tf", "")
        Path(workdir, "main.tf").write_text(tf_code, encoding="utf-8")
        terraform_bin = st.session_state.get("terraform_path_override") or find_terraform_binary() or auto_install_terraform()
        st.session_state["terraform_path_override"] = terraform_bin
        return run_stage([terraform_bin, "plan", "-input=false"], workdir, env, "plan", tf_code)

    def apply_cb(context):
        tf_code = context.get("tf", "")
        Path(workdir, "main.tf").write_text(tf_code, encoding="utf-8")
        terraform_bin = st.session_state.get("terraform_path_override") or find_terraform_binary() or auto_install_terraform()
        st.session_state["terraform_path_override"] = terraform_bin
        return run_stage([terraform_bin, "apply", "-auto-approve", "-input=false"], workdir, env, "apply", tf_code)

    def heal_cb(context):
        tf_code = context.get("tf", "")
        last_attempt = context.get("last_attempt") or {}
        stage = last_attempt.get("stage", "unknown")
        stderr = last_attempt.get("stderr", "")
        stdout = last_attempt.get("stdout", "")

        logger.warning(f"Terraform failed during {stage}. Healing code...")

        healing_prompt = f"""
You are a Terraform and AWS specialist.
Fix ONLY the Terraform HCL.

Rules:
- No markdown
- No explanations
- No backticks
- Return ONLY valid Terraform code

Terraform failed at stage: {stage}

STDERR:
{stderr}

STDOUT:
{stdout}

Current Terraform code:
{tf_code}

Fix EVERYTHING required for terraform init/plan/apply to succeed.
"""
        healed = call_claude(st.session_state.aws_region, healing_prompt, max_tokens=2000)
        cleaned = clean_terraform_code(healed)

        logger.info("Claude returned healed Terraform code.")
        logger.debug(f"Healed Terraform:\n{cleaned}")

        return {
            "stage": "heal",
            "success": True,
            "stdout": "Terraform code healed by Claude",
            "stderr": "",
            "tf": cleaned
        }

    return {
        "init": init_cb,
        "plan": plan_cb,
        "apply": apply_cb,
        "heal": heal_cb
    }


# ========================================================================================
#  High-level Streamlit Wrapper (agentic, graph-driven)
# ========================================================================================
def run_terraform(tf_code: str, graph: dict = None):
    logger.info("Starting agentic (graph-driven) Terraform pipeline...")
    save_tf_file(tf_code)

    terraform_bin = find_terraform_binary() or auto_install_terraform()
    st.session_state["terraform_path_override"] = terraform_bin

    # Reset init flag for a new full run
    st.session_state["terraform_init_done"] = False

    # Build env for Terraform
    env = os.environ.copy()
    env["AWS_ACCESS_KEY_ID"] = st.session_state.get("aws_access_key", "")
    env["AWS_SECRET_ACCESS_KEY"] = st.session_state.get("aws_secret_key", "")
    env["AWS_DEFAULT_REGION"] = st.session_state.get("aws_region", "us-east-1")

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)

        # Graph selection: prefer uploaded graph in session, else arg, else default
        user_graph = graph or st.session_state.get("langgraph_def") or build_default_terraform_graph()
        attempt_cap = user_graph.get("metadata", {}).get("max_attempts", MAX_HEALING_ATTEMPTS)

        callbacks = make_callbacks(workdir, env)

        context = {
            "tf": tf_code,
            "aws_region": st.session_state.get("aws_region", "us-east-1"),
            "last_attempt": None
        }

        exec_result = execute_graph(
            region=st.session_state.get("aws_region", "us-east-1"),
            graph=user_graph,
            callbacks=callbacks,
            initial_context=context,
            attempt_limit=attempt_cap
        )

        attempts = exec_result.get("attempts", [])
        success = exec_result.get("success", False)

        final_tf = context.get("tf", tf_code)
        final_path = save_tf_file(final_tf)

        return {
            "success": success,
            "attempts": attempts,
            "tf_file": str(final_path),
            "graph_used": user_graph.get("metadata", {}).get("name", "TerraformSelfHealing"),
            "error": exec_result.get("error")
        }
