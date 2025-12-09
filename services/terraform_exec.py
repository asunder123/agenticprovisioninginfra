# services/terraform_exec.py

import subprocess
import tempfile
import os
import shutil
from pathlib import Path
import streamlit as st
from services.terraform_auto_installer import auto_install_terraform


GENERATED_DIR = Path("generated")
GENERATED_DIR.mkdir(exist_ok=True)


def find_terraform_binary():
    if "terraform_path_override" in st.session_state:
        override = st.session_state["terraform_path_override"]
        if override and Path(override).exists():
            return override

    t = shutil.which("terraform")
    if t:
        return t

    win_paths = [
        r"C:\Program Files\Terraform\terraform.exe",
        r"C:\terraform\terraform.exe",
        rf"C:\Users\{os.getlogin()}\AppData\Local\Programs\Terraform\terraform.exe",
    ]
    for p in win_paths:
        if Path(p).exists():
            return p

    unix_paths = [
        "/usr/local/bin/terraform",
        "/usr/bin/terraform",
        "/opt/homebrew/bin/terraform",
    ]
    for p in unix_paths:
        if Path(p).exists():
            return p

    return None


def save_tf_file(tf_code: str) -> Path:
    tf_path = GENERATED_DIR / "main.tf"
    tf_path.write_text(tf_code, encoding="utf-8")
    return tf_path


def run_terraform(tf_code: str):
    """
    Saves main.tf and runs TF using environment variables for AWS credentials.
    """

    tf_local_path = save_tf_file(tf_code)

    terraform_bin = find_terraform_binary()
    if terraform_bin is None:
        try:
            terraform_bin = auto_install_terraform()
            st.success(f"Terraform auto-installed at: {terraform_bin}")
            st.session_state["terraform_path_override"] = terraform_bin
        except Exception as e:
            return "", f"Terraform auto-install failed:\n{e}", str(tf_local_path)

    # ✅ Inject AWS credentials for Terraform
    env = os.environ.copy()
    env["AWS_ACCESS_KEY_ID"] = st.session_state.get("aws_access_key", "")
    env["AWS_SECRET_ACCESS_KEY"] = st.session_state.get("aws_secret_key", "")
    env["AWS_DEFAULT_REGION"] = st.session_state.get("aws_region", "us-east-1")

    if not env["AWS_ACCESS_KEY_ID"]:
        return "", "❌ No AWS access key provided in UI.", str(tf_local_path)

    if not env["AWS_SECRET_ACCESS_KEY"]:
        return "", "❌ No AWS secret key provided in UI.", str(tf_local_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        tf_temp = Path(tmpdir) / "main.tf"
        tf_temp.write_text(tf_code, encoding="utf-8")

        # terraform init
        init_proc = subprocess.run(
            [terraform_bin, "init", "-input=false"],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,               # 👈 Inject AWS creds
        )

        if init_proc.returncode != 0:
            return init_proc.stdout, init_proc.stderr, str(tf_local_path)

        # terraform apply
        apply_proc = subprocess.run(
            [terraform_bin, "apply", "-auto-approve", "-input=false"],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,               # 👈 Inject AWS creds
        )

        return apply_proc.stdout, apply_proc.stderr, str(tf_local_path)
