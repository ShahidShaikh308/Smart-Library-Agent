"""Safe errors surfaced by the Smart Library request orchestrator."""


class ProviderRequestError(RuntimeError):
    """A provider request failed after configured retry/failover attempts."""


class AgentExecutionError(RuntimeError):
    """A request could not be completed safely by the agent workflow."""
