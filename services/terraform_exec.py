import subprocess
import tempfile
import os
import shutil
from pathlib import Path
import streamlit as st

from services.terraform_auto_installer import auto_install_terraform
from services.bedrock import call_claude
from services.terraform_cleaner import clean_terraform_code
from services.logger import get_logger

logger = get_logger()

GENERATED_DIR = Path("generated")
GENERATED_DIR.mkdir(exist_ok=True)

MAX_HEALING_ATTEMPTS = 3


def find_terraform_binary():
    override = st.session_state.get("terraform_path_override", "")
    if override and Path(override).exists():
        logger.info(f"Using Terraform override: {override}")
        return override

    path = shutil.which("terraform")
    if path:
        logger.info(f"Found Terraform in PATH: {path}")
        return path

    common = [
        "/usr/local/bin/terraform",
        "/usr/bin/terraform",
        "C:\\terraform\\terraform.exe",
        "C:\\Program Files\\Terraform\\terraform.exe",
    ]
    for p in common:
        if Path(p).exists():
            logger.info(f"Found Terraform: {p}")
            return p

    logger.warning("Terraform binary not found in system.")
    return None


def save_tf_file(tf_code: str) -> Path:
    tf_path = GENERATED_DIR / "main.tf"
    tf_path.write_text(tf_code, encoding="utf-8")
    logger.info(f"Terraform code saved to {tf_path}")
    return tf_path


def run_step(cmd, cwd, env, stage_name, tf_code):
    """
    Logs and executes terraform stages separately.
    """
    logger.info(f"Running Terraform stage: {stage_name}")
    logger.debug(f"Command: {cmd}")
    logger.debug(f"TF Code:\n{tf_code}")

    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env
    )

    stdout = proc.stdout
    stderr = proc.stderr
    success = proc.returncode == 0

    # Logging
    if success:
        logger.info(f"{stage_name} succeeded.")
    else:
        logger.error(f"{stage_name} failed.")

    logger.debug(f"{stage_name} STDOUT:\n{stdout}")
    if stderr:
        logger.error(f"{stage_name} STDERR:\n{stderr}")

    return stdout, stderr, success


def attempt_terraform_once(tf_code: str, terraform_bin: str, env: dict):
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "main.tf").write_text(tf_code, encoding="utf-8")

        # INIT
        init_out, init_err, init_ok = run_step(
            [terraform_bin, "init", "-input=false"], tmp, env, "init", tf_code
        )
        if not init_ok:
            return {
                "stage": "init",
                "success": False,
                "stdout": init_out,
                "stderr": init_err,
                "tf": tf_code,
            }

        # PLAN
        plan_out, plan_err, plan_ok = run_step(
            [terraform_bin, "plan", "-input=false"], tmp, env, "plan", tf_code
        )
        if not plan_ok:
            return {
                "stage": "plan",
                "success": False,
                "stdout": plan_out,
                "stderr": plan_err,
                "tf": tf_code,
            }

        # APPLY
        apply_out, apply_err, apply_ok = run_step(
            [terraform_bin, "apply", "-auto-approve", "-input=false"], tmp, env, "apply", tf_code
        )
        if not apply_ok:
            return {
                "stage": "apply",
                "success": False,
                "stdout": apply_out,
                "stderr": apply_err,
                "tf": tf_code,
            }

        return {
            "stage": "apply",
            "success": True,
            "stdout": apply_out,
            "stderr": apply_err,
            "tf": tf_code,
        }


def heal_terraform_code(tf_code: str, stage: str, stdout: str, stderr: str):
    logger.warning(f"Healing Terraform code after failure at stage: {stage}")

    healing_prompt = f"""
You are a Terraform expert. Fix ONLY the Terraform HCL.
No explanations.

Stage failed: {stage}

STDERR:
{stderr}

STDOUT:
{stdout}

Current Terraform code:
{tf_code}

Return ONLY valid Terraform HCL.
"""
    healed = call_claude(st.session_state.aws_region, healing_prompt, max_tokens=2000)
    healed = clean_terraform_code(healed)

    logger.info("Claude produced healed Terraform code.")
    logger.debug(f"Healed TF:\n{healed}")

    return healed


def run_terraform(tf_code: str):
    logger.info("Starting Terraform self-healing workflow.")
    original_tf = tf_code
    save_tf_file(original_tf)

    terraform_bin = find_terraform_binary()
    if terraform_bin is None:
        logger.warning("Terraform not found; installing...")
        terraform_bin = auto_install_terraform()
        st.session_state["terraform_path_override"] = terraform_bin
        logger.info(f"Terraform installed at {terraform_bin}")

    env = os.environ.copy()
    env["AWS_ACCESS_KEY_ID"] = st.session_state.get("aws_access_key", "")
    env["AWS_SECRET_ACCESS_KEY"] = st.session_state.get("aws_secret_key", "")
    env["AWS_DEFAULT_REGION"] = st.session_state.get("aws_region", "us-east-1")

    attempts = []
    current_tf = original_tf

    for attempt in range(1, MAX_HEALING_ATTEMPTS + 1):
        logger.info(f"--- Terraform Attempt {attempt}/{MAX_HEALING_ATTEMPTS} ---")

        result = attempt_terraform_once(current_tf, terraform_bin, env)
        attempts.append(result)

        if result["success"]:
            logger.info("Terraform successfully applied!")
            final_path = save_tf_file(current_tf)
            return {"success": True, "attempts": attempts, "tf_file": str(final_path)}

        # Healing required
        current_tf = heal_terraform_code(
            current_tf, result["stage"], result["stdout"], result["stderr"]
        )

    logger.error("Terraform failed after all healing attempts.")
    final_path = save_tf_file(current_tf)

    return {"success": False, "attempts": attempts, "tf_file": str(final_path)}
