"""Create a sign-in for an existing customer. The password is typed at a hidden prompt.

Usage: uv run python scripts/create_user.py --email alex.morgan@example.com --customer-id CUST-1001
"""

import argparse
import getpass
import sys

import boto3

from stack_outputs import REGION, get_stack_outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--customer-id", required=True, help="e.g. CUST-1001")
    args = parser.parse_args()

    password = getpass.getpass("New password (12+ chars, upper, lower, digit): ")
    if password != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match.")

    cognito = boto3.client("cognito-idp", region_name=REGION)
    pool_id = get_stack_outputs()["UserPoolId"]
    try:
        cognito.admin_create_user(
            UserPoolId=pool_id,
            Username=args.email,
            UserAttributes=[
                {"Name": "email", "Value": args.email},
                {"Name": "email_verified", "Value": "true"},
                {"Name": "custom:customer_id", "Value": args.customer_id},
            ],
            MessageAction="SUPPRESS",  # no invitation email
        )
    except cognito.exceptions.UsernameExistsException:
        sys.exit(f"{args.email} already exists.")
    cognito.admin_set_user_password(
        UserPoolId=pool_id, Username=args.email, Password=password, Permanent=True
    )
    print(f"Created {args.email} linked to {args.customer_id}")


if __name__ == "__main__":
    main()
