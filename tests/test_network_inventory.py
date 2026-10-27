"""Fixed AWS control-plane responses; no test can contact AWS."""
import json
from dataclasses import replace
from importlib.util import find_spec

import pytest
from conftest import ACCOUNT, NOW

from aws_inventory.engine import AwsInventory

VPC = "vpc-0123456789abcdef0"
SUBNET = "subnet-0123456789abcdef0"
SG = "sg-0123456789abcdef0"
VOLUME = "vol-0123456789abcdef0"
FILTER = [{"Name": "vpc-id", "Values": [VPC]}]
OWNER_FILTER = [{"Name": "owner-id", "Values": [ACCOUNT]}]
SG_FILTER = [*FILTER, *OWNER_FILTER]


def scoped_inventory(inventory, aws, **settings):
    return AwsInventory(replace(inventory.settings, **settings), session=aws, clock=lambda: NOW)


def checks(row):
    return {check["id"]: check["status"] for check in row["security_checks"]}


def group(permissions):
    return {"GroupId": SG, "VpcId": VPC, "OwnerId": ACCOUNT, "IpPermissions": permissions}


def ingress(*, protocol="tcp", start=22, end=22, ipv4="0.0.0.0/0", ipv6=None):
    result = {"IpProtocol": protocol, "IpRanges": [], "Ipv6Ranges": [], "UserIdGroupPairs": [],
              "PrefixListIds": []}
    if start is not None:
        result["FromPort"] = start
    if end is not None:
        result["ToPort"] = end
    if ipv4 is not None:
        result["IpRanges"] = [{"CidrIp": ipv4, "Description": "DO_NOT_LEAK"}]
    if ipv6 is not None:
        result["Ipv6Ranges"] = [{"CidrIpv6": ipv6, "Description": "DO_NOT_LEAK"}]
    return result


LIST_CASES = [
    ("list_vpcs", {}, "ec2", "describe_vpcs", "Vpcs", {"Filters": OWNER_FILTER, "MaxResults": 50}, "vpc"),
    ("list_security_groups", {"vpc_id": VPC}, "ec2", "describe_security_groups", "SecurityGroups",
     {"Filters": SG_FILTER, "MaxResults": 50}, "vpc"),
    ("list_ebs_volumes", {}, "ec2", "describe_volumes", "Volumes", {"MaxResults": 50}, "ebs"),
    ("list_ecr_repositories", {}, "ecr", "describe_repositories", "repositories",
     {"registryId": ACCOUNT, "maxResults": 50}, "ecr"),
]


@pytest.mark.parametrize("tool,args,service,operation,key,params,envelope", LIST_CASES)
def test_network_empty_response_is_explicit_and_region_scoped(
        inventory, aws, tool, args, service, operation, key, params, envelope):
    aws.stub(service).add_response(operation, {key: []}, params)
    result = inventory.invoke(tool, args)
    assert result["status"] == "empty"
    assert result["pagination_complete"] is True
    assert result["data"] == []
    assert result["service"] == envelope
    assert result["region"] == "ap-northeast-2"
    assert result["account_id"] == ACCOUNT
    assert result["api_calls"][0]["api"] == "GetCallerIdentity"
    assert result["api_calls"][-1]["service"] == service
    assert all(region == ("us-east-1" if name == "sts" else "ap-northeast-2")
               for name, region in aws.regions)


@pytest.mark.parametrize("tool,args,service,operation,key,params,envelope", LIST_CASES)
def test_network_denied_response_is_never_empty(
        inventory, aws, tool, args, service, operation, key, params, envelope):
    aws.stub(service).add_client_error(operation, "AccessDeniedException",
                                       service_message="DO_NOT_LEAK", expected_params=params)
    result = inventory.invoke(tool, args)
    assert result["status"] == "access_denied"
    assert result["permission_denied"] is True
    assert result["pagination_complete"] is False
    assert "DO_NOT_LEAK" not in json.dumps(result)


