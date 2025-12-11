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

logger = get_logger()

GENERATED_DIR = Path("generated")
GENERATED_DIR.mkdir(exist_ok=True)

MAX_HEALING_ATTEMPTS = 3


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

    return {
        "stage": stage_name,
        "success": ok,
        "stdout": stdout,
        "stderr": stderr,
        "tf_code": tf_code
    }


# ========================================================================================
# 🔥 LANGGRAPH TOOL — run_terraform_once (init only once, plan/apply always)
# ========================================================================================
def run_terraform_once(tf_code: str):
    """
    New behavior:
    - init runs ONLY ONE TIME per session
    - plan/apply run on every retry
    - if apply fails, retry starts at plan
    - if plan fails, retry starts at plan
    """

    terraform_bin = find_terraform_binary()
    if not terraform_bin:
        terraform_bin = auto_install_terraform()
        st.session_state["terraform_path_override"] = terraform_bin

    env = os.environ.copy()
    env["AWS_ACCESS_KEY_ID"] = st.session_state.get("aws_access_key", "")
    env["AWS_SECRET_ACCESS_KEY"] = st.session_state.get("aws_secret_key", "")
    env["AWS_DEFAULT_REGION"] = st.session_state.get("aws_region", "us-east-1")

    # Track whether init already executed
    init_done = st.session_state.get("terraform_init_done", False)

    with tempfile.TemporaryDirectory() as tmp:
        tf_file = Path(tmp, "main.tf")
        tf_file.write_text(tf_code, encoding="utf-8")

        # ----------------------------------------------------
        # INIT: Only run on first attempt
        # ----------------------------------------------------
        if not init_done:
            init_result = run_stage(
                [terraform_bin, "init", "-input=false"],
                tmp,
                env,
                "init",
                tf_code,
            )
            if not init_result["success"]:
                return init_result

            st.session_state["terraform_init_done"] = True
            logger.info("Terraform init completed (will not run again).")

        # ----------------------------------------------------
        # PLAN: Always run before apply
        # ----------------------------------------------------
        plan_result = run_stage(
            [terraform_bin, "plan", "-input=false"],
            tmp,
            env,
            "plan",
            tf_code,
        )
        if not plan_result["success"]:
            return plan_result  # healing → retry from plan

        # ----------------------------------------------------
        # APPLY
        # ----------------------------------------------------
        apply_result = run_stage(
            [terraform_bin, "apply", "-auto-approve", "-input=false"],
            tmp,
            env,
            "apply",
            tf_code,
        )
        return apply_result


# ========================================================================================
# 🔥 LANGGRAPH TOOL — heal_terraform
# ========================================================================================
def heal_terraform(tf_code: str, stage: str, stderr: str, stdout: str):
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

    return cleaned


# ========================================================================================
# 🔥 High-level Streamlit Wrapper (auto-heal loop)
# ========================================================================================
def run_terraform(tf_code: str):
    logger.info("Starting self-healing Terraform pipeline...")
    save_tf_file(tf_code)

    terraform_bin = find_terraform_binary() or auto_install_terraform()
    st.session_state["terraform_path_override"] = terraform_bin

    # Reset init flag for new full run
    st.session_state["terraform_init_done"] = False

    attempts = []
    current_tf = tf_code

    for attempt in range(1, MAX_HEALING_ATTEMPTS + 1):
        logger.info(f"=== Attempt {attempt}/{MAX_HEALING_ATTEMPTS} ===")

        result = run_terraform_once(current_tf)
        attempts.append(result)

        if result["success"]:
            logger.info("Terraform successfully applied.")
            final = save_tf_file(current_tf)
            return {
                "success": True,
                "attempts": attempts,
                "tf_file": str(final)
            }

        # Heal
        current_tf = heal_terraform(
            current_tf,
            result["stage"],
            result["stderr"],
            result["stdout"]
        )

    logger.error("Terraform failed even after all healing cycles.")
    final = save_tf_file(current_tf)

    return {
        "success": False,
        "attempts": attempts,
        "tf_file": str(final)
    }
