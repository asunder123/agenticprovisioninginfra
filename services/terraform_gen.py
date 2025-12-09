# services/terraform_gen.py

from services.bedrock import call_claude
from services.terraform_cleaner import clean_terraform_code

def generate_terraform(region: str, prompt: str) -> str:

    system_prompt = """
You are an AWS IaC expert.
Generate ONLY Terraform HCL. No markdown. No explanations.
"""

    final_prompt = f"{system_prompt}\nUser Request:\n{prompt}"

    raw_tf = call_claude(region, final_prompt, max_tokens=1200)

    # CLEAN THE OUTPUT
    clean_tf = clean_terraform_code(raw_tf)

    return clean_tf
