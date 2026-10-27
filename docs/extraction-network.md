# Network, EBS, and ECR extraction

> 이 문서는 최초 설계 또는 오레곤 추출 검증 기록을 포함합니다. 현재 실행 리전과 모델은 [배포 보고서](aws-deployment.md)를 기준으로 확인합니다.

Verified on 2026-10-27. The extraction source is `/home/ec2-user/my-project/awsops`.
Only the five source files below were read; no source code was executed or modified.
The implementation is in `aws_inventory/network_inventory.py`, with synthetic SDK
responses in `aws_inventory/network_samples.py`.

## Source provenance

| Original file, relative to `awsops` | SHA-256 | Adaptation |
| --- | --- | --- |
| `agent/lambda/network_mcp.py` | `3c8f5905c3cae040171d0acfe1e4504725fbda59fd646822e3d963d83fc2a71d` | Extracted fixed VPC reads, VPC filters, and explicit subnet/gateway associations. Replaced direct client creation and unbounded results with the existing verified-account engine. |
| `src/lib/queries/vpc.ts` | `900d8e661cb26ffb976a8625e906cab9539875f47a8a8c4db336b8e5a575a1cb` | Adapted VPC/subnet configuration fields, SG permissions, and explicit route-table subnet associations to SDK response fields. |
| `src/lib/queries/ebs.ts` | `f8846fdc448ba278fbb67b60fbb53a2d04568f46fbc3ce3f2b56b0dc7c474ae0` | Adapted volume type, size, state, encryption, performance settings, and attached instance IDs. |
| `src/lib/queries/ecr.ts` | `25e6db2ce505e51b02c6acf95b37f57f1f1dbcd31e51206c91cb0260dbef1467` | Adapted repository name, tag mutability, scan-on-push setting, encryption type, and creation time. |
| `src/app/topology/page.tsx` | `d276a3216229e14ef286a0a566e79c9f229486834a6a2e8bd95b896ec6fbc8f9` | Retained the idea of connecting returned IDs using observed VPC/subnet membership. No inferred, placeholder, or Kubernetes nodes are emitted. |

SQL execution, arbitrary resource-type dispatch, CLI execution, cross-account role
selection, flow logs, VPN/TGW/firewall reads, raw tags, descriptions, key identifiers,
endpoint URLs, and resource mutations were not extracted.

## Tool contract and limits

`TOOL_SCHEMAS`, `DATA_FIELDS`, and `handlers(engine)` are the integration points.
Argument models are strict Pydantic models with extra fields forbidden. The only
tool argument is `vpc_id`, required by `get_vpc_topology` and
`list_security_groups`; it must be an EC2 VPC ID with 8 or 17 lowercase hexadecimal
digits. Account, Region, service name, SDK operation, SQL, and shell command cannot
be selected through arguments.

| Tool | Envelope service | SDK client | Returned kinds |
| --- | --- | --- | --- |
| `list_vpcs` | `vpc` | `ec2` | `vpc` |
| `get_vpc_topology(vpc_id)` | `vpc` | `ec2` | `vpc`, `subnet`, `route_table`, `security_group`, `internet_gateway`, `nat_gateway`, `vpc_endpoint` |
| `list_security_groups(vpc_id)` | `vpc` | `ec2` | `security_group` |
| `list_ebs_volumes` | `ebs` | `ec2` | `ebs_volume` |
| `list_ecr_repositories` | `ecr` | `ecr` | `ecr_repository` |

All calls use the shared engine's `client`, `call`, and bounded pagination.
`api_calls[].service` records the actual SDK client, while the envelope uses the
logical service above. STS verifies `EXPECTED_ACCOUNT_ID` before each invocation
in `us-west-2`; resource reads use `ap-northeast-2`. Account mismatch prevents any
resource API call. The existing timeouts, three-attempt retry bound, request
metadata, sanitized errors, and per-invocation evidence envelope remain in force.

STS identifies the execution account; it does not prove that a visible shared
resource belongs to that account. `list_vpcs` therefore sends an `owner-id` filter,
and both standalone and topology SG reads combine `vpc-id` with `owner-id`.
Returned VPC and SG rows must also contain `OwnerId=EXPECTED_ACCOUNT_ID` before
normalization. SG ownership is validated independently of the VPC owner because
shared-VPC participant security groups can have a different owner.