def test_vpc_pages_are_followed_and_sensitive_metadata_is_removed(inventory, aws):
    aws.stub("ec2").add_response("describe_vpcs", {
        "Vpcs": [{"VpcId": VPC, "State": "available", "CidrBlock": "10.0.0.0/16", "IsDefault": False,
                  "Tags": [{"Key": "Name", "Value": "DO_NOT_LEAK"}], "OwnerId": ACCOUNT}],
        "NextToken": "next",
    }, {"Filters": OWNER_FILTER, "MaxResults": 50})
    aws.stub("ec2").add_response("describe_vpcs", {
        "Vpcs": [{"VpcId": "vpc-0123456789abcdef1", "State": "pending", "OwnerId": ACCOUNT}],
    }, {"Filters": OWNER_FILTER, "MaxResults": 50, "NextToken": "next"})
    result = inventory.invoke("list_vpcs")
    assert result["status"] == "ok"
    assert result["count"] == 2
    assert result["pagination_complete"] is True
    assert result["data"][0]["kind"] == "vpc"
    assert result["data"][0]["vpc_id"] == VPC
    assert result["data"][0]["cidr_block"] == "10.0.0.0/16"
    assert "DO_NOT_LEAK" not in json.dumps(result)
    assert "999988887777" not in json.dumps(result)


def test_failed_later_vpc_page_preserves_observed_rows(inventory, aws):
    aws.stub("ec2").add_response("describe_vpcs", {"Vpcs": [{"VpcId": VPC, "OwnerId": ACCOUNT}],
                                                  "NextToken": "next"},
                                  {"Filters": OWNER_FILTER, "MaxResults": 50})
    aws.stub("ec2").add_client_error("describe_vpcs", "UnauthorizedOperation",
                                       expected_params={"Filters": OWNER_FILTER,
                                                        "MaxResults": 50, "NextToken": "next"})
    result = inventory.invoke("list_vpcs")
    assert result["status"] == "partial"
    assert result["count"] == 1
    assert result["permission_denied"] is True
    assert result["pagination_complete"] is False


def test_network_resource_limit_stops_at_the_global_cap(inventory, aws):
    inventory = scoped_inventory(inventory, aws, max_resources=1)
    aws.stub("ec2").add_response("describe_vpcs", {
        "Vpcs": [{"VpcId": VPC, "OwnerId": ACCOUNT}, {"VpcId": "vpc-0123456789abcdef1", "OwnerId": ACCOUNT}],
        "NextToken": "next",
    }, {"Filters": OWNER_FILTER, "MaxResults": 5})
    result = inventory.invoke("list_vpcs")
    assert result["count"] == 1
    assert result["status"] == "partial"
    assert result["truncated"] is True
    assert result["pagination_complete"] is False


@pytest.mark.parametrize("tool,args", [
    ("get_vpc_topology", {"vpc_id": "arn:aws:ec2:us-east-1:999988887777:vpc/" + VPC}),
    ("get_vpc_topology", {"vpc_id": VPC, "region": "us-east-1"}),
    ("get_vpc_topology", {"vpc_id": "vpc-not-valid"}),
    ("get_vpc_topology", {"vpc_id": 123}),
    ("list_security_groups", {}),
    ("list_security_groups", {"vpc_id": VPC, "operation": "delete_security_group"}),
    ("list_vpcs", {"region": "us-east-1"}),
    ("list_ebs_volumes", {"command": "aws ec2 delete-volume"}),
    ("list_ecr_repositories", {"registryId": "999988887777"}),
])
def test_network_inputs_cannot_change_aws_scope_or_operation(inventory, aws, tool, args):
    result = inventory.invoke(tool, args)
    assert result["status"] == "invalid_input"
    assert [call["api"] for call in result["api_calls"]] == ["GetCallerIdentity"]


def test_account_mismatch_stops_before_any_network_inventory_api(aws):
    from aws_inventory.config import Settings

    aws.identity("999988887777")
    inventory = AwsInventory(Settings(expected_account_id=ACCOUNT), session=aws, clock=lambda: NOW)
    result = inventory.invoke("get_vpc_topology", {"vpc_id": VPC})
    assert result["status"] == "account_mismatch"
    assert result["data"] == []
    assert [call["api"] for call in result["api_calls"]] == ["GetCallerIdentity"]


TOPOLOGY_KINDS = ["vpc", "subnet", "route_table", "security_group", "internet_gateway",
                  "nat_gateway", "vpc_endpoint"]


