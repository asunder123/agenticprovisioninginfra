
# services/terraform_exec.py
# Fast, local-backend optimized Terraform runner for Streamlit + agentic graph
# Enhancements:
# - SINGLE_FILE_MODE: sanitize workspace so only main.tf is used (avoid duplicates)
# - Pre-write workspace/main.tf before graph runs
# - Plan exit code fix (2 = success/changes)
# - Init retry w/ writable lockfile when provider dependencies change
# - Persistent TF data dir, plugin cache, adaptive parallelism

import subprocess
import os
import shutil
from pathlib import Path
import streamlit as st
import hashlib

from services.terraform_auto_installer import auto_install_terraform
from services.terraform_cleaner import clean_terraform_code
from services.bedrock import call_claude
from services.logger import get_logger

# Agentic helpers
from services.langgraph import build_default_terraform_graph, execute_graph

logger = get_logger()

# ---------------------------------------------------------------------------------------
# Directories and defaults
# ---------------------------------------------------------------------------------------
GENERATED_DIR = Path("generated")
GENERATED_DIR.mkdir(exist_ok=True)

WORKSPACE_DIR = GENERATED_DIR / "workspace"   # single persistent workspace
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

MAIN_TF_PATH = WORKSPACE_DIR / "main.tf"      # canonical tf path used by Terraform

MAX_HEALING_ATTEMPTS = 3
DEFAULT_PARALLELISM = 20          # faster for local state; auto-dials down on throttling
DEFAULT_FAST_MODE = True          # apply directly unless you really need a full drift check

# Workspace policy: keep only main.tf (avoid duplication across runs)
SINGLE_FILE_MODE = True
SAFE_KEEP = {
    "main.tf",                    # our single source of truth
    ".terraform.lock.hcl",        # provider lock
    "terraform.tfstate",
    "terraform.tfstate.backup",
}

# Global Terraform binary cache and throttling detection
TERRAFORM_BIN = None
THROTTLE_PATTERNS = (
    "Throttling",
    "Rate exceeded",
    "RequestLimitExceeded",
    "TooManyRequests",
)

