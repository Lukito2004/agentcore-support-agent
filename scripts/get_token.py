"""Sign in as a customer and print the access token (for --bearer-token). Never saved to disk.

Usage: uv run python scripts/get_token.py --email alex.morgan@example.com
"""

import argparse
import getpass
import sys

import boto3

from stack_outputs import REGION, get_stack_outputs


def get_access_token(email: str, password: str) -> str:
    cognito = boto3.client("cognito-idp", region_name=REGION)
    try:
        result = cognito.initiate_auth(
            ClientId=get_stack_outputs()["ChatClientId"],
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": email, "PASSWORD": password},
        )
    except cognito.exceptions.NotAuthorizedException:
        sys.exit("Sign-in failed: wrong email or password.")
    return result["AuthenticationResult"]["AccessToken"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    print(get_access_token(args.email, getpass.getpass("Password: ")))


if __name__ == "__main__":
    main()
