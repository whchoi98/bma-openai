"""Bounded network, EBS, and ECR configuration reads through the shared engine."""
from __future__ import annotations

import re
from ipaddress import ip_network
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from .normalize import timestamp

MAX_NESTED = 50
TOPOLOGY_KINDS = (
    "vpc", "subnet", "route_table", "security_group", "internet_gateway", "nat_gateway", "vpc_endpoint",
)


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class VpcArguments(Arguments):
    vpc_id: Annotated[str, Field(pattern=r"^vpc-(?:[0-9a-f]{8}|[0-9a-f]{17})$")]


TOOL_SCHEMAS = {
    "list_vpcs": ("vpc", Arguments, "List bounded VPC configuration in the verified account and Seoul."),
    "get_vpc_topology": (
        "vpc", VpcArguments,
        "Read observed VPC, subnet, route table, security group, gateway, and endpoint associations. "
        "Returns per-kind coverage; does not assess connectivity or application health.",
    ),
    "list_security_groups": (
        "vpc", VpcArguments,
        "Read bounded ingress configuration for one VPC, including unknown or truncated security checks.",
    ),
    "list_ebs_volumes": (
        "ebs", Arguments, "Read bounded EBS configuration and encryption flags; no disk or snapshot contents.",
    ),
    "list_ecr_repositories": (
        "ecr", Arguments,
        "Read bounded private ECR repository configuration, without image contents or repository URLs.",
    ),
}

# Top-level row keys for the public evidence allowlist. Nested fields have separate
# allowlists in the consumer; no raw AWS dictionaries are included here.
DATA_FIELDS = {
    "kind", "id", "vpc_id", "subnet_id", "subnet_ids", "state", "cidr_block", "is_default",
    "instance_tenancy", "availability_zone", "available_ip_address_count", "map_public_ip_on_launch",
    "main", "route_count", "relationships_complete", "relationships_truncated", "ingress_rules",
    "ingress_complete", "ingress_truncated", "security_checks", "connectivity_type", "endpoint_type",
    "private_dns_enabled", "volume_type", "size_gib", "encrypted", "iops", "throughput_mibps",
    "multi_attach_enabled", "attached_instance_ids", "attachments_complete", "attachments_truncated",
    "created_at", "image_tag_mutability", "scan_on_push", "encryption_type",
}


def _boolean(value):
    return value if type(value) is bool else None


def _integer(value):
    return value if type(value) is int else None


def _text(value):
    return value if isinstance(value, str) and len(value) <= 256 else None


def _identifier(value, prefix):
    if isinstance(value, str) and re.fullmatch(rf"{prefix}-(?:[0-9a-f]{{8}}|[0-9a-f]{{17}})", value):
        return value
    return None


def _cidr(value, version=None):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        network = ip_network(value, strict=False)
    except ValueError:
        return None
    return str(network) if version is None or network.version == version else None


def _check(check_id, value, severity="medium"):
    return {"id": check_id, "status": "pass" if value is True else "fail" if value is False else "unknown",
            "severity": severity}


def _id_list(values, prefix):
    if not isinstance(values, list):
        return [], False, False
    result = []
    complete = len(values) <= MAX_NESTED
    for value in values[:MAX_NESTED]:
        identifier = _identifier(value, prefix)
        if identifier is None:
            complete = False
        elif identifier not in result:
            result.append(identifier)
    return result, complete, len(values) > MAX_NESTED


def _vpc(row):
    identifier = _identifier(row.get("VpcId"), "vpc")
    return {
        "kind": "vpc", "id": identifier, "vpc_id": identifier, "state": _text(row.get("State")),
        "cidr_block": _cidr(row.get("CidrBlock"), 4), "is_default": _boolean(row.get("IsDefault")),
        "instance_tenancy": _text(row.get("InstanceTenancy")),
    }


def _subnet(row):
    return {
        "kind": "subnet", "id": _identifier(row.get("SubnetId"), "subnet"),
        "vpc_id": _identifier(row.get("VpcId"), "vpc"), "state": _text(row.get("State")),
        "cidr_block": _cidr(row.get("CidrBlock"), 4), "availability_zone": _text(row.get("AvailabilityZone")),
        "available_ip_address_count": _integer(row.get("AvailableIpAddressCount")),
        "map_public_ip_on_launch": _boolean(row.get("MapPublicIpOnLaunch")),
    }


