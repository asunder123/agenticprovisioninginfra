from dataclasses import dataclass
from typing import Optional, Any


@dataclass
class PipelineStage:
    id: str
    name: str
    description: str
    status: str = "PENDING"
    last_output: Optional[Any] = None
    error: Optional[str] = None
    fix_suggestion: Optional[str] = None

    def copy(self):
        return PipelineStage(
            id=self.id,
            name=self.name,
            description=self.description,
            status="PENDING",
            last_output=None,
            error=None,
            fix_suggestion=None,
        )


DEFAULT_STAGES = [
    PipelineStage(
        id="check_identity",
        name="Check AWS Identity",
        description="Calls STS GetCallerIdentity to verify AWS credentials."
    ),
    PipelineStage(
        id="list_s3_buckets",
        name="List S3 Buckets",
        description="Lists all S3 buckets."
    ),
    PipelineStage(
        id="bedrock_ping",
        name="Ping Bedrock + Claude",
        description="Calls Claude 3 Haiku through Amazon Bedrock."
    ),
   PipelineStage(
    id="langgraph_provision",
    name="Provision LangGraph Runtime",
    description="Loads your LangGraph file, validates it with Claude, and provisions the workflow runtime."
)

]