def topology_tail(aws, *, denied_route_table=False):
    ec2 = aws.stub("ec2")
    ec2.add_response("describe_subnets", {"Subnets": [
        {"SubnetId": SUBNET, "VpcId": VPC, "CidrBlock": "10.0.1.0/24",
         "MapPublicIpOnLaunch": False, "AvailabilityZone": "ap-northeast-2a",
         "Tags": [{"Key": "secret", "Value": "DO_NOT_LEAK"}]},
    ]}, {"Filters": FILTER, "MaxResults": 50})
    route_params = {"Filters": FILTER, "MaxResults": 50}
    if denied_route_table:
        ec2.add_client_error("describe_route_tables", "UnauthorizedOperation",
                             expected_params=route_params)
    else:
        ec2.add_response("describe_route_tables", {"RouteTables": [{
            "RouteTableId": "rtb-0123456789abcdef0", "VpcId": VPC,
            "Associations": [{"SubnetId": SUBNET}, {"Main": True}],
            "Routes": [{"DestinationCidrBlock": "0.0.0.0/0", "GatewayId": "igw-0123456789abcdef0"}],
        }]}, route_params)
    ec2.add_response("describe_security_groups", {"SecurityGroups": [group([])]},
                     {"Filters": SG_FILTER, "MaxResults": 50})
    ec2.add_response("describe_internet_gateways", {"InternetGateways": [{
        "InternetGatewayId": "igw-0123456789abcdef0",
        "Attachments": [{"VpcId": VPC, "State": "available"}],
    }]}, {"Filters": [{"Name": "attachment.vpc-id", "Values": [VPC]}], "MaxResults": 50})
    ec2.add_response("describe_nat_gateways", {"NatGateways": [{
        "NatGatewayId": "nat-0123456789abcdef0", "VpcId": VPC, "SubnetId": SUBNET, "State": "available",
        "NatGatewayAddresses": [{"PublicIp": "192.0.2.1", "PrivateIp": "10.0.1.100"}],
    }]}, {"Filter": FILTER, "MaxResults": 50})
    ec2.add_response("describe_vpc_endpoints", {"VpcEndpoints": [{
        "VpcEndpointId": "vpce-0123456789abcdef0", "VpcId": VPC, "SubnetIds": [SUBNET],
        "VpcEndpointType": "Interface", "State": "available", "PrivateDnsEnabled": True,
        "DnsEntries": [{"DnsName": "DO_NOT_LEAK.example.test", "HostedZoneId": "secret"}],
        "PolicyDocument": "DO_NOT_LEAK",
    }]}, {"Filters": FILTER, "MaxResults": 50})


def test_topology_returns_observed_nodes_and_only_explicit_associations(inventory, aws):
    aws.stub("ec2").add_response("describe_vpcs", {"Vpcs": [{"VpcId": VPC, "OwnerId": ACCOUNT}]},
                                  {"VpcIds": [VPC]})
    topology_tail(aws)
    result = inventory.invoke("get_vpc_topology", {"vpc_id": VPC})
    assert result["status"] == "ok"
    assert result["pagination_complete"] is True
    assert [row["kind"] for row in result["data"]] == TOPOLOGY_KINDS
    assert set(result["scope"]["kind_coverage"].values()) == {"complete"}
    assert result["scope"]["omitted_kinds"] == []
    assert result["scope"]["truncated_kinds"] == []
    assert result["data"][2]["subnet_ids"] == [SUBNET]
    assert result["data"][-2]["subnet_id"] == SUBNET
    assert result["data"][-1]["subnet_ids"] == [SUBNET]
    assert "DO_NOT_LEAK" not in json.dumps(result)
    assert "192.0.2.1" not in json.dumps(result)
    aws.stub("ec2").assert_no_pending_responses()


def test_topology_records_denied_kind_and_continues_other_types(inventory, aws):
    aws.stub("ec2").add_response("describe_vpcs", {"Vpcs": [{"VpcId": VPC, "OwnerId": ACCOUNT}]},
                                  {"VpcIds": [VPC]})
    topology_tail(aws, denied_route_table=True)
    result = inventory.invoke("get_vpc_topology", {"vpc_id": VPC})
    assert result["status"] == "partial"
    assert result["permission_denied"] is True
    assert result["pagination_complete"] is False
    assert result["scope"]["kind_coverage"]["route_table"] == "error"
    assert "route_table" in result["scope"]["omitted_kinds"]
    assert result["scope"]["kind_coverage"]["vpc_endpoint"] == "complete"
    assert len(result["data"]) == 6


def test_topology_does_not_synthesize_a_vpc_or_query_children_when_not_found(inventory, aws):
    aws.stub("ec2").add_response("describe_vpcs", {"Vpcs": []}, {"VpcIds": [VPC]})
    result = inventory.invoke("get_vpc_topology", {"vpc_id": VPC})
    assert result["data"] == []
    assert result["missing_resource_ids"] == [VPC]
    assert set(result["scope"]["omitted_kinds"]) == set(TOPOLOGY_KINDS[1:])
    assert len(result["api_calls"]) == 2
    assert result["pagination_complete"] is False


