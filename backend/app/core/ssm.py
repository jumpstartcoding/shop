"""Load secrets from AWS Systems Manager Parameter Store into the environment.

On Lambda, secrets (database URL, Stripe keys) live as SecureString parameters under one
path, e.g. /shop/prod/DATABASE_URL. They are read once per cold start, before settings are
built, so they never appear in the Lambda console or the CloudFormation template.

The parameter's last path segment is the environment variable name. Parameter Store
standard parameters and their API calls are free.
"""

import os
import re

_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


def load_parameters(path: str, client=None) -> list[str]:
    """Copy every parameter under `path` into os.environ. Returns the names loaded.

    Parameter Store values override environment variables of the same name, so a value can
    be fixed in Parameter Store without redeploying.
    """
    if client is None:
        import boto3

        client = boto3.client("ssm")
    path = "/" + path.strip("/") + "/"
    loaded: list[str] = []
    kwargs = {"Path": path, "WithDecryption": True, "Recursive": False, "MaxResults": 10}
    while True:
        resp = client.get_parameters_by_path(**kwargs)
        for p in resp.get("Parameters", []):
            name = p["Name"][len(path) :]
            if not _NAME.match(name):
                continue  # ignore anything that isn't an UPPER_CASE variable name
            os.environ[name] = p["Value"]
            loaded.append(name)
        token = resp.get("NextToken")
        if not token:
            return sorted(loaded)
        kwargs["NextToken"] = token
