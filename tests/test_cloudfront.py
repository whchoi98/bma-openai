"""Check both Web Function front doors against concrete public/private requests.

These are local CloudFormation contract tests. HTTP cache-control behavior is
tested separately in each app's cache-control.test.js; live OAC signing and the
resource policy are verified by the staged deployment.
"""
import fnmatch
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ["infra/template.yaml", "studio/infra/template.yaml"]


class TemplateLoader(yaml.SafeLoader):
    pass


def intrinsic(loader, tag, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return {tag: value}


TemplateLoader.add_multi_constructor("!", intrinsic)


@pytest.fixture(params=TEMPLATES, ids=["operations-desk", "document-studio"])
def template(request):
    return yaml.load((ROOT / request.param).read_text(), Loader=TemplateLoader)


def distribution(template):
    return template["Resources"]["WebDistribution"]["Properties"]["DistributionConfig"]


def behavior_for(template, path):
    config = distribution(template)
    for behavior in config.get("CacheBehaviors", []):
        if fnmatch.fnmatchcase(path, behavior["PathPattern"]):
            return behavior
    return config["DefaultCacheBehavior"]


def test_oac_signs_for_the_regional_endpoint_without_replacing_app_authorization(template):
    resources = template["Resources"]
    endpoint = resources["WebEndpoint"]["Properties"]
    assert endpoint["EndpointType"] == "HomeRegion"
    assert endpoint["AuthType"] == {"Ref": "WebEndpointAuthType"}
    assert template["Parameters"]["WebEndpointAuthType"]["Default"] == "IamAuth"
    assert template["Parameters"]["AppRegion"]["Default"] == "us-east-1"
    oac = resources["WebOriginAccessControl"]["Properties"]["OriginAccessControlConfig"]
    assert oac["OriginAccessControlOriginType"] == "lambda"
    assert oac["SigningBehavior"] == "always-amz-auth"
    assert oac["SigningProtocol"] == "sigv4"
    origins = distribution(template)["Origins"]
    assert len(origins) == 1
    assert origins[0]["DomainName"] == {"GetAtt": "WebEndpoint.DomainName"}
    assert origins[0]["OriginAccessControlId"] == {"GetAtt": "WebOriginAccessControl.Id"}
    assert template["Outputs"]["WebUrl"]["Value"] == {"Sub": "https://${WebDistribution.DomainName}"}


@pytest.mark.parametrize("path", [
    "/api/config", "/api/context", "/api/jobs",
    "/api/jobs/11111111-1111-4111-8111-111111111111/events",
    "/api/jobs/11111111-1111-4111-8111-111111111111/artifacts/documents_html",
    "/api/chat", "/api/runs/11111111-1111-4111-8111-111111111111/report.html",
    "/health", "/missing.js",
])
def test_private_or_unknown_routes_never_select_public_asset_caching(template, path):
    behavior = behavior_for(template, path)
    assert behavior is distribution(template)["DefaultCacheBehavior"]
    assert behavior["MinTTL"] == behavior["DefaultTTL"] == behavior["MaxTTL"] == 0
    assert behavior["Compress"] is False
    assert set(behavior["CachedMethods"]) == {"GET", "HEAD"}
    assert {"GET", "HEAD", "POST", "OPTIONS"} <= set(behavior["AllowedMethods"])


@pytest.mark.parametrize("path", [
    "/", "/static/app.js", "/static/style.css", "/static/fonts/NanumSquareB.otf",
])
def test_only_public_asset_routes_get_bounded_origin_controlled_caching(template, path):
    behavior = behavior_for(template, path)
    assert behavior["PathPattern"] in {"/", "/static/*"}
    assert behavior["MinTTL"] == behavior["DefaultTTL"] == 0
    assert 0 < behavior["MaxTTL"] <= 3600
    assert behavior["Compress"] is True
    assert set(behavior["AllowedMethods"]) == {"GET", "HEAD", "OPTIONS"}
    assert set(behavior["CachedMethods"]) == {"GET", "HEAD"}


def test_every_behavior_preserves_authentication_queries_and_origin_host_without_policy_resources(template):
    config = distribution(template)
    assert not any(resource["Type"] == "AWS::CloudFront::CachePolicy"
                   for resource in template["Resources"].values())
    for behavior in [config["DefaultCacheBehavior"], *config["CacheBehaviors"]]:
        assert behavior["TargetOriginId"] == config["Origins"][0]["Id"]
        assert behavior["ViewerProtocolPolicy"] == "redirect-to-https"
        assert "CachePolicyId" not in behavior
        assert "OriginRequestPolicyId" not in behavior
        assert not behavior.get("LambdaFunctionAssociations")
        forwarding = behavior["ForwardedValues"]
        forwarded_headers = {name.lower() for name in forwarding["Headers"]}
        assert "authorization" in forwarded_headers
        assert "host" not in forwarded_headers
        assert "*" not in forwarded_headers
        assert forwarding["Cookies"]["Forward"] == "all"
        assert forwarding["QueryString"] is True
    headers = {name.lower() for name in config["DefaultCacheBehavior"]["ForwardedValues"]["Headers"]}
    assert {"content-type", "x-file-name", "last-event-id", "origin", "accept"} <= headers


def test_edge_coverage_and_https_origin_support_streaming_without_a_short_total_deadline(template):
    config = distribution(template)
    assert config["Enabled"] is True
    assert config["PriceClass"] == "PriceClass_All"
    assert config["HttpVersion"] == "http2and3"
    assert config["IPV6Enabled"] is True
    origin = config["Origins"][0]
    assert origin["ConnectionAttempts"] <= 3
    connection = origin["CustomOriginConfig"]
    assert connection["OriginProtocolPolicy"] == "https-only"
    assert connection["OriginSSLProtocols"] == ["TLSv1.2"]
    # Application heartbeats arrive every 10 or 15 seconds during idle waits.
    assert connection["OriginReadTimeout"] >= 30
    assert origin.get("ResponseCompletionTimeout", 600) >= 600


def test_permission_and_application_errors_are_not_retained_at_the_edge(template):
    errors = {item["ErrorCode"]: item for item in distribution(template)["CustomErrorResponses"]}
    for code in [403, 404, 405, 500, 502, 503, 504]:
        assert errors[code]["ErrorCachingMinTTL"] == 0
        assert "ResponseCode" not in errors[code]
        assert "ResponsePagePath" not in errors[code]
