# services/terraform_cleaner.py

import re


def clean_terraform_code(raw: str) -> str:
    """
    Cleans Claude-generated Terraform and returns valid HCL.
    Removes:
    - markdown fences
    - leading/trailing commentary
    - any text before first terraform { or resource {
    - unicode smart quotes
    """

    if raw is None:
        return ""

    # Normalize line endings
    text = raw.replace("\r\n", "\n")

    # Remove ```terraform or ```hcl fenced blocks
    text = re.sub(r"```[\s\S]*?```", lambda m: m.group(0).replace("```", ""), text)
    text = text.replace("```hcl", "").replace("```terraform", "").replace("```", "")

    # Remove markdown bullets, numbering, explanations
    text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
    text = re.sub(r"(?m)^\s*\d+\.\s+", "", text)

    # Strip unwanted unicode quotes
    text = text.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')

    # Remove everything before real HCL starts
    match = re.search(
        r"(terraform\s*\{)|(provider\s*\"aws\")|(resource\s*\"[A-Za-z0-9_]+\")",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        text = text[match.start():]

    # Trim whitespace
    text = text.strip()

    return text