# ---------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------
def _content_hash(text: str) -> str:
    """Stable content hash to skip redundant init/plan/apply when code unchanged."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def maybe_reduce_parallelism(stderr: str):
    """Auto-dial back parallelism if we see throttling patterns in stderr."""
    if not stderr:
        return
    if any(pat in stderr for pat in THROTTLE_PATTERNS):
        current = int(st.session_state.get("tf_parallelism", DEFAULT_PARALLELISM))
        if current > 10:
            st.session_state["tf_parallelism"] = 10
            logger.warning(f"AWS throttling detected; reducing parallelism to 10 from {current}")


def sanitize_workspace(workdir: Path):
    """
    Remove stray HCL files to prevent duplicate loads.
    Preserves .terraform/, lockfile, and state files.
    """
    if not SINGLE_FILE_MODE:
        return
    removed = []
    for pattern in ("*.tf", "*.tf.json"):
        for p in workdir.glob(pattern):
            if p.name in SAFE_KEEP:
                continue
            try:
                p.unlink()
                removed.append(p.name)
            except Exception as e:
                logger.warning(f"Could not remove {p}: {e}")
    if removed:
        logger.info(f"Sanitized workspace; removed files: {', '.join(sorted(set(removed)))}")


# ---------------------------------------------------------------------------------------
# Find Terraform binary (resolve once and cache)
# ---------------------------------------------------------------------------------------
def find_terraform_binary():
    global TERRAFORM_BIN
    # Use cached binary if already resolved
    if TERRAFORM_BIN and Path(TERRAFORM_BIN).exists():
        return TERRAFORM_BIN

    # Session override
    override = st.session_state.get("terraform_path_override")
    if override and Path(override).exists():
        TERRAFORM_BIN = override
        logger.info(f"Using Terraform override path: {override}")
        return TERRAFORM_BIN

    # PATH resolution
    auto_found = shutil.which("terraform")
    if auto_found:
        TERRAFORM_BIN = auto_found
        logger.info(f"Terraform found on PATH: {auto_found}")
        return TERRAFORM_BIN

    # Known locations
    fixed = [
        "/usr/local/bin/terraform",
        "/usr/bin/terraform",
        "C:\\terraform\\terraform.exe",
        "C:\\Program Files\\Terraform\\terraform.exe",
    ]
    for p in fixed:
        if Path(p).exists():
            TERRAFORM_BIN = p
            logger.info(f"Terraform found at known path: {p}")
            return TERRAFORM_BIN

    logger.warning("Terraform not found. It will be installed automatically.")
    return None


# ---------------------------------------------------------------------------------------
# Save Terraform file (for user visibility)
# ---------------------------------------------------------------------------------------
def save_tf_file(tf_code: str) -> Path:
    """Optional: write a preview copy to generated/main.tf for user visibility (not executed)."""
    preview_path = GENERATED_DIR / "main.tf"
    preview_path.write_text(tf_code, encoding="utf-8")
    logger.info(f"Saved Terraform code (preview) to {preview_path}")
    return preview_path


# ---------------------------------------------------------------------------------------
# Environment Setup (fast defaults & persistent data directory)
# ---------------------------------------------------------------------------------------
def make_env():
    env = os.environ.copy()
    env["AWS_ACCESS_KEY_ID"] = st.session_state.get("aws_access_key", "")
    env["AWS_SECRET_ACCESS_KEY"] = st.session_state.get("aws_secret_key", "")
    env["AWS_DEFAULT_REGION"] = st.session_state.get("aws_region", "us-east-1")

    # Proxy pass-through (keep downloads working on corp networks)
    for var in ["HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"]:
        if os.environ.get(var):
            env[var] = os.environ[var]

    # Persistent TF working data (reduces recomputation between runs)
    tf_data = GENERATED_DIR / ".tfdata"
    tf_data.mkdir(parents=True, exist_ok=True)
    env["TF_DATA_DIR"] = str(tf_data)

    # Plugin cache (avoid redownloading providers)
    cache_dir = Path("~/.terraform.d/plugin-cache").expanduser()
    cache_dir.mkdir(parents=True, exist_ok=True)
    env["TF_PLUGIN_CACHE_DIR"] = str(cache_dir)

    # Faster, quieter CLI
    env.setdefault("TF_LOG", "ERROR")
    env["TF_IN_AUTOMATION"] = "1"

    # Conservative AWS SDK retries & disable IMDS probing for speed
    env.setdefault("AWS_RETRY_MODE", "standard")
    env.setdefault("AWS_MAX_ATTEMPTS", "3")
    env.setdefault("AWS_EC2_METADATA_DISABLED", "true")

    # Global default fast flags for plan/apply (explicit args still used below)
    env["TF_CLI_ARGS_plan"]  = "-input=false -no-color -refresh=false -detailed-exitcode -lock=false"
    env["TF_CLI_ARGS_apply"] = "-input=false -no-color -auto-approve -lock=false"
    # NOTE: We intentionally do NOT set TF_CLI_ARGS_init.

    return env


# ---------------------------------------------------------------------------------------
# Run a Terraform stage (init/plan/apply) — non-streaming (faster UI)
# ---------------------------------------------------------------------------------------
def run_stage(cmd, cwd, env, stage_name, tf_code, timeout_sec=900):
    """
    Generic runner. Note: success evaluation for 'plan' is overridden in plan_cb
    to treat exit code 2 (changes present) as success.
    """
    logger.info(f"Running Terraform stage: {stage_name}")
    logger.debug(f"Command: {cmd}")

    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout_sec
    )

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    ok = proc.returncode == 0

    if ok:
        logger.info(f"{stage_name} SUCCESS")
    else:
        logger.error(f"{stage_name} FAILED (exit={proc.returncode})")

    # Minimal UI rendering (avoid per-line updates)
    st.write(f"**{stage_name} output:**")
    if stdout:
        st.code(stdout, language="bash")
    if stderr:
        st.code(stderr, language="bash")

    return {
        "stage": stage_name,
        "success": ok,               # NOTE: may be adjusted by caller (plan_cb)
        "stdout": stdout,
        "stderr": stderr,
        "tf": tf_code,
        "returncode": proc.returncode
    }


# =======================================================================================
# LANGGRAPH CALLBACKS — per-stage functions (init/plan/apply/heal)
# =======================================================================================
def make_callbacks(workdir: Path, env: dict):
    # Faster defaults for local state; will auto-dial down on throttling
    parallelism = int(st.session_state.get("tf_parallelism", DEFAULT_PARALLELISM))
    refresh = bool(st.session_state.get("tf_refresh", False))           # speed-first default
    fast_mode = bool(st.session_state.get("tf_fast_mode", DEFAULT_FAST_MODE))
    tfhash_key = "terraform_last_tf_hash"

    def write_tf(tf_code: str):
        """Ensure only main.tf is present; then (re)write it."""
        workdir.mkdir(parents=True, exist_ok=True)
        sanitize_workspace(workdir)  # <-- remove stray *.tf / *.tf.json
        (workdir / "main.tf").write_text(tf_code, encoding="utf-8")

    def init_cb(context):
        tf_code = context.get("tf", "")
        write_tf(tf_code)  # pre-write & sanitize

        # Skip init if workspace already initialized AND code unchanged
        code_hash = _content_hash(tf_code)
        init_done = st.session_state.get("terraform_init_done", False)
        last_hash = st.session_state.get(tfhash_key)

        if init_done and last_hash == code_hash:
            logger.info("Init skipped: workspace initialized & code unchanged.")
            return {
                "stage": "init",
                "success": True,
                "stdout": "Init skipped (cached).",
                "stderr": "",
                "tf": tf_code
            }

        terraform_bin = st.session_state.get("terraform_path_override")
        if not terraform_bin:
            terraform_bin = find_terraform_binary() or auto_install_terraform()
            st.session_state["terraform_path_override"] = terraform_bin

        # 1) Fast path: local backend, readonly lockfile (avoids unnecessary writes)
        cmd_fast = [
            terraform_bin, "init",
            "-input=false",
            "-no-color",
            "-backend=true",
            "-upgrade=false"
        ]
        res = run_stage(cmd_fast, workdir, env, "init", tf_code)

        # 2) If provider deps changed, re-run with writable lockfile and upgrade
        needs_writable_lock = (
            "Provider dependency changes detected" in (res.get("stderr") or "") or
            "lock file is read-only" in (res.get("stderr") or "")
        )

        if (not res["success"]) and needs_writable_lock:
            logger.info("Re-running init with writable lockfile and -upgrade due to provider changes.")
            cmd_retry = [
                terraform_bin, "init",
                "-input=false",
                "-no-color",
                "-backend=false",
                "-upgrade",              # allow provider constraint reconciliation
                # NOTE: omit -lockfile=readonly so TF can write .terraform.lock.hcl
            ]
            res = run_stage(cmd_retry, workdir, env, "init (retry)", tf_code)

        if res["success"]:
            st.session_state["terraform_init_done"] = True
            st.session_state[tfhash_key] = code_hash
            logger.info("Terraform init completed (cached for this workspace).")
        return res

    def plan_cb(context):
        tf_code = context.get("tf", "")
        write_tf(tf_code)  # ensure only main.tf exists with current code
        terraform_bin = st.session_state.get("terraform_path_override") or find_terraform_binary() or auto_install_terraform()
        st.session_state["terraform_path_override"] = terraform_bin

        # Detailed exit codes gate the apply; lock=false is safe for single-process local state
        cmd = [
            terraform_bin, "plan",
            "-input=false",
            "-no-color",
            "-detailed-exitcode",
            f"-parallelism={parallelism}",
            "-lock=false",
        ]
        if not refresh:
            cmd.append("-refresh=false")

        res = run_stage(cmd, workdir, env, "plan", tf_code)

        # Interpret detailed exit code:
        # 0 -> success, no changes
        # 2 -> success, changes present
        # 1 -> error
        rc = res["returncode"]
        if rc in (0, 2):
            res["success"] = True
        res["detailed_exit_code"] = rc

        maybe_reduce_parallelism(res.get("stderr", ""))
        return res

    def apply_cb(context):
        tf_code = context.get("tf", "")
        write_tf(tf_code)  # ensure only main.tf exists with current code
        terraform_bin = st.session_state.get("terraform_path_override") or find_terraform_binary() or auto_install_terraform()
        st.session_state["terraform_path_override"] = terraform_bin

        # If last plan showed no changes, skip apply entirely
        last_attempt = context.get("last_attempt") or {}
        if last_attempt.get("stage") == "plan":
            dec = last_attempt.get("detailed_exit_code")
            if dec == 0:
                logger.info("Apply skipped: plan shows no changes.")
                return {
                    "stage": "apply",
                    "success": True,
                    "stdout": "Apply skipped (no changes detected).",
                    "stderr": "",
                    "tf": tf_code
                }
            # dec == 2 -> changes; proceed to apply

        # Fast mode: do a micro-plan first if we don't know change status
        if fast_mode and last_attempt.get("stage") != "plan":
            micro = plan_cb({"tf": tf_code})
            if not micro["success"]:
                return {
                    "stage": "apply",
                    "success": False,
                    "stdout": micro.get("stdout", ""),
                    "stderr": micro.get("stderr", ""),
                    "tf": tf_code
                }
            if micro.get("detailed_exit_code") == 0:
                logger.info("Apply skipped: micro-plan found no changes.")
                return {
                    "stage": "apply",
                    "success": True,
                    "stdout": "Apply skipped (no changes).",
                    "stderr": "",
                    "tf": tf_code
                }

        # Apply without lock for local state; optional refresh=false for speed
        cmd = [
            terraform_bin, "apply",
            "-auto-approve",
            "-input=false",
            "-no-color",
            f"-parallelism={parallelism}",
            "-lock=false",
        ]
        if not refresh:
            cmd.append("-refresh=false")  # speeds up; use drift check separately when needed

        res = run_stage(cmd, workdir, env, "apply", tf_code)
        maybe_reduce_parallelism(res.get("stderr", ""))
        return res

    def heal_cb(context):
        tf_code = context.get("tf", "")
        last_attempt = context.get("last_attempt") or {}
        stage = last_attempt.get("stage", "unknown")
        stderr = last_attempt.get("stderr", "")
        stdout = last_attempt.get("stdout", "")

        # Only heal when the previous stage actually failed
        if last_attempt.get("success", True):
            return {
                "stage": "heal",
                "success": True,
                "stdout": "No healing needed (last stage succeeded).",
                "stderr": "",
                "tf": tf_code
            }

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
        healed = call_claude(st.session_state.aws_region, healing_prompt, max_tokens=1500)
        cleaned = clean_terraform_code(healed)

        # Avoid loop if identical
        if cleaned.strip() == tf_code.strip():
            logger.warning("Healed code identical; skipping further heal.")
            return {
                "stage": "heal",
                "success": True,
                "stdout": "Healing produced identical code; skipping.",
                "stderr": "",
                "tf": tf_code
            }

        logger.info("Claude returned healed Terraform code.")
        logger.debug(f"Healed Terraform:\n{cleaned}")

        # Overwrite main.tf immediately and keep workspace sanitized
        write_tf(cleaned)

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


# =======================================================================================
# High-level Streamlit Wrapper (agentic, graph-driven)
# =======================================================================================
def run_terraform(tf_code: str, graph: dict = None):
    logger.info("Starting agentic (graph-driven) Terraform pipeline...")

    # Pre-sanitize and pre-write workspace/main.tf BEFORE graph runs
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    sanitize_workspace(WORKSPACE_DIR)
    MAIN_TF_PATH.write_text(tf_code, encoding="utf-8")

    # Optional preview copy for user visibility (outside workspace)
    current_hash = _content_hash(tf_code)
    if st.session_state.get("terraform_last_tf_hash") != current_hash:
        save_tf_file(tf_code)
        st.session_state["terraform_last_tf_hash"] = current_hash

    terraform_bin = find_terraform_binary() or auto_install_terraform()
    st.session_state["terraform_path_override"] = terraform_bin

    # Single persistent workspace (much faster than temp dirs or hashing)
    workdir = WORKSPACE_DIR

    # Init guard per workspace (do not reset on every run)
    if st.session_state.get("tf_workspace") != str(workdir.resolve()):
        st.session_state["terraform_init_done"] = False
        st.session_state["tf_workspace"] = str(workdir.resolve())

    env = make_env()

    # Graph selection
    user_graph = graph or st.session_state.get("langgraph_def") or build_default_terraform_graph()
    attempt_cap = user_graph.get("metadata", {}).get("max_attempts", MAX_HEALING_ATTEMPTS)

    # Sensible defaults (can be toggled in UI)
    st.session_state.setdefault("tf_parallelism", DEFAULT_PARALLELISM)  # adaptively reduced on throttle
    st.session_state.setdefault("tf_refresh", False)                     # speed-first for local state
    st.session_state.setdefault("tf_fast_mode", DEFAULT_FAST_MODE)

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
    # Ensure final code is present in workspace too
    MAIN_TF_PATH.write_text(final_tf, encoding="utf-8")
    final_path = save_tf_file(final_tf)

    return {
        "success": success,
        "attempts": attempts,
        "tf_file": str(final_path),
        "workspace": st.session_state.get("tf_workspace"),
        "graph_used": user_graph.get("metadata", {}).get("name", "TerraformSelfHealing"),
        "error": exec_result.get("error")
    }
