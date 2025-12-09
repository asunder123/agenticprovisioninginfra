
import boto3
import json
import streamlit as st
from botocore.exceptions import BotoCoreError, ClientError

MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"


def bedrock_client(region):
    ak = st.session_state.get("aws_access_key")
    sk = st.session_state.get("aws_secret_key")

    try:
        if ak and sk:
            return boto3.client(
                "bedrock-runtime",
                region_name=region,
                aws_access_key_id=ak,
                aws_secret_access_key=sk,
            )
        return boto3.client("bedrock-runtime", region_name=region)
    except:
        return None


def call_claude(region, prompt, max_tokens=300):
    client = bedrock_client(region)

    if client is None:
        return "❌ Bedrock client could not be created. Check credentials & region."

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{
            "role": "user",
            "content": [{"type": "text", "text": prompt}]
        }],
    }

    try:
        resp = client.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps(body),
        )
        data = json.loads(resp["body"].read())
        return data["content"][0]["text"]

    except ClientError as e:
        return f"❌ Bedrock ClientError:\n{e}"

    except BotoCoreError as e:
        return f"❌ BotoCoreError:\n{e}"

    except Exception as e:
        return f"❌ Unexpected Bedrock Error:\n{e}"
