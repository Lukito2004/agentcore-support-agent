# Setup

How to deploy the project into an AWS account, check it with the test scripts, run the apps, and tear it down. Commands are for PowerShell on Windows; the scripts also run in Windows PowerShell 5.1.

The committed configuration points at the author's account. Deploying elsewhere means copying your stack outputs into it (step 3).

## Prerequisites

- An AWS account in `us-east-1` with Bedrock model access to Claude Haiku 4.5, and AWS CLI v2 signed in with rights to deploy CloudFormation, IAM and the services below.
- Node.js 20 or newer, then:

```powershell
npm install -g @aws/agentcore@1.2.0 aws-cdk
```

- [uv](https://docs.astral.sh/uv/); it installs Python 3.14 for each project. Then, in the repository root:

```powershell
uv sync
```

## 1. Deploy the business backend

```powershell
cd infra
uv sync
cdk bootstrap
cdk deploy
cd ..
```

`cdk bootstrap` is needed once per account and region. The stack `SupportAgentBackend` creates the DynamoDB tables, the tool Lambdas, Cognito, the Guardrail, the refund review workflow and the evaluator Lambda, and prints its outputs. Any output can be read later with:

```powershell
uv run python scripts/stack_outputs.py SupportAgentBackend ChatClientId
```

## 2. Load demo data and create a sign-in

```powershell
uv run python scripts/seed_data.py
uv run python scripts/create_user.py --email alex.morgan@example.com --customer-id CUST-1001
uv run python scripts/create_user.py --email sam.rivera@example.com --customer-id CUST-1002
```

`create_user.py` asks for the password at a hidden prompt (at least 12 characters with upper case, lower case and a digit). The second user is only needed by the memory test, which checks that one customer's preference does not reach another.

## 3. Point the agent at your backend

Edit [agentcore/agentcore.json](../agentcore/agentcore.json):

| Stack output | Field |
|---|---|
| `DiscoveryUrl` | every `discoveryUrl` (runtime authorizer, credential, gateway authorizer) |
| `ChatClientId` | the runtime's `allowedClients` |
| `GatewayClientId` | the credential's `clientId` and the gateway's `allowedClients` |
| `GuardrailId`, `GuardrailVersion` | the runtime's `GUARDRAIL_ID` and `GUARDRAIL_VERSION` env vars |
| `ApplyGuardrailPolicyArn` | the runtime's `additionalPolicies` |
| `ReadToolsFunctionArn`, `RefundToolFunctionArn` | the `lambdaArn` of the `customer-orders` and `refunds` targets |
| `RefundArgumentsEvaluatorArn` | the `refund_arguments` evaluator's `lambdaArn` |

Set your account in [agentcore/aws-targets.json](../agentcore/aws-targets.json): `[{"name": "default", "account": "<your account id>", "region": "us-east-1"}]`. The committed copy is empty; `git update-index --skip-worktree agentcore/aws-targets.json` keeps your account out of commits.

## 4. Give the agent its Gateway credential

The secret goes from Cognito straight into the CLI, never onto disk in the repository or into shell history:

```powershell
aws cognito-idp describe-user-pool-client --user-pool-id <UserPoolId> --client-id <GatewayClientId> --query UserPoolClient.ClientSecret --output text | agentcore add credentials oauth --name support-tools-oauth --discovery-url <DiscoveryUrl> --client-id <GatewayClientId> --scopes support-gateway/tools.invoke --client-secret -
```

The CLI keeps it encrypted in `agentcore/.env.local` (gitignored) and stores it in the AgentCore Identity token vault on deploy.

## 5. Deploy the agent, then the policies

The Cedar policies name the Gateway's ARN, which exists only after the first deploy. So deploy without them first:

```powershell
agentcore remove policy --engine support_tools_policies --name allow_read_tools
agentcore remove policy --engine support_tools_policies --name limit_refunds
agentcore deploy
uv run python scripts/stack_outputs.py AgentCore-SupportAgent-default Gateway ArnOutput
```

Put that ARN into both files in [policies](../policies), then add them back and deploy again:

```powershell
agentcore add policy --engine support_tools_policies --name allow_read_tools --description "Read-only tools are always allowed" --statement file://policies/allow_read_tools.cedar --validation-mode fail-on-any-findings
agentcore add policy --engine support_tools_policies --name limit_refunds --description "Refunds up to 1,000 USD" --statement file://policies/limit_refunds.cedar --validation-mode fail-on-any-findings
agentcore deploy
```

Until the policies are back, the engine denies every tool call by default.

## 6. Subscribe an approver

```powershell
uv run python scripts/approve_refund.py subscribe you@example.com
```

Confirm the email AWS sends. Refunds that reach 500 USD on an order are announced there.

## Check it

Each script signs in (password prompt), prints PASS or FAIL per check and can save a log with `-OutFile`. The logs in [docs/evidence](evidence) were made this way.

| Script | Checks |
|---|---|
| `test_sessions.ps1` | sign-in required, session isolation, payload validation |
| `test_scenarios.ps1` | order status, customer info, another customer's order, a small refund |
| `test_memory.ps1 -OtherEmail sam.rivera@example.com` | a preference recalled in a new session, not by another customer |
| `test_policy.ps1 -Mode enforced` | 100 USD allowed; the model's 5,000 USD request denied by the Gateway, checked in its trace; the brief's "ignore previous instructions" sentence; injection; a direct Gateway call denied |
| `test_reliability.ps1` | the same refund twice moves money once, including the brief's `operation-123` key sent twice to the Gateway |
| `test_approval.ps1` | review from 500 USD, approve, reject, optional timeout with `-WaitForTimeout` |
| `test_guardrail.ps1` | attacks and secrets blocked, no false positives |

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test_scenarios.ps1 -Email alex.morgan@example.com
```

Unit tests and lint run without AWS:

```powershell
uv run pytest
uv run ruff check .
```

## Run the apps

```powershell
cd ui
uv sync
uv run streamlit run chat_app.py
```

The chat app opens on http://127.0.0.1:8501. The staff app uses your AWS credentials, in a second terminal:

```powershell
cd ui
uv run streamlit run staff_app.py --server.port 8502
```

## Evaluations and failure drills

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_evals.ps1 -Email alex.morgan@example.com -OutFile docs\evidence\evals.txt
```

The failure drills need fault injection on, and off again afterwards:

```powershell
cd infra
cdk deploy -c fault_injection=enabled
cd ..
powershell -ExecutionPolicy Bypass -File .\scripts\test_failures.ps1 -Email alex.morgan@example.com -OutFile docs\evidence\failure-drills.txt
cd infra
cdk deploy
cd ..
```

The wrong-tool drill swaps two tool descriptions at the Gateway, and back again afterwards:

```powershell
uv run python scripts/toggle_wrong_tool_drill.py on
agentcore deploy
powershell -ExecutionPolicy Bypass -File .\scripts\test_wrong_tool.ps1 -Email alex.morgan@example.com -OutFile docs\evidence\wrong-tool-drill.txt
uv run python scripts/toggle_wrong_tool_drill.py off
agentcore deploy
```

Details: [evaluations.md](evaluations.md), [failure-scenarios.md](failure-scenarios.md).

## Tear down

Delete the agent's stack first, because it uses the backend's Lambdas and guardrail policy:

```powershell
aws cloudformation delete-stack --stack-name AgentCore-SupportAgent-default
aws cloudformation wait stack-delete-complete --stack-name AgentCore-SupportAgent-default
cd infra
cdk destroy
```

Guardrail versions are retained on purpose; delete the guardrail with `aws bedrock delete-guardrail --guardrail-identifier <GuardrailId>`. If the AgentCore Identity credential provider or the runtime's log groups remain, delete them in the console. The CDK bootstrap stack can stay.