A foreign or missing owner on the root VPC stops topology before any child API
call, with `invalid_input` and `ResourceOwnerMismatch` or `ResourceOwnerUnknown`.
List and child rejections produce an `out_of_scope` error, exclude the rejected
row, and leave pagination/coverage incomplete. The verified execution account
remains in the envelope; resource-owner rejection is never reported as an STS
`account_mismatch`. Owner fields on returned subnets, route tables, internet
gateways, VPC endpoints, and EBS volumes are checked when supplied. The NAT gateway
response has no `OwnerId`; its scope is the verified root VPC and fixed VPC filter.
No foreign owner ID or rejected resource body is copied into an error.

Each result contains at most `settings.max_resources` total data rows, including
all topology kinds combined. Every paginated read uses at most
`settings.max_pages`; EC2 page sizes are `max(5, min(50, max_resources))`, and ECR
uses `min(50, max_resources)`. The singular VPC lookup uses `VpcIds=[vpc_id]`.
The six child topology reads each have their own bounded pagination, so the
logical-call maximum is `2 + 6 * max_pages`, including STS and the root lookup.
Hitting the shared row cap skips later resource kinds.

Topology exposes `scope.kind_coverage`, mapping each kind to `complete`,
`truncated`, `error`, or `not_queried`. `scope.omitted_kinds` lists kinds with an
error or no query; an errored kind may still have rows observed on an earlier
page. `scope.truncated_kinds` identifies capped kinds. A later successful read
cannot overwrite an earlier incomplete coverage result. A missing or denied
root VPC produces no fabricated root and prevents child queries. A denied child
kind preserves earlier rows and permits the other bounded child reads.

Rows retain only observed membership fields: `kind`, `id`, `vpc_id`, `subnet_id`
for a NAT gateway, and `subnet_ids` for explicit route-table associations and
VPC endpoint subnet membership. Consumers must create edges only when both
endpoint IDs occur in returned rows. A main route table does not cause implicit
subnet associations to be synthesized. No route reachability or application
health is inferred.

## Fields and security checks

| Kind | Additional allowlisted fields |
| --- | --- |
| `vpc` | `state`, `cidr_block`, `is_default`, `instance_tenancy` |
| `subnet` | `state`, `cidr_block`, `availability_zone`, `available_ip_address_count`, `map_public_ip_on_launch` |
| `route_table` | `main`, `route_count`, `relationships_complete`, `relationships_truncated` |
| `security_group` | `ingress_rules`, `ingress_complete`, `ingress_truncated`, `security_checks` |
| `internet_gateway` | Observed attachment `state` |
| `nat_gateway` | `state`, `connectivity_type` |
| `vpc_endpoint` | `state`, `endpoint_type`, `private_dns_enabled`, `relationships_complete`, `relationships_truncated` |
| `ebs_volume` | `state`, `volume_type`, `size_gib`, `availability_zone`, `encrypted`, `iops`, `throughput_mibps`, `multi_attach_enabled`, `created_at`, `attached_instance_ids`, `attachments_complete`, `attachments_truncated`, `security_checks` |
| `ecr_repository` | `image_tag_mutability`, `scan_on_push`, `encryption_type`, `created_at`, `security_checks`; `id` is the repository name |

Nested SG ingress is flattened into at most 50 source rules per group. Each rule
contains only `protocol`, `from_port`, `to_port`, `source_type`, `source`, and
`unrestricted`. Source types are `ipv4`, `ipv6`, `security_group`, `prefix_list`,
and `unknown`. CIDRs are canonicalized; source group and prefix-list IDs are
validated. Rule descriptions and source account IDs are omitted. `unrestricted`
means an IPv4 or IPv6 `/0` source. Prefix-list contents are not queried, so their
exposure remains unknown.

