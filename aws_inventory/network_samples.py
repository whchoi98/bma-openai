"""Synthetic, deterministic network fixtures; no clients, sockets, or credentials."""
from copy import deepcopy

from .config import SAMPLE_ACCOUNT

VPC = "vpc-00000000000000001"
SUBNET_A = "subnet-00000000000000001"
SUBNET_B = "subnet-00000000000000002"
SG_A = "sg-00000000000000001"
SG_B = "sg-00000000000000002"

_FIXTURES = {
    ("ec2", "describe_vpcs"): ("Vpcs", [
        {"VpcId": VPC, "State": "available", "CidrBlock": "10.0.0.0/16",
         "IsDefault": False, "InstanceTenancy": "default", "OwnerId": SAMPLE_ACCOUNT},
    ]),
    ("ec2", "describe_subnets"): ("Subnets", [
        {"SubnetId": SUBNET_A, "VpcId": VPC, "OwnerId": SAMPLE_ACCOUNT,
         "State": "available", "CidrBlock": "10.0.1.0/24",
         "AvailabilityZone": "ap-northeast-2a", "AvailableIpAddressCount": 240, "MapPublicIpOnLaunch": True},
        {"SubnetId": SUBNET_B, "VpcId": VPC, "OwnerId": SAMPLE_ACCOUNT,
         "State": "available", "CidrBlock": "10.0.2.0/24",
         "AvailabilityZone": "ap-northeast-2c", "AvailableIpAddressCount": 240, "MapPublicIpOnLaunch": False},
    ]),
    ("ec2", "describe_route_tables"): ("RouteTables", [
        {"RouteTableId": "rtb-00000000000000001", "VpcId": VPC, "OwnerId": SAMPLE_ACCOUNT,
         "Associations": [{"SubnetId": SUBNET_A, "Main": False}],
         "Routes": [{"DestinationCidrBlock": "0.0.0.0/0", "GatewayId": "igw-00000000000000001",
                     "State": "active"}]},
    ]),
    ("ec2", "describe_security_groups"): ("SecurityGroups", [
        {"GroupId": SG_A, "VpcId": VPC, "OwnerId": SAMPLE_ACCOUNT, "IpPermissions": [
            {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
            {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
        ]},
        {"GroupId": SG_B, "VpcId": VPC, "OwnerId": SAMPLE_ACCOUNT, "IpPermissions": [
            {"IpProtocol": "tcp", "FromPort": 5432, "ToPort": 5432, "UserIdGroupPairs": [{"GroupId": SG_A}]},
        ]},
    ]),
    ("ec2", "describe_internet_gateways"): ("InternetGateways", [
        {"InternetGatewayId": "igw-00000000000000001", "OwnerId": SAMPLE_ACCOUNT,
         "Attachments": [{"VpcId": VPC, "State": "available"}]},
    ]),
    ("ec2", "describe_nat_gateways"): ("NatGateways", [
        {"NatGatewayId": "nat-00000000000000001", "VpcId": VPC, "SubnetId": SUBNET_A,
         "State": "available", "ConnectivityType": "public"},
    ]),
    ("ec2", "describe_vpc_endpoints"): ("VpcEndpoints", [
        {"VpcEndpointId": "vpce-00000000000000001", "VpcId": VPC, "OwnerId": SAMPLE_ACCOUNT,
         "State": "available",
         "VpcEndpointType": "Interface", "SubnetIds": [SUBNET_B], "PrivateDnsEnabled": True},
    ]),
    ("ec2", "describe_volumes"): ("Volumes", [
        {"VolumeId": "vol-00000000000000001", "OwnerId": SAMPLE_ACCOUNT, "State": "in-use", "VolumeType": "gp3",
         "Size": 20, "Encrypted": True, "AvailabilityZone": "ap-northeast-2a",
         "Iops": 3000, "Throughput": 125, "MultiAttachEnabled": False,
         "Attachments": [{"InstanceId": "i-00000000000000001", "State": "attached"}]},
        {"VolumeId": "vol-00000000000000002", "OwnerId": SAMPLE_ACCOUNT,
         "State": "available", "VolumeType": "gp3",
         "Size": 10, "Encrypted": False, "AvailabilityZone": "ap-northeast-2c",
         "Iops": 3000, "Throughput": 125, "MultiAttachEnabled": False, "Attachments": []},
    ]),
    ("ecr", "describe_repositories"): ("repositories", [
        {"repositoryName": "sample/api", "imageTagMutability": "IMMUTABLE",
         "imageScanningConfiguration": {"scanOnPush": True},
         "encryptionConfiguration": {"encryptionType": "AES256"}},
        {"repositoryName": "sample/worker", "imageTagMutability": "MUTABLE",
         "imageScanningConfiguration": {"scanOnPush": False},
         "encryptionConfiguration": {"encryptionType": "KMS"}},
    ]),
}


def response(service, operation, params):
    """Return a fresh SDK-shaped response, or raise KeyError for an unowned API."""
    key, rows = _FIXTURES[(service, operation)]
    rows = deepcopy(rows)
    if operation == "describe_vpcs" and "VpcIds" in params:
        rows = [row for row in rows if row["VpcId"] in params["VpcIds"]]
    for selected in params.get("Filters", params.get("Filter", [])):
        name, values = selected.get("Name"), selected.get("Values", [])
        if name == "vpc-id":
            rows = [row for row in rows if row.get("VpcId") in values]
        elif name == "owner-id":
            rows = [row for row in rows if row.get("OwnerId") in values]
        elif name == "attachment.vpc-id":
            rows = [row for row in rows if any(a["VpcId"] in values for a in row.get("Attachments", []))]
        else:
            raise ValueError("Unsupported sample filter.")
    if operation == "describe_repositories" and params.get("registryId", SAMPLE_ACCOUNT) != SAMPLE_ACCOUNT:
        rows = []
    token_name = "nextToken" if service == "ecr" else "NextToken"
    token = params.get(token_name, "sample-0")
    if not isinstance(token, str) or not token.startswith("sample-") or not token[7:].isdigit():
        raise ValueError("Invalid sample pagination token.")
    offset = int(token[7:])
    limit = params.get("maxResults" if service == "ecr" else "MaxResults", 50)
    if type(limit) is not int or limit < 1:
        raise ValueError("Invalid sample page size.")
    result = {key: rows[offset:offset + limit]}
    if offset + limit < len(rows):
        result[token_name] = f"sample-{offset + limit}"
    return result
