# services/terraform_auto_installer.py

import os
import platform
import zipfile
import requests
from pathlib import Path
import streamlit as st

TERRAFORM_VERSION = "1.9.5"   # You may change this


def get_download_url():
    system = platform.system().lower()
    machine = platform.machine().lower()

    # WINDOWS
    if system == "windows":
        return f"https://releases.hashicorp.com/terraform/{TERRAFORM_VERSION}/terraform_{TERRAFORM_VERSION}_windows_amd64.zip"

    # MAC INTEL
    if system == "darwin" and "x86_64" in machine:
        return f"https://releases.hashicorp.com/terraform/{TERRAFORM_VERSION}/terraform_{TERRAFORM_VERSION}_darwin_amd64.zip"

    # MAC APPLE SILICON
    if system == "darwin" and ("arm" in machine or "aarch64" in machine):
        return f"https://releases.hashicorp.com/terraform/{TERRAFORM_VERSION}/terraform_{TERRAFORM_VERSION}_darwin_arm64.zip"

    # LINUX x86_64
    if system == "linux" and ("x86_64" in machine or "amd64" in machine):
        return f"https://releases.hashicorp.com/terraform/{TERRAFORM_VERSION}/terraform_{TERRAFORM_VERSION}_linux_amd64.zip"

    # LINUX ARM64
    if system == "linux" and ("arm" in machine or "aarch64" in machine):
        return f"https://releases.hashicorp.com/terraform/{TERRAFORM_VERSION}/terraform_{TERRAFORM_VERSION}_linux_arm64.zip"

    raise Exception(f"Unsupported platform: {system} {machine}")


def auto_install_terraform() -> str:
    """
    Downloads and installs Terraform into .terraform_bin/ and returns its path.
    """

    bin_dir = Path(".terraform_bin")
    bin_dir.mkdir(exist_ok=True)

    terraform_path = bin_dir / ("terraform.exe" if platform.system().lower() == "windows" else "terraform")

    # Already installed
    if terraform_path.exists():
        return str(terraform_path)

    url = get_download_url()
    zip_path = bin_dir / "terraform.zip"

    # Download
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)

    # Extract ZIP
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(bin_dir)

    # Remove ZIP
    zip_path.unlink(missing_ok=True)

    try:
        terraform_path.chmod(0o755)
    except:
        pass

    return str(terraform_path)
