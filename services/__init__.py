"""
Service integrations for AWS + Bedrock.

aws.py:
    - Session/STS/S3 helpers

bedrock.py:
    - Claude 3 Haiku (Anthropic) Bedrock Runtime client
"""

from .aws import get_boto3_session, check_identity, list_buckets
from .bedrock import call_claude, bedrock_client

__all__ = [
    "get_boto3_session",
    "check_identity",
    "list_buckets",
    "call_claude",
    "bedrock_client",
]
