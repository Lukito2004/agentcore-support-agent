import logging

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

from guards import add_amount_cents, bind_customer_id

log = logging.getLogger(__name__)


class ToolCallGuard(HookProvider):
    """Rewrites every tool call before it runs: signed-in customer_id, refund amount in cents."""

    def __init__(self, customer_id: str) -> None:
        self.customer_id = customer_id

    def register_hooks(self, registry: HookRegistry, **_kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self._guard)

    def _guard(self, event: BeforeToolCallEvent) -> None:
        tool_use, overridden = bind_customer_id(dict(event.tool_use), self.customer_id)
        if overridden:
            log.warning("Overrode a foreign customer_id in a %s call", tool_use["name"])
        event.tool_use = add_amount_cents(tool_use)
