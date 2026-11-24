import logging

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

from guards import bind_customer_id

log = logging.getLogger(__name__)


class CustomerBindingHook(HookProvider):
    """Rewrites customer_id in every tool call to the signed-in customer before it runs."""

    def __init__(self, customer_id: str) -> None:
        self.customer_id = customer_id

    def register_hooks(self, registry: HookRegistry, **_kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self._bind_customer)

    def _bind_customer(self, event: BeforeToolCallEvent) -> None:
        tool_use, overridden = bind_customer_id(dict(event.tool_use), self.customer_id)
        if overridden:
            log.warning("Overrode a foreign customer_id in a %s call", tool_use["name"])
        event.tool_use = tool_use
