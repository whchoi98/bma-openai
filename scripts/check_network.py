#!/usr/bin/env python3
"""TLS-only endpoint reachability probe; sends no signed API requests or resource data."""
import json
import socket
import ssl
from concurrent.futures import ThreadPoolExecutor

ENDPOINTS = {
    "ec2": "ec2.ap-northeast-2.amazonaws.com",
    "rds": "rds.ap-northeast-2.amazonaws.com",
    "ecs": "ecs.ap-northeast-2.amazonaws.com",
    "lambda": "lambda.ap-northeast-2.amazonaws.com",
    "cloudwatch": "monitoring.ap-northeast-2.amazonaws.com",
}


def check(pair):
    service, hostname = pair
    try:
        with socket.create_connection((hostname, 443), timeout=5) as connection:
            with ssl.create_default_context().wrap_socket(connection, server_hostname=hostname):
                return {"service": service, "endpoint": hostname, "tls_reachable": True}
    except OSError as error:
        return {"service": service, "endpoint": hostname, "tls_reachable": False, "error": type(error).__name__}


if __name__ == "__main__":
    result = {
        "execution_context": "local_process_or_docker_not_deployed_agentcore",
        "method": "DNS_TCP_TLS_only_no_AWS_API",
        "results": list(ThreadPoolExecutor(max_workers=5).map(check, ENDPOINTS.items())),
    }
    print(json.dumps(result, indent=2))
