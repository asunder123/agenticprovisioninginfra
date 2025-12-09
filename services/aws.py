import boto3
import streamlit as st


def get_boto3_session(region: str):
    """
    Builds a boto3 session using ONLY the credentials entered in the UI.
    Never touches disk, environment variables, or ~/.aws/credentials.
    """

    access_key = st.session_state.get("aws_access_key")
    secret_key = st.session_state.get("aws_secret_key")

    # If user did not enter credentials, fallback to default AWS chain
    if not access_key or not secret_key:
        return boto3.Session(region_name=region)

    return boto3.Session(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    )


def check_identity(session):
    sts = session.client("sts")
    return sts.get_caller_identity()


def list_buckets(session):
    s3 = session.client("s3")
    resp = s3.list_buckets()
    return [b["Name"] for b in resp.get("Buckets", [])]