`ingress_complete` requires all represented ingress to be parsed and classifiable
for these checks. Missing permissions, missing required protocol/port/source
fields, unresolved prefix-list sources, and truncated rules prevent a pass.
`ingress_truncated` also sets envelope `truncated`, yielding a partial result.
Explicitly empty `IpPermissions=[]` is complete evidence of no ingress rules.
Observed failures remain failures even when other rules are incomplete.
For ICMPv6, both type and code may be omitted: this is valid all-type/all-code
ingress, and is complete evidence for the three narrowly scoped SG checks.
A one-sided omission, an out-of-range type/code, or type `-1` combined with a
specific code is incomplete. Explicit ICMP type/code pairs remain bounded to
`-1..255`, with all types requiring all codes.
Subnet relationship and EBS attachment ID lists are also capped at 50, with
explicit completion and truncation flags.

Every security check has exactly `{id, status, severity}`. Status is `pass`,
`fail`, or `unknown`; no absent setting defaults to a secure value.

| Check ID | Severity | Meaning |
| --- | --- | --- |
| `sg_no_public_ssh` | `high` | No observed `/0` TCP port 22 permission or all-protocol permission; unknown when the available ingress cannot establish this. |
| `sg_no_public_rdp` | `high` | No observed `/0` TCP/UDP port 3389 permission or all-protocol permission. |
| `sg_no_public_all_traffic` | `high` | No observed `/0` permission for protocol `-1` (all protocols). |
| `ebs_encrypted` | `high` | Uses the returned `Encrypted` boolean. |
| `ecr_encrypted` | `medium` | Passes only for a returned, recognized encryption type: `AES256`, `KMS`, or `KMS_DSSE`. |
| `ecr_immutable_tags` | `medium` | Passes only for `IMMUTABLE`; modes with mutable exclusions do not claim full immutability. |
| `ecr_scan_on_push` | `info` | Reports the repository's returned `scanOnPush` setting. It is not evidence of registry scan coverage or vulnerability results. |

These are bounded configuration facts, not health judgments or compliance
certification. SG checks cover individual unrestricted CIDR sources; they do not
analyze unions of narrower CIDRs, routing, NACLs, attachments, reachability, or
application listeners. ECR registry scanning settings and image scans are outside
this tool's evidence.

## Verified SDK and IAM action matrix

All SDK references below returned HTTP 200 on the verification date. The
installed botocore models were also used to validate request and response shapes.
Every action was checked against the official machine-readable service
authorization references:

- EC2: <https://servicereference.us-east-1.amazonaws.com/v1/ec2/ec2.json>
- ECR: <https://servicereference.us-east-1.amazonaws.com/v1/ecr/ecr.json>

Both references reported version `v1.5`. Their `Operations` entries map each
method below to exactly the corresponding IAM action, and all listed actions
have `Annotations.Properties.IsWrite=false`. All eight EC2 actions have no
resource-level ARN support and expose the `ec2:Region` condition. ECR
`DescribeRepositories` supports the `repository` resource type.

| SDK method and official documentation | Exact action | Scope |
| --- | --- | --- |
| [`ec2.describe_vpcs`](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_vpcs.html) | `ec2:DescribeVpcs` | `Resource: "*"`; list with `owner-id`, or one `VpcIds` selection followed by mandatory owner validation |
| [`ec2.describe_subnets`](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_subnets.html) | `ec2:DescribeSubnets` | `Resource: "*"`; `Filters` on `vpc-id` |
| [`ec2.describe_route_tables`](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_route_tables.html) | `ec2:DescribeRouteTables` | `Resource: "*"`; `Filters` on `vpc-id` |
| [`ec2.describe_security_groups`](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_security_groups.html) | `ec2:DescribeSecurityGroups` | `Resource: "*"`; `Filters` on `vpc-id` and `owner-id`, plus mandatory response-owner validation |
| [`ec2.describe_internet_gateways`](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_internet_gateways.html) | `ec2:DescribeInternetGateways` | `Resource: "*"`; `Filters` on `attachment.vpc-id` |
| [`ec2.describe_nat_gateways`](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_nat_gateways.html) | `ec2:DescribeNatGateways` | `Resource: "*"`; singular `Filter` on `vpc-id` |
| [`ec2.describe_vpc_endpoints`](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_vpc_endpoints.html) | `ec2:DescribeVpcEndpoints` | `Resource: "*"`; `Filters` on `vpc-id` |
| [`ec2.describe_volumes`](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_volumes.html) | `ec2:DescribeVolumes` | `Resource: "*"`; regional volume configuration |
| [`ecr.describe_repositories`](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecr/client/describe_repositories.html) | `ecr:DescribeRepositories` | Repository ARN scope; explicit `registryId=EXPECTED_ACCOUNT_ID` |