def _route_table(row):
    associations = row.get("Associations")
    values = None
    if isinstance(associations, list):
        values = [a.get("SubnetId") for a in associations[:MAX_NESTED]
                  if isinstance(a, dict) and "SubnetId" in a]
    subnet_ids, complete, truncated = _id_list(values, "subnet")
    if isinstance(associations, list) and len(associations) > MAX_NESTED:
        complete, truncated = False, True
    main = any(a.get("Main") is True for a in associations[:MAX_NESTED]
               if isinstance(a, dict)) if isinstance(associations, list) else None
    return {
        "kind": "route_table", "id": _identifier(row.get("RouteTableId"), "rtb"),
        "vpc_id": _identifier(row.get("VpcId"), "vpc"), "subnet_ids": subnet_ids, "main": main,
        "route_count": len(row["Routes"]) if isinstance(row.get("Routes"), list) else None,
        "relationships_complete": complete, "relationships_truncated": truncated,
    }


def _protocol(permission):
    value = permission.get("IpProtocol")
    names = {"-1": "all", "6": "tcp", "17": "udp", "1": "icmp", "58": "icmpv6"}
    if not isinstance(value, str):
        return None
    if value in names:
        return names[value]
    if value in {"tcp", "udp", "icmp", "icmpv6"}:
        return value
    if value.isascii() and value.isdigit() and len(value) <= 3 and 0 <= int(value) <= 255:
        return str(int(value))
    return None


def _ports_complete(protocol, start, end, *, omitted=False):
    if protocol is None:
        return False
    if protocol in {"tcp", "udp"}:
        return start is not None and end is not None and 0 <= start <= end <= 65535
    if protocol == "icmpv6" and start is None and end is None:
        return omitted  # Only genuinely absent fields mean all ICMPv6 types/codes.
    if protocol in {"icmp", "icmpv6"}:
        return (start is not None and end is not None and -1 <= start <= 255 and -1 <= end <= 255
                and (start != -1 or end == -1))
    return True  # All protocols and other protocol numbers do not use port ranges.


def _source(source_type, value):
    if source_type in {"ipv4", "ipv6"}:
        source = _cidr(value, 4 if source_type == "ipv4" else 6)
        return source, ip_network(source).prefixlen == 0 if source else None
    if source_type == "security_group":
        source = _identifier(value, "sg")
        return source, False if source else None
    if source_type == "prefix_list":
        # No extra prefix-list reads: the referenced contents were not observed.
        return _identifier(value, "pl"), None
    return None, None


def _ingress(permissions):
    if not isinstance(permissions, list):
        return [], False, False
    rules, complete, truncated = [], True, False
    source_fields = (
        ("IpRanges", "CidrIp", "ipv4"), ("Ipv6Ranges", "CidrIpv6", "ipv6"),
        ("UserIdGroupPairs", "GroupId", "security_group"), ("PrefixListIds", "PrefixListId", "prefix_list"),
    )
    for permission in permissions:
        if len(rules) >= MAX_NESTED:
            complete, truncated = False, True
            break
        permission = permission if isinstance(permission, dict) else {}
        protocol = _protocol(permission)
        start, end = _integer(permission.get("FromPort")), _integer(permission.get("ToPort"))
        complete = complete and _ports_complete(
            protocol, start, end, omitted="FromPort" not in permission and "ToPort" not in permission
        )
        count_before = len(rules)
        for list_key, value_key, source_type in source_fields:
            sources = permission.get(list_key, [])
            if not isinstance(sources, list):
                complete = False
                continue
            for raw_source in sources:
                if len(rules) >= MAX_NESTED:
                    complete, truncated = False, True
                    break
                value = raw_source.get(value_key) if isinstance(raw_source, dict) else None
                source, unrestricted = _source(source_type, value)
                complete = complete and source is not None and unrestricted is not None
                rules.append({
                    "protocol": protocol, "from_port": start, "to_port": end, "source_type": source_type,
                    "source": source, "unrestricted": unrestricted,
                })
            if truncated:
                break
        if len(rules) == count_before:
            complete = False
            rules.append({
                "protocol": protocol, "from_port": start, "to_port": end,
                "source_type": "unknown", "source": None, "unrestricted": None,
            })
        if truncated:
            break
    return rules, complete, truncated