def test_topology_global_cap_marks_unqueried_kinds(inventory, aws):
    inventory = scoped_inventory(inventory, aws, max_resources=2)
    aws.stub("ec2").add_response("describe_vpcs", {"Vpcs": [{"VpcId": VPC, "OwnerId": ACCOUNT}]},
                                  {"VpcIds": [VPC]})
    aws.stub("ec2").add_response("describe_subnets", {"Subnets": [
        {"SubnetId": SUBNET, "VpcId": VPC}, {"SubnetId": "subnet-0123456789abcdef1", "VpcId": VPC},
    ]}, {"Filters": FILTER, "MaxResults": 5})
    result = inventory.invoke("get_vpc_topology", {"vpc_id": VPC})
    assert result["count"] == 2
    assert result["status"] == "partial"
    assert result["pagination_complete"] is False
    assert result["scope"]["kind_coverage"]["subnet"] == "truncated"
    assert result["scope"]["truncated_kinds"] == ["subnet"]
    assert set(result["scope"]["omitted_kinds"]) == set(TOPOLOGY_KINDS[2:])
    assert len(result["api_calls"]) == 3


@pytest.mark.parametrize("permissions,want", [
    ([], {"sg_no_public_ssh": "pass", "sg_no_public_rdp": "pass", "sg_no_public_all_traffic": "pass"}),
    ([ingress()], {"sg_no_public_ssh": "fail", "sg_no_public_rdp": "pass",
                   "sg_no_public_all_traffic": "pass"}),
    ([ingress(start=3389, end=3389, ipv4=None, ipv6="::/0")],
     {"sg_no_public_ssh": "pass", "sg_no_public_rdp": "fail", "sg_no_public_all_traffic": "pass"}),
    ([ingress(protocol="-1", start=None, end=None)],
     {"sg_no_public_ssh": "fail", "sg_no_public_rdp": "fail", "sg_no_public_all_traffic": "fail"}),
    ([ingress(start=0, end=65535)],
     {"sg_no_public_ssh": "fail", "sg_no_public_rdp": "fail", "sg_no_public_all_traffic": "pass"}),
    ([ingress(ipv4="10.0.0.0/8")],
     {"sg_no_public_ssh": "pass", "sg_no_public_rdp": "pass", "sg_no_public_all_traffic": "pass"}),
])
def test_security_group_checks_include_ipv6_and_port_ranges(inventory, aws, permissions, want):
    aws.stub("ec2").add_response("describe_security_groups", {
        "SecurityGroups": [{**group(permissions), "Description": "DO_NOT_LEAK",
                            "Tags": [{"Key": "secret", "Value": "DO_NOT_LEAK"}]}],
    }, {"Filters": SG_FILTER, "MaxResults": 50})
    result = inventory.invoke("list_security_groups", {"vpc_id": VPC})
    assert checks(result["data"][0]) == want
    assert result["data"][0]["ingress_complete"] is True
    assert "DO_NOT_LEAK" not in json.dumps(result)
    assert all(set(check) == {"id", "status", "severity"} for check in result["data"][0]["security_checks"])


