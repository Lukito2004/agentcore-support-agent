from aws_cdk import RemovalPolicy
from aws_cdk import aws_dynamodb as dynamodb
from constructs import Construct


def _table(scope: Construct, construct_id: str, partition_key: str, **kwargs) -> dynamodb.TableV2:
    return dynamodb.TableV2(
        scope,
        construct_id,
        partition_key=dynamodb.Attribute(name=partition_key, type=dynamodb.AttributeType.STRING),
        billing=dynamodb.Billing.on_demand(),
        encryption=dynamodb.TableEncryptionV2.aws_managed_key(),
        point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
            point_in_time_recovery_enabled=True
        ),
        # Demo data only; a real system would RETAIN business tables.
        removal_policy=RemovalPolicy.DESTROY,
        **kwargs,
    )


class BusinessTables(Construct):
    """Authoritative business state: customers and orders."""

    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)

        self.customers = _table(self, "Customers", "customer_id")
        self.orders = _table(
            self,
            "Orders",
            "order_id",
            global_secondary_indexes=[
                dynamodb.GlobalSecondaryIndexPropsV2(
                    index_name="by_customer",
                    partition_key=dynamodb.Attribute(
                        name="customer_id", type=dynamodb.AttributeType.STRING
                    ),
                    sort_key=dynamodb.Attribute(
                        name="created_at", type=dynamodb.AttributeType.STRING
                    ),
                )
            ],
        )