def _sg_checks(rules, complete):
    results = []
    for check_id, port in (("sg_no_public_ssh", 22), ("sg_no_public_rdp", 3389),
                           ("sg_no_public_all_traffic", None)):
        exposed = False
        for rule in rules:
            if rule["unrestricted"] is not True:
                continue
            if rule["protocol"] == "all":
                exposed = True
            elif port is not None and rule["protocol"] in ({"tcp", "udp"} if port == 3389 else {"tcp"}):
                start, end = rule["from_port"], rule["to_port"]
                exposed = exposed or (start is not None and end is not None and 0 <= start <= port <= end <= 65535)
        value = False if exposed else True if complete else None
        results.append(_check(check_id, value, "high"))
    return results


def _security_group(row):
    rules, complete, truncated = _ingress(row.get("IpPermissions"))
    return {
        "kind": "security_group", "id": _identifier(row.get("GroupId"), "sg"),
        "vpc_id": _identifier(row.get("VpcId"), "vpc"), "ingress_rules": rules,
        "ingress_complete": complete, "ingress_truncated": truncated,
        "security_checks": _sg_checks(rules, complete),
    }


def _internet_gateway(row, vpc_id):
    attachment = next((a for a in row.get("Attachments", [])
                       if isinstance(a, dict) and a.get("VpcId") == vpc_id), {})
    return {
        "kind": "internet_gateway", "id": _identifier(row.get("InternetGatewayId"), "igw"),
        "vpc_id": _identifier(attachment.get("VpcId"), "vpc"), "state": _text(attachment.get("State")),
    }


def _nat_gateway(row):
    return {
        "kind": "nat_gateway", "id": _identifier(row.get("NatGatewayId"), "nat"),
        "vpc_id": _identifier(row.get("VpcId"), "vpc"), "subnet_id": _identifier(row.get("SubnetId"), "subnet"),
        "state": _text(row.get("State")), "connectivity_type": _text(row.get("ConnectivityType")),
    }


def _endpoint(row):
    subnet_ids, complete, truncated = _id_list(row.get("SubnetIds"), "subnet")
    return {
        "kind": "vpc_endpoint", "id": _identifier(row.get("VpcEndpointId"), "vpce"),
        "vpc_id": _identifier(row.get("VpcId"), "vpc"), "subnet_ids": subnet_ids,
        "state": _text(row.get("State")), "endpoint_type": _text(row.get("VpcEndpointType")),
        "private_dns_enabled": _boolean(row.get("PrivateDnsEnabled")),
        "relationships_complete": complete, "relationships_truncated": truncated,
    }


def _volume(row):
    attachments = row.get("Attachments")
    values = [a.get("InstanceId") if isinstance(a, dict) else None for a in attachments[:MAX_NESTED]] \
        if isinstance(attachments, list) else None
    ids, complete, truncated = _id_list(values, "i")
    if isinstance(attachments, list) and len(attachments) > MAX_NESTED:
        complete, truncated = False, True
    encrypted = _boolean(row.get("Encrypted"))
    return {
        "kind": "ebs_volume", "id": _identifier(row.get("VolumeId"), "vol"),
        "state": _text(row.get("State")), "volume_type": _text(row.get("VolumeType")),
        "size_gib": _integer(row.get("Size")), "availability_zone": _text(row.get("AvailabilityZone")),
        "encrypted": encrypted, "iops": _integer(row.get("Iops")),
        "throughput_mibps": _integer(row.get("Throughput")),
        "multi_attach_enabled": _boolean(row.get("MultiAttachEnabled")),
        "created_at": timestamp(row.get("CreateTime")), "attached_instance_ids": ids,
        "attachments_complete": complete, "attachments_truncated": truncated,
        "security_checks": [_check("ebs_encrypted", encrypted, "high")],
    }


