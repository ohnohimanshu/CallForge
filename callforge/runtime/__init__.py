def __getattr__(name: str):
    if name == "AgentRuntime":
        from callforge.runtime.agent_runtime import AgentRuntime
        return AgentRuntime
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["AgentRuntime"]
