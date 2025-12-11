
# services/langgraph.py

import json
from typing import Dict, Any, Callable, Optional
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
            import yaml  # local import to avoid hard dependency if unused
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

    summary = {
        "nodes": len(graph.get("nodes", [])),
        "edges": len(graph.get("edges", [])),
        "metadata": graph.get("metadata", {}),
    }

    return {"status": "PROVISIONED", "summary": summary}


# -----------------------------------------------------------------------------
# Default graph for Terraform self-healing
# -----------------------------------------------------------------------------
def build_default_terraform_graph() -> Dict[str, Any]:
    """
    Minimal agentic graph:
      INIT (runs once per session) -> PLAN
      PLAN success -> APPLY
      PLAN failure -> HEAL -> PLAN
      APPLY success -> END
      APPLY failure -> HEAL -> PLAN
    """
    return {
        "metadata": {
            "name": "TerraformSelfHealing",
            "start": "INIT",
            "max_attempts": 3
        },
        "nodes": [
            {"id": "INIT", "type": "init"},
            {"id": "PLAN", "type": "plan"},
            {"id": "APPLY", "type": "apply"},
            {"id": "HEAL", "type": "heal"},
            {"id": "END",  "type": "end"},
        ],
        "edges": [
            {"from": "INIT",  "to": "PLAN",  "condition": "always"},
            {"from": "PLAN",  "to": "APPLY", "condition": "success"},
            {"from": "PLAN",  "to": "HEAL",  "condition": "failure"},
            {"from": "APPLY", "to": "END",   "condition": "success"},
            {"from": "APPLY", "to": "HEAL",  "condition": "failure"},
            {"from": "HEAL",  "to": "PLAN",  "condition": "always"},
        ],
    }


# -----------------------------------------------------------------------------
# Generic graph executor (callback-based)
# -----------------------------------------------------------------------------
def execute_graph(
    region: str,
    graph: Dict[str, Any],
    callbacks: Dict[str, Callable[..., Dict[str, Any]]],
    initial_context: Dict[str, Any],
    attempt_limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Executes a simple node/edge-driven workflow.
    - `callbacks` maps node.type -> callable(context) -> result dict
    - `initial_context` carries mutable state (e.g., tf code, env)
    - `attempt_limit` caps cycles (esp. healing loops)

    Expected result dict from callbacks:
      {
        "stage": str,          # "init" | "plan" | "apply" | "heal"
        "success": bool,
        "stdout": str,
        "stderr": str,
        "tf": str              # Terraform code used/produced in that step
      }

    Returns:
      {
        "success": bool,
        "attempts": [result dicts...],
        "final_context": {...},
        "error": optional str
      }
    """
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    edges = graph.get("edges", [])
    start = graph.get("metadata", {}).get("start") or (graph["nodes"][0]["id"] if graph.get("nodes") else None)
    max_attempts = attempt_limit or graph.get("metadata", {}).get("max_attempts") or 3

    if not start or start not in nodes:
        return {"success": False, "attempts": [], "final_context": initial_context, "error": "Invalid graph start node"}

    current = start
    attempts = []
    heal_cycles = 0

    while True:
        node = nodes[current]
        node_type = node.get("type", "unknown").lower()

        if node_type == "end":
            return {"success": True, "attempts": attempts, "final_context": initial_context}

        if node_type not in callbacks:
            return {
                "success": False,
                "attempts": attempts,
                "final_context": initial_context,
                "error": f"No callback registered for node type '{node_type}'"
            }

        # Execute node
        result = callbacks[node_type](initial_context)
        # Normalize presence of 'tf'
        if "tf" not in result and "tf_code" in result:
            result["tf"] = result.get("tf_code") or ""

        attempts.append(result)

        # Update context for downstream nodes
        initial_context["last_attempt"] = result
        if "tf" in result and result["tf"] is not None:
            initial_context["tf"] = result["tf"]

        # Bound healing loops
        if node_type == "heal":
            heal_cycles += 1
            if heal_cycles >= max_attempts:
                return {"success": False, "attempts": attempts, "final_context": initial_context, "error": "Max healing attempts reached"}

        # Route to next node
        routed = False
        for e in edges:
            if e.get("from") != current:
                continue
            cond = e.get("condition", "always").lower()
            if cond == "always":
                current = e["to"]
                routed = True
                break
            if cond == "success" and result.get("success", False):
                current = e["to"]
                routed = True
                break
            if cond == "failure" and not result.get("success", False):
                current = e["to"]
                routed = True
                break

        if not routed:
            return {
                "success": False,
                "attempts": attempts,
                "final_context": initial_context,
                "error": f"No edge route matched from node '{current}'"
            }


__all__ = [
    "load_langgraph_definition",
    "validate_graph_with_claude",
    "provision_langgraph",
    "build_default_terraform_graph",
    "execute_graph",
]
