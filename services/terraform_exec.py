# services/terraform_exec.py

import subprocess
import tempfile
import os
import shutil
from pathlib import Path
import streamlit as st
from services.terraform_auto_installer import auto_install_terraform
from services.bedrock import call_claude
from services.terraform_cleaner import clean_terraform_code


GENERATED_DIR = Path("generated")
GENERATED_DIR.mkdir(exist_ok=True)

MAX_HEALING_ATTEMPTS = 3


def find_terraform_binary():
    override = st.session_state.get("terraform_path_override", "")
    if override and Path(override).exists():
        return override

    path = shutil.which("terraform")
    if path:
        return path

    common_paths = [
        "/usr/local/bin/terraform",
        "/usr/bin/terraform",
        "C:\\terraform\\terraform.exe",
        "C:\\Program Files\\Terraform\\terraform.exe",
    ]
    for p in common_paths:
        if Path(p).exists():
            return p

    return None


def save_tf_file(tf_code: str) -> Path:
    tf_path = GENERATED_DIR / "main.tf"
    tf_path.write_text(tf_code, encoding="utf-8")
    return tf_path


def run_step(cmd, cwd, env):
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, env=env
    )
    return proc.stdout, proc.stderr, proc.returncode


def attempt_terraform_once(tf_code: str, terraform_bin: str, env: dict):
    """
    Runs terraform init -> plan -> apply ONCE.
    Returns dict containing stage results.
    """

    with tempfile.TemporaryDirectory() as tmp:
        tmp_tf = Path(tmp) / "main.tf"
        tmp_tf.write_text(tf_code, encoding="utf-8")

        # INIT
        init_out, init_err, init_code = run_step(
            [terraform_bin, "init", "-input=false"],
            tmp,
            env,
        )
        if init_code != 0:
            return {
                "stage": "init",
                "success": False,
                "stdout": init_out,
                "stderr": init_err,
                "tf": tf_code,
            }

        # PLAN
        plan_out, plan_err, plan_code = run_step(
            [terraform_bin, "plan", "-input=false"],
            tmp,
            env,
        )
        if plan_code != 0:
            return {
                "stage": "plan",
                "success": False,
                "stdout": plan_out,
                "stderr": plan_err,
                "tf": tf_code,
            }

        # APPLY
        apply_out, apply_err, apply_code = run_step(
            [terraform_bin, "apply", "-auto-approve", "-input=false"],
            tmp,
            env,
        )
        if apply_code != 0:
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


def heal_terraform_code(tf_code: str, error_stage: str, stdout: str, stderr: str):
    """
    Sends failure details to Claude to self-heal the Terraform.
    """
    healing_prompt = f"""
You are a Terraform and AWS expert. Fix ONLY the Terraform HCL code.

The Terraform operation failed.

Stage: {error_stage}
Error Stderr:
{stderr}
Error Stdout:
{stdout}

Current Terraform Code:
{tf_code}

Fix ALL issues so Terraform will succeed.
Return ONLY clean Terraform HCL.
    """

    healed = call_claude(st.session_state.aws_region, healing_prompt, max_tokens=1500)
    return clean_terraform_code(healed)


def run_terraform(tf_code: str):
    """
    Self-healing Terraform executor:
    init -> plan -> apply
    If any stage fails, agent uses Claude to fix the code, then retries.
    """

    original_tf = tf_code
    save_tf_file(original_tf)

    terraform_bin = find_terraform_binary()
    if terraform_bin is None:
        terraform_bin = auto_install_terraform()
        st.session_state["terraform_path_override"] = terraform_bin

    env = os.environ.copy()
    env["AWS_ACCESS_KEY_ID"] = st.session_state.get("aws_access_key", "")
    env["AWS_SECRET_ACCESS_KEY"] = st.session_state.get("aws_secret_key", "")
    env["AWS_DEFAULT_REGION"] = st.session_state.get("aws_region", "us-east-1")

    healing_attempts = []
    current_tf = original_tf

    for attempt in range(1, MAX_HEALING_ATTEMPTS + 1):

        result = attempt_terraform_once(current_tf, terraform_bin, env)
        healing_attempts.append(result)

        if result["success"]:
            # FINAL SUCCESS
            return {
                "success": True,
                "attempts": healing_attempts,
                "tf_file": save_tf_file(current_tf),
            }

        # Not successful → Heal Terraform
        healed_tf = heal_terraform_code(
            current_tf, result["stage"], result["stdout"], result["stderr"]
        )

        current_tf = healed_tf

    # Final failure after all attempts
    return {
        "success": False,
        "attempts": healing_attempts,
        "tf_file": save_tf_file(current_tf),
    }