@pytest.mark.parametrize("permissions", [None, [{}], [{"IpProtocol": "tcp", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]])
def test_missing_security_group_evidence_never_passes(inventory, aws, permissions):
    row = {"GroupId": SG, "VpcId": VPC, "OwnerId": ACCOUNT}
    if permissions is not None:
        row["IpPermissions"] = permissions
    aws.stub("ec2").add_response("describe_security_groups", {"SecurityGroups": [row]},
                                  {"Filters": SG_FILTER, "MaxResults": 50})
    result = inventory.invoke("list_security_groups", {"vpc_id": VPC})
    assert set(checks(result["data"][0]).values()) == {"unknown"}
    assert result["data"][0]["ingress_complete"] is False


def test_security_group_nested_sources_are_bounded_and_cannot_hide_an_unknown(inventory, aws):
    permission = ingress(ipv4=None)
    permission["IpRanges"] = [{"CidrIp": f"10.0.0.{n}/32", "Description": "DO_NOT_LEAK"}
                              for n in range(60)]
    aws.stub("ec2").add_response("describe_security_groups", {"SecurityGroups": [group([permission])]},
                                  {"Filters": SG_FILTER, "MaxResults": 50})
    result = inventory.invoke("list_security_groups", {"vpc_id": VPC})
    row = result["data"][0]
    assert len(row["ingress_rules"]) == 50
    assert row["ingress_complete"] is False
    assert set(checks(row).values()) == {"unknown"}
    assert result["truncated"] is True
    assert result["status"] == "partial"


def test_prefix_list_sources_are_unknown_without_extra_queries(inventory, aws):
    permission = ingress(ipv4=None)
    permission["PrefixListIds"] = [{"PrefixListId": "pl-0123456789abcdef0", "Description": "DO_NOT_LEAK"}]
    aws.stub("ec2").add_response("describe_security_groups", {"SecurityGroups": [group([permission])]},
                                  {"Filters": SG_FILTER, "MaxResults": 50})
    result = inventory.invoke("list_security_groups", {"vpc_id": VPC})
    assert checks(result["data"][0])["sg_no_public_ssh"] == "unknown"
    assert len(result["api_calls"]) == 2
    assert "DO_NOT_LEAK" not in json.dumps(result)


@pytest.mark.parametrize("encrypted,want", [(True, "pass"), (False, "fail"), (None, "unknown")])
def test_ebs_encryption_is_evidence_based_and_key_fields_are_omitted(inventory, aws, encrypted, want):
    row = {"VolumeId": VOLUME, "State": "in-use", "VolumeType": "gp3", "Size": 20,
           "AvailabilityZone": "ap-northeast-2a", "KmsKeyId": "DO_NOT_LEAK",
           "SnapshotId": "snap-secret", "Tags": [{"Key": "Name", "Value": "DO_NOT_LEAK"}],
           "Attachments": [{"InstanceId": "i-0123456789abcdef0", "VolumeId": VOLUME,
                            "Device": "/dev/DO_NOT_LEAK", "State": "attached"}]}
    if encrypted is not None:
        row["Encrypted"] = encrypted
    aws.stub("ec2").add_response("describe_volumes", {"Volumes": [row]}, {"MaxResults": 50})
    result = inventory.invoke("list_ebs_volumes")
    assert result["service"] == "ebs"
    assert result["data"][0]["kind"] == "ebs_volume"
    assert result["data"][0]["size_gib"] == 20
    assert checks(result["data"][0])["ebs_encrypted"] == want
    assert "DO_NOT_LEAK" not in json.dumps(result)
    assert "snap-secret" not in json.dumps(result)


def test_ecr_repository_settings_are_not_scan_results_or_endpoint_disclosure(inventory, aws):
    aws.stub("ecr").add_response("describe_repositories", {"repositories": [{
        "repositoryName": "sample/app", "repositoryUri": "DO_NOT_LEAK.example.test/sample/app",
        "repositoryArn": f"arn:aws:ecr:ap-northeast-2:{ACCOUNT}:repository/sample/app",
        "imageTagMutability": "IMMUTABLE", "imageScanningConfiguration": {"scanOnPush": False},
        "encryptionConfiguration": {"encryptionType": "KMS", "kmsKey": "DO_NOT_LEAK"},
    }]}, {"registryId": ACCOUNT, "maxResults": 50})
    result = inventory.invoke("list_ecr_repositories")
    assert result["data"][0]["id"] == "sample/app"
    assert result["data"][0]["kind"] == "ecr_repository"
    assert checks(result["data"][0]) == {"ecr_encrypted": "pass", "ecr_immutable_tags": "pass",
                                        "ecr_scan_on_push": "fail"}
    assert "DO_NOT_LEAK" not in json.dumps(result)


def test_missing_ecr_settings_remain_unknown(inventory, aws):
    aws.stub("ecr").add_response("describe_repositories", {"repositories": [{"repositoryName": "sample"}]},
                                  {"registryId": ACCOUNT, "maxResults": 50})
    result = inventory.invoke("list_ecr_repositories")
    assert set(checks(result["data"][0]).values()) == {"unknown"}


@pytest.mark.parametrize("tool,service,operation,key,params,first,second,token", [
    ("list_ebs_volumes", "ec2", "describe_volumes", "Volumes", {"MaxResults": 50},
     {"VolumeId": VOLUME}, {"VolumeId": "vol-0123456789abcdef1"}, "NextToken"),
    ("list_ecr_repositories", "ecr", "describe_repositories", "repositories",
     {"registryId": ACCOUNT, "maxResults": 50},
     {"repositoryName": "first"}, {"repositoryName": "second"}, "nextToken"),
])
def test_storage_and_registry_pagination_uses_their_sdk_tokens(
        inventory, aws, tool, service, operation, key, params, first, second, token):
    aws.stub(service).add_response(operation, {key: [first], token: "next"}, params)
    aws.stub(service).add_response(operation, {key: [second]}, {**params, token: "next"})
    result = inventory.invoke(tool)
    assert result["count"] == 2
    assert result["pagination_complete"] is True
    assert len(result["api_calls"]) == 3


def test_network_page_limit_is_honored(inventory, aws):
    inventory = scoped_inventory(inventory, aws, max_pages=1)
    aws.stub("ec2").add_response("describe_vpcs", {"Vpcs": [{"VpcId": VPC, "OwnerId": ACCOUNT}],
                                                  "NextToken": "next"},
                                  {"Filters": OWNER_FILTER, "MaxResults": 50})
    result = inventory.invoke("list_vpcs")
    assert result["status"] == "partial"
    assert result["count"] == 1
    assert result["pagination_complete"] is False
    assert len(result["api_calls"]) == 2


def test_topology_root_denial_records_every_unobserved_kind(inventory, aws):
    aws.stub("ec2").add_client_error("describe_vpcs", "UnauthorizedOperation",
                                       expected_params={"VpcIds": [VPC]})
    result = inventory.invoke("get_vpc_topology", {"vpc_id": VPC})
    assert result["status"] == "access_denied"
    assert result["data"] == []
    assert set(result["scope"]["omitted_kinds"]) == set(TOPOLOGY_KINDS)
    assert result["scope"]["kind_coverage"]["vpc"] == "error"
    assert result["pagination_complete"] is False


def test_observed_security_failure_survives_truncation(inventory, aws):
    permissions = [ingress()] + [ingress(ipv4="10.0.0.0/8") for _ in range(50)]
    aws.stub("ec2").add_response("describe_security_groups", {"SecurityGroups": [group(permissions)]},
                                  {"Filters": SG_FILTER, "MaxResults": 50})
    result = inventory.invoke("list_security_groups", {"vpc_id": VPC})
    row = result["data"][0]
    assert checks(row)["sg_no_public_ssh"] == "fail"
    assert checks(row)["sg_no_public_rdp"] == "unknown"
    assert row["ingress_complete"] is False


@pytest.mark.parametrize("mutability,want", [
    ("IMMUTABLE", "pass"), ("MUTABLE", "fail"),
    ("IMMUTABLE_WITH_EXCLUSION", "fail"), ("MUTABLE_WITH_EXCLUSION", "fail"),
])
def test_ecr_mutability_exceptions_do_not_claim_full_immutability(inventory, aws, mutability, want):
    aws.stub("ecr").add_response("describe_repositories", {"repositories": [
        {"repositoryName": "sample", "imageTagMutability": mutability},
    ]}, {"registryId": ACCOUNT, "maxResults": 50})
    result = inventory.invoke("list_ecr_repositories")
    assert checks(result["data"][0])["ecr_immutable_tags"] == want


def test_network_sample_adapter_is_fixed_and_rejects_unowned_operations():
    assert find_spec("aws_inventory.network_samples") is not None
    from aws_inventory.network_samples import response

    first = response("ec2", "describe_vpcs", {"MaxResults": 50})
    vpc_id = first["Vpcs"][0]["VpcId"]
    first["Vpcs"][0]["VpcId"] = "mutated"
    assert response("ec2", "describe_vpcs", {"MaxResults": 50})["Vpcs"][0]["VpcId"] == vpc_id
    assert response("ec2", "describe_vpcs", {"VpcIds": [VPC]}) == {"Vpcs": []}
    with pytest.raises(KeyError):
        response("ec2", "delete_vpc", {"VpcId": vpc_id})
    with pytest.raises(KeyError):
        response("s3", "describe_vpcs", {})


def test_sample_network_responses_conform_to_real_sdk_models(aws):
    assert find_spec("aws_inventory.network_samples") is not None
    from aws_inventory.network_samples import response

    vpc_id = response("ec2", "describe_vpcs", {})["Vpcs"][0]["VpcId"]
    operations = [
        ("ec2", "describe_vpcs", {}),
        ("ec2", "describe_subnets", {}),
        ("ec2", "describe_route_tables", {}),
        ("ec2", "describe_security_groups", {}),
        ("ec2", "describe_internet_gateways", {}),
        ("ec2", "describe_nat_gateways", {}),
        ("ec2", "describe_vpc_endpoints", {}),
        ("ec2", "describe_volumes", {}),
        ("ecr", "describe_repositories", {}),
    ]
    for service, operation, params in operations:
        result = response(service, operation, params)
        aws.stub(service).add_response(operation, result, params)
        assert result
    filtered = response("ec2", "describe_security_groups", {
        "Filters": [{"Name": "vpc-id", "Values": [VPC]}],
    })
    assert filtered["SecurityGroups"] == []
    assert vpc_id != VPC


@pytest.mark.parametrize("owner,code", [
    ("999988887777", "ResourceOwnerMismatch"),
    (None, "ResourceOwnerUnknown"),
])
def test_vpc_list_rejects_foreign_or_unknown_resource_owner(inventory, aws, owner, code):
    row = {"VpcId": VPC, "CidrBlock": "10.99.0.0/16"}
    if owner is not None:
        row["OwnerId"] = owner
    aws.stub("ec2").add_response("describe_vpcs", {"Vpcs": [row]})
    result = inventory.invoke("list_vpcs")
    assert result["data"] == []
    assert result["account_id"] == ACCOUNT
    assert result["status"] == "api_error"
    assert result["errors"][0]["code"] == code
    assert result["errors"][0]["kind"] == "out_of_scope"
    assert result["pagination_complete"] is False
    assert "999988887777" not in json.dumps(result)
    assert "10.99.0.0/16" not in json.dumps(result)


@pytest.mark.parametrize("owner,code", [
    ("999988887777", "ResourceOwnerMismatch"),
    (None, "ResourceOwnerUnknown"),
])
def test_root_vpc_owner_is_checked_before_any_child_query(inventory, aws, owner, code):
    row = {"VpcId": VPC, "CidrBlock": "10.99.0.0/16"}
    if owner is not None:
        row["OwnerId"] = owner
    aws.stub("ec2").add_response("describe_vpcs", {"Vpcs": [row]}, {"VpcIds": [VPC]})
    result = inventory.invoke("get_vpc_topology", {"vpc_id": VPC})
    assert result["data"] == []
    assert result["account_id"] == ACCOUNT
    assert result["status"] == "invalid_input"
    assert result["errors"][0]["code"] == code
    assert len(result["api_calls"]) == 2
    assert result["scope"]["kind_coverage"]["vpc"] == "error"
    assert "999988887777" not in json.dumps(result)


@pytest.mark.parametrize("owner,code", [
    ("999988887777", "ResourceOwnerMismatch"),
    (None, "ResourceOwnerUnknown"),
])
def test_sg_ownership_is_validated_independently_of_vpc_owner(inventory, aws, owner, code):
    row = group([ingress()])
    row.pop("OwnerId", None)
    if owner is not None:
        row["OwnerId"] = owner
    aws.stub("ec2").add_response("describe_security_groups", {"SecurityGroups": [row]})
    result = inventory.invoke("list_security_groups", {"vpc_id": VPC})
    assert result["data"] == []
    assert result["account_id"] == ACCOUNT
    assert result["status"] == "api_error"
    assert result["errors"][0]["code"] == code
    assert len(result["api_calls"]) == 2
    assert "999988887777" not in json.dumps(result)


def test_mixed_vpc_owners_preserve_only_authorized_rows(inventory, aws):
    aws.stub("ec2").add_response("describe_vpcs", {"Vpcs": [
        {"VpcId": VPC, "OwnerId": ACCOUNT},
        {"VpcId": "vpc-0123456789abcdef1", "OwnerId": "999988887777", "CidrBlock": "10.99.0.0/16"},
    ]})
    result = inventory.invoke("list_vpcs")
    assert result["status"] == "partial"
    assert [row["id"] for row in result["data"]] == [VPC]
    assert result["pagination_complete"] is False
    assert "10.99.0.0/16" not in json.dumps(result)


@pytest.mark.parametrize("start,end,complete", [
    (None, None, True), (None, -1, False), (-1, None, False), (-1, 0, False),
    (256, -1, False), (128, -1, True),
])
def test_icmpv6_optional_type_and_code_follow_sdk_semantics(inventory, aws, start, end, complete):
    row = {**group([ingress(protocol="icmpv6", start=start, end=end, ipv4=None, ipv6="::/0")]),
           "OwnerId": ACCOUNT}
    aws.stub("ec2").add_response("describe_security_groups", {"SecurityGroups": [row]})
    result = inventory.invoke("list_security_groups", {"vpc_id": VPC})
    assert result["data"][0]["ingress_complete"] is complete
    assert set(checks(result["data"][0]).values()) == ({"pass"} if complete else {"unknown"})


@pytest.mark.parametrize("foreign_kind", [
    "subnet", "route_table", "security_group", "internet_gateway", "vpc_endpoint",
])
def test_topology_omits_foreign_child_owners_and_preserves_owned_vpc(inventory, aws, foreign_kind):
    aws.stub("ec2").add_response("describe_vpcs", {"Vpcs": [{"VpcId": VPC, "OwnerId": ACCOUNT}]},
                                  {"VpcIds": [VPC]})
    children = [
        ("subnet", "describe_subnets", "Subnets", {"SubnetId": SUBNET, "VpcId": VPC},
         {"Filters": FILTER, "MaxResults": 50}),
        ("route_table", "describe_route_tables", "RouteTables",
         {"RouteTableId": "rtb-0123456789abcdef0", "VpcId": VPC},
         {"Filters": FILTER, "MaxResults": 50}),
        ("security_group", "describe_security_groups", "SecurityGroups", group([]),
         {"Filters": SG_FILTER, "MaxResults": 50}),
        ("internet_gateway", "describe_internet_gateways", "InternetGateways",
         {"InternetGatewayId": "igw-0123456789abcdef0", "Attachments": [{"VpcId": VPC}]},
         {"Filters": [{"Name": "attachment.vpc-id", "Values": [VPC]}], "MaxResults": 50}),
        ("nat_gateway", "describe_nat_gateways", "NatGateways", {},
         {"Filter": FILTER, "MaxResults": 50}),
        ("vpc_endpoint", "describe_vpc_endpoints", "VpcEndpoints",
         {"VpcEndpointId": "vpce-0123456789abcdef0", "VpcId": VPC},
         {"Filters": FILTER, "MaxResults": 50}),
    ]
    for kind, operation, key, row, params in children:
        rows = [{**row, "OwnerId": "999988887777"}] if kind == foreign_kind else []
        aws.stub("ec2").add_response(operation, {key: rows}, params)
    result = inventory.invoke("get_vpc_topology", {"vpc_id": VPC})
    assert result["status"] == "partial"
    assert result["account_id"] == ACCOUNT
    assert [row["id"] for row in result["data"]] == [VPC]
    assert result["scope"]["kind_coverage"][foreign_kind] == "error"
    assert result["errors"][0]["code"] == "ResourceOwnerMismatch"
    assert "999988887777" not in json.dumps(result)


def test_ebs_rejects_foreign_owner_when_sdk_supplies_it(inventory, aws):
    aws.stub("ec2").add_response("describe_volumes", {"Volumes": [
        {"VolumeId": VOLUME, "OwnerId": "999988887777", "Encrypted": True},
    ]}, {"MaxResults": 50})
    result = inventory.invoke("list_ebs_volumes")
    assert result["data"] == []
    assert result["status"] == "api_error"
    assert result["account_id"] == ACCOUNT
    assert result["errors"][0]["code"] == "ResourceOwnerMismatch"
    assert result["pagination_complete"] is False


def test_sample_owner_filter_selects_only_its_synthetic_account():
    from aws_inventory.config import SAMPLE_ACCOUNT
    from aws_inventory.network_samples import response

    own = [{"Name": "owner-id", "Values": [SAMPLE_ACCOUNT]}]
    foreign = [{"Name": "owner-id", "Values": [ACCOUNT]}]
    assert len(response("ec2", "describe_vpcs", {"Filters": own})["Vpcs"]) == 1
    assert response("ec2", "describe_vpcs", {"Filters": foreign})["Vpcs"] == []
    groups = response("ec2", "describe_security_groups", {"Filters": own})["SecurityGroups"]
    assert len(groups) == 2
    assert all(row["OwnerId"] == SAMPLE_ACCOUNT for row in groups)


@pytest.mark.parametrize("value", ["bad", False, None, 1.5])
def test_invalid_present_icmpv6_fields_do_not_count_as_omitted(value):
    from aws_inventory.network_inventory import _security_group

    row = _security_group(group([{
        "IpProtocol": "icmpv6", "FromPort": value, "ToPort": value,
        "Ipv6Ranges": [{"CidrIpv6": "::/0"}],
    }]))
    assert row["ingress_complete"] is False
    assert {check["status"] for check in row["security_checks"]} == {"unknown"}


def test_api_budget_stops_before_issuing_another_sdk_request(inventory):
    from aws_inventory.engine import MAX_API_CALLS, Observation, QueryStopped

    obs = Observation(inventory.settings, "get_vpc_topology", "vpc", inventory.clock())
    obs.result["api_calls"] = [{} for _ in range(MAX_API_CALLS)]
    with pytest.raises(QueryStopped):
        inventory.call(obs, "ec2", "DescribeSubnets", lambda: pytest.fail("SDK must not be called"))
    assert len(obs.result["api_calls"]) == MAX_API_CALLS
    assert obs.result["truncated"] is True
    assert obs.result["errors"][-1]["code"] == "ApiCallLimitReached"
