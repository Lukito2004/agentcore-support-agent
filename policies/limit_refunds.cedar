// Refunds up to 1,000 USD only; amount_cents is set by the agent's code, not by the model.
// A call without amount_cents, or above the limit, matches no permit and is denied by default.
permit (
  principal,
  action == AgentCore::Action::"refunds___refund_customer",
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1:230858577630:gateway/supportagent-default-support-tools-heawf1kemt"
)
when { context.input has amount_cents && context.input.amount_cents <= 100000 };
