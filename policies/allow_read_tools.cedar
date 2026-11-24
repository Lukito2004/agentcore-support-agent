// Read-only tools are always allowed; the Lambda still checks the order belongs to the customer.
permit (
  principal,
  action in [
    AgentCore::Action::"customer-orders___get_customer",
    AgentCore::Action::"customer-orders___get_order_status"
  ],
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1:230858577630:gateway/supportagent-default-support-tools-heawf1kemt"
);
