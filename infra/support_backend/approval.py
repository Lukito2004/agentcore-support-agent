from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sns as sns
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from constructs import Construct

from support_backend.functions import backend_function


class RefundApproval(Construct):
    """Human review of larger refunds: email an approver, wait for a decision, then apply it."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        orders: dynamodb.ITableV2,
        refunds: dynamodb.ITableV2,
        timeout_minutes: int,
    ) -> None:
        super().__init__(scope, construct_id)
        self.timeout_minutes = timeout_minutes

        # Approvers subscribe with scripts/approve_refund.py, so no email address is in the code.
        self.topic = sns.Topic(
            self, "Topic", display_name="Support agent refund approvals", enforce_ssl=True
        )

        notify = backend_function(
            Construct(self, "Notify"),
            "Refund review: stores the callback token and emails the approver",
            "approval.handler.notify",
            {"REFUNDS_TABLE": refunds.table_name, "TOPIC_ARN": self.topic.topic_arn},
        )
        refunds.grant(notify, "dynamodb:UpdateItem")
        self.topic.grant_publish(notify)

        finalize = backend_function(
            Construct(self, "Finalize"),
            "Refund review: completes, rejects or expires a pending refund",
            "approval.handler.finalize",
            {"REFUNDS_TABLE": refunds.table_name, "ORDERS_TABLE": orders.table_name},
        )
        refunds.grant(finalize, "dynamodb:GetItem", "dynamodb:UpdateItem")
        orders.grant(finalize, "dynamodb:UpdateItem")

        ask_approver = tasks.LambdaInvoke(
            self,
            "AskApprover",
            lambda_function=notify,
            integration_pattern=sfn.IntegrationPattern.WAIT_FOR_TASK_TOKEN,
            payload=sfn.TaskInput.from_object(
                {"token": sfn.JsonPath.task_token, "refund": sfn.JsonPath.entire_payload}
            ),
            task_timeout=sfn.Timeout.duration(Duration.minutes(timeout_minutes)),
            result_path="$.review",
        )

        def apply(decision: str, details_path: str) -> tasks.LambdaInvoke:
            task = tasks.LambdaInvoke(
                self,
                f"Apply{decision.title()}",
                lambda_function=finalize,
                payload=sfn.TaskInput.from_object(
                    {
                        "idempotency_key": sfn.JsonPath.string_at("$.idempotency_key"),
                        "decision": decision,
                        "details": sfn.JsonPath.object_at(details_path),
                    }
                ),
                payload_response_only=True,
            )
            # finalize is safe to run again, so any failure is retried.
            task.add_retry(
                errors=["States.ALL"],
                max_attempts=4,
                interval=Duration.seconds(2),
                backoff_rate=2,
            )
            return task

        # A rejection arrives as the "Rejected" error; anything else (timeout, no email) expires.
        ask_approver.add_catch(
            apply("REJECTED", "$.failure"), errors=["Rejected"], result_path="$.failure"
        )
        ask_approver.add_catch(
            apply("EXPIRED", "$.failure"), errors=["States.ALL"], result_path="$.failure"
        )
        definition = ask_approver.next(apply("APPROVED", "$.review"))

        log_group = logs.LogGroup(
            self,
            "Logs",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.state_machine = sfn.StateMachine(
            self,
            "StateMachine",
            comment="Human review of refunds of 500 USD or more",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            state_machine_type=sfn.StateMachineType.STANDARD,
            timeout=Duration.minutes(timeout_minutes + 10),
            tracing_enabled=True,
            # Execution data holds the callback token and refund details, so it is not logged.
            logs=sfn.LogOptions(
                destination=log_group, level=sfn.LogLevel.ALL, include_execution_data=False
            ),
        )