Use a Seoul condition on these resource-read statements, separate from the
existing STS identity call. EC2 supports `ec2:Region=ap-northeast-2`; the shared
regional policy may also use the global `aws:RequestedRegion` condition. ECR
repository ARNs have the documented format
`arn:${Partition}:ecr:${Region}:${Account}:repository/${RepositoryName}`, permitting
a fixed account/Seoul `repository/*` scope. No managed `ReadOnlyAccess`,
`ecr:GetAuthorizationToken`, image-download permission, log-read permission,
or resource mutation is required by these tools.

The legacy HTML SAR URLs for EC2 and ECR redirected to the service-authorization
guide root when checked. The action verification therefore uses the official
JSON references above, including their operation-to-action and resource metadata,
rather than treating that redirect as a successful action lookup.

| Documentation snapshot | SHA-256 |
| --- | --- |
| EC2 service authorization JSON | `5e688934071fefe90db27b61e380ce69f232c61dadcd8245dbb9634b10829e98` |
| ECR service authorization JSON | `6ed3141573acfeae5a9162cb755d1704de4efcab191bbcd014246bdd4d24733f` |
| `describe_vpcs` SDK page | `734f0edca6ef9ebcd7a48712a12c67707499cd1aeea22ec7f268246b28265438` |
| `describe_subnets` SDK page | `9acce5d527052f755d665af83173098e9bcdd8143f0c820c6668c1a5e3f1aaa9` |
| `describe_route_tables` SDK page | `432b88332ab4cde46e053127b3a35124274e3e0693b97e4700656825337aa328` |
| `describe_security_groups` SDK page | `481205118ad02a7154653c922d09e4fb3839f95f52a49c816c5aa72df9421931` |
| `describe_internet_gateways` SDK page | `6830e24a569831c1af940a98c005846cca9014f5613d703495e0ff7c26ead7b9` |
| `describe_nat_gateways` SDK page | `fa15b9864f89c88282f690bef154b974e9253289426604a9c7151380c39d5552` |
| `describe_vpc_endpoints` SDK page | `ee0d141d99fd4e033c8e9964c35780a9b801178045a296666439bdff3b3b0438` |
| `describe_volumes` SDK page | `4a5dd6e89a3ebc313cf00ee544200cefece60d54b6ba7e3f99e991832e9708b5` |
| `describe_repositories` SDK page | `824f4ef35324239d8e3fe225dc68a90b9b8443ea1263f9e61bdc65a4b1b0ca4e` |

## Validation and integration

Run the scoped checks without creating bytecode or pytest cache files:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -s -p no:cacheprovider tests/test_network_inventory.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/ruff check --no-cache aws_inventory/network_inventory.py aws_inventory/network_samples.py tests/test_network_inventory.py
```

The scoped suite has 77 passing tests, covering empty/denied/partial responses,
fixed Regions, account mismatch, foreign/missing resource owners, owner filtering,
root-owner rejection before child reads, strict input rejection, EC2 and ECR pagination,
resource/page caps, topology coverage, absent root VPCs, sensitive-field removal,
IPv4/IPv6 and port-range SG checks, valid omitted ICMPv6 type/code fields,
malformed ICMPv6 combinations, missing and truncated ingress, unresolved
prefix lists, encryption, tag mutability exceptions, and synthetic SDK shapes.
The shared engine additionally caps all SDK calls at 31 per invocation, including
STS. Topology leaves later kinds unqueried when this cap is reached. The ICMPv6
omission shortcut applies only when both raw keys are absent; malformed provided
values remain incomplete/unknown.
No live AWS resource API call or deployment is part of validation.

The sample adapter is
`network_samples.response(service, snake_case_operation, params)`. It returns a
fresh SDK-shaped dictionary, follows bounded page requests and VPC filters, and
raises `KeyError` for APIs it does not own. Its VPC is
`vpc-00000000000000001`. The complete sample topology has nine observed rows.
The coordinator owns sample-session wiring, public nested-field allowlists,
graph rendering, the shared SDK service registry, and IAM template integration.
