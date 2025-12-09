import json
import streamlit as st
from services.bedrock import call_claude


def load_langgraph_definition(upload):
    """
    Accept YAML/JSON graph files uploaded from UI.
    """
    if upload is None:
        return None

    content = upload.read().decode("utf-8")

    try:
        if upload.name.endswith(".json"):
            return json.loads(content)

        if upload.name.endswith(".yaml") or upload.name.endswith(".yml"):
            import yaml
            return yaml.safe_load(content)

    except Exception as e:
        st.error(f"Failed to parse graph definition: {e}")
        return None


def validate_graph_with_claude(region, graph):
    """
    Ask Claude to validate the graph logic and provide suggestions.
    """
    prompt = f"""
    You are an expert LangGraph architect.

    Validate the following workflow graph:
    {json.dumps(graph, indent=2)}

    Return:
    - structural issues
    - missing nodes
    - dead-end edges
    - optimization suggestions
    """
    return call_claude(region, prompt, max_tokens=400)


def provision_langgraph(region, graph):
    """
    Simulated provisioning of LangGraph runtime.
    Replace with real deployment (local, ECS, EKS, Lambda).
    """

    if not graph:
        return {"status": "NO_GRAPH", "detail": "No graph loaded"}

    # Future: Convert this to actual runtime provisioning

    # Example: compile summary
    summary = {
        "nodes": len(graph.get("nodes", [])),
        "edges": len(graph.get("edges", [])),
        "metadata": graph.get("metadata", {}),
    }

    return {
        "status": "PROVISIONED",
        "summary": summary,
    }