def _repository(row):
    encryption = row.get("encryptionConfiguration", {}).get("encryptionType")
    encryption = encryption if encryption in {"AES256", "KMS", "KMS_DSSE"} else None
    scanning = _boolean(row.get("imageScanningConfiguration", {}).get("scanOnPush"))
    mutability = row.get("imageTagMutability")
    known_mutability = {"IMMUTABLE", "MUTABLE", "IMMUTABLE_WITH_EXCLUSION", "MUTABLE_WITH_EXCLUSION"}
    mutability = mutability if mutability in known_mutability else None
    return {
        "kind": "ecr_repository", "id": _text(row.get("repositoryName")),
        "image_tag_mutability": mutability, "scan_on_push": scanning, "encryption_type": encryption,
        "created_at": timestamp(row.get("createdAt")),
        "security_checks": [
            _check("ecr_encrypted", True if encryption else None),
            _check("ecr_immutable_tags", mutability == "IMMUTABLE" if mutability else None),
            _check("ecr_scan_on_push", scanning, "info"),
        ],
    }


class _NetworkInventory:
    def __init__(self, engine):
        self.engine = engine

    def _page_size(self):
        return max(5, min(50, self.engine.settings.max_resources))

    def _owner_filter(self):
        return [{"Name": "owner-id", "Values": [self.engine.settings.expected_account_id]}]

    def _owner_matches(self, obs, api, row, *, required=False):
        if not required and "OwnerId" not in row:
            return True
        owner = row.get("OwnerId")
        if owner == self.engine.settings.expected_account_id:
            return True
        code = "ResourceOwnerUnknown" if owner is None else "ResourceOwnerMismatch"
        # A resource owner mismatch is not a failure of the already verified
        # execution identity. Do not expose the foreign owner or row in errors.
        obs.error(code, "ec2", api, kind="out_of_scope")
        return False

    def _rows(self, obs, service, api, response, key):
        rows = response.get(key, [])
        if service != "ec2":
            return rows
        required = api in {"DescribeVpcs", "DescribeSecurityGroups"}
        return [row for row in rows if self._owner_matches(obs, api, row, required=required)]

    def _record(self, obs, normalizer, row):
        result = normalizer(row)
        if any(result.get(key) for key in ("ingress_truncated", "relationships_truncated",
                                           "attachments_truncated")):
            obs.result["truncated"] = True
        return result

    def _paginate(self, obs, service, api, operation, key, params, normalizer):
        token = "nextToken" if service == "ecr" else "NextToken"
        errors_before = len(obs.result["errors"])
        self.engine.paginate(
            obs, service, api, operation, params, lambda response: self._rows(obs, service, api, response, key),
            lambda row: self._record(obs, normalizer, row), token, token,
        )
        if len(obs.result["errors"]) > errors_before:
            obs.result["pagination_complete"] = False

    def list_vpcs(self, obs):
        self._paginate(
            obs, "ec2", "DescribeVpcs", self.engine.client("ec2").describe_vpcs, "Vpcs",
            {"Filters": self._owner_filter(), "MaxResults": self._page_size()}, _vpc,
        )

    def list_security_groups(self, obs, vpc_id):
        obs.result["scope"].update(vpc_id=vpc_id, max_ingress_rules=MAX_NESTED)
        self._paginate(
            obs, "ec2", "DescribeSecurityGroups", self.engine.client("ec2").describe_security_groups,
            "SecurityGroups", {"Filters": [{"Name": "vpc-id", "Values": [vpc_id]}, *self._owner_filter()],
                               "MaxResults": self._page_size()}, _security_group,
        )

    def list_ebs_volumes(self, obs):
        self._paginate(
            obs, "ec2", "DescribeVolumes", self.engine.client("ec2").describe_volumes, "Volumes",
            {"MaxResults": self._page_size()}, _volume,
        )

    def list_ecr_repositories(self, obs):
        obs.result["notes"].append(
            "scan_on_push is the returned repository setting; registry scanning and image findings are not assessed."
        )
        self._paginate(
            obs, "ecr", "DescribeRepositories", self.engine.client("ecr").describe_repositories, "repositories",
            {"registryId": self.engine.settings.expected_account_id,
             "maxResults": min(50, self.engine.settings.max_resources)}, _repository,
        )

    def get_vpc_topology(self, obs, vpc_id):
        # Import only on invocation: engine imports these handlers during setup.
        from .engine import QueryStopped

        coverage = dict.fromkeys(TOPOLOGY_KINDS, "not_queried")
        scope = obs.result["scope"]
        scope.update(vpc_id=vpc_id, kind_coverage=coverage, omitted_kinds=[], truncated_kinds=[],
                     max_ingress_rules=MAX_NESTED, max_relationships=MAX_NESTED)
        obs.result["notes"].append(
            "Only returned IDs and explicit associations are observed. No route reachability, "
            "implicit main-route associations, or application health is inferred."
        )
        ec2 = self.engine.client("ec2")
        try:
            response = self.engine.call(obs, "ec2", "DescribeVpcs", ec2.describe_vpcs, VpcIds=[vpc_id])
        except QueryStopped:
            coverage["vpc"] = "error"
            self._finish_topology(obs, coverage)
            return
        vpcs = [row for row in response.get("Vpcs", []) if row.get("VpcId") == vpc_id]
        coverage["vpc"] = "complete"
        if not vpcs:
            obs.result["missing_resource_ids"] = [vpc_id]
            self._finish_topology(obs, coverage)
            return
        if not self._owner_matches(obs, "DescribeVpcs", vpcs[0], required=True):
            coverage["vpc"] = "error"
            obs.forced_status = "invalid_input"
            self._finish_topology(obs, coverage)
            return
        obs.result["data"].append(_vpc(vpcs[0]))
        filters = [{"Name": "vpc-id", "Values": [vpc_id]}]
        size = self._page_size()
        reads = [
            ("subnet", "DescribeSubnets", ec2.describe_subnets, "Subnets", {"Filters": filters}, _subnet),
            ("route_table", "DescribeRouteTables", ec2.describe_route_tables, "RouteTables",
             {"Filters": filters}, _route_table),
            ("security_group", "DescribeSecurityGroups", ec2.describe_security_groups, "SecurityGroups",
             {"Filters": [*filters, *self._owner_filter()]}, _security_group),
            ("internet_gateway", "DescribeInternetGateways", ec2.describe_internet_gateways, "InternetGateways",
             {"Filters": [{"Name": "attachment.vpc-id", "Values": [vpc_id]}]},
             lambda row: _internet_gateway(row, vpc_id)),
            ("nat_gateway", "DescribeNatGateways", ec2.describe_nat_gateways, "NatGateways",
             {"Filter": filters}, _nat_gateway),
            ("vpc_endpoint", "DescribeVpcEndpoints", ec2.describe_vpc_endpoints, "VpcEndpoints",
             {"Filters": filters}, _endpoint),
        ]
        for kind, api, operation, key, params, normalizer in reads:
            if len(obs.result["data"]) >= self.engine.settings.max_resources or len(obs.result["api_calls"]) >= 31:
                obs.result["truncated"] = True
                break
            # engine.paginate updates the shared envelope. Keep each kind's
            # completion separate so a later success cannot hide an earlier gap.
            previous_truncated = obs.result["truncated"]
            obs.result["pagination_complete"], obs.result["truncated"] = False, False
            errors_before = len(obs.result["errors"])
            try:
                self._paginate(obs, "ec2", api, operation, key, {**params, "MaxResults": size}, normalizer)
            except QueryStopped:
                pass
            if len(obs.result["errors"]) > errors_before:
                coverage[kind] = "error"
            elif obs.result["truncated"] or not obs.result["pagination_complete"]:
                coverage[kind] = "truncated"
            else:
                coverage[kind] = "complete"
            obs.result["truncated"] = previous_truncated or obs.result["truncated"]
        self._finish_topology(obs, coverage)

    @staticmethod
    def _finish_topology(obs, coverage):
        scope = obs.result["scope"]
        scope["omitted_kinds"] = [kind for kind, status in coverage.items()
                                  if status in {"not_queried", "error"}]
        scope["truncated_kinds"] = [kind for kind, status in coverage.items() if status == "truncated"]
        obs.result["pagination_complete"] = all(status == "complete" for status in coverage.values())


def handlers(engine):
    inventory = _NetworkInventory(engine)
    return {
        "list_vpcs": inventory.list_vpcs,
        "get_vpc_topology": inventory.get_vpc_topology,
        "list_security_groups": inventory.list_security_groups,
        "list_ebs_volumes": inventory.list_ebs_volumes,
        "list_ecr_repositories": inventory.list_ecr_repositories,
    }
