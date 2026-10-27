from copy import deepcopy

import pytest

from scripts.deploy_cloudfront import endpoint_policy, review_changes


@pytest.mark.parametrize("function,endpoint", [
    ("bma-seoul-inventory-web", "demo"),
    ("bma-office-studio-web", "studio"),
])
def test_endpoint_policy_allows_only_one_expected_endpoint_and_distribution(function, endpoint):
    policy = endpoint_policy("123456789012", function, endpoint, "E12ABCDE345FGH")
    assert policy == {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "AllowOnlyThisCloudFrontDistribution",
            "Effect": "Allow",
            "Principal": {"Service": "cloudfront.amazonaws.com"},
            "Action": "lambda:InvokeWebFunctionEndpoint",
            "Resource": f"arn:aws:lambda:us-east-1:123456789012:web-function/{function}/endpoint/{endpoint}",
            "Condition": {"StringEquals": {
                "aws:SourceArn": "arn:aws:cloudfront::123456789012:distribution/E12ABCDE345FGH",
            }},
        }],
    }


@pytest.mark.parametrize("account,function,endpoint,distribution", [
    ("12345", "bma-office-studio-web", "studio", "EABC"),
    ("123456789012", "other-web", "studio", "EABC"),
    ("123456789012", "bma-office-studio-web", "demo", "EABC"),
    ("123456789012", "bma-seoul-inventory-web", "studio", "EABC"),
    ("123456789012", "bma-office-studio-web", "studio", "*"),
    ("123456789012", "bma-office-studio-web", "studio", "EABC*"),
])
def test_endpoint_policy_rejects_broader_or_unrelated_scopes(account, function, endpoint, distribution):
    with pytest.raises(ValueError):
        endpoint_policy(account, function, endpoint, distribution)


def test_prepare_change_allowlist_accepts_only_intended_existing_and_new_resources():
    review_changes([
        {"LogicalResourceId": "WebRevision", "Action": "Modify", "Replacement": "True"},
        {"LogicalResourceId": "WebEndpoint", "Action": "Modify", "Replacement": "False"},
        {"LogicalResourceId": "StudioWorker", "Action": "Modify", "Replacement": "False"},
        {"LogicalResourceId": "WebDistribution", "Action": "Add"},
        {"LogicalResourceId": "WebOriginAccessControl", "Action": "Add"},
    ], "StudioWorker")


@pytest.mark.parametrize("row", [
    {"LogicalResourceId": "Runtime", "Action": "Modify", "Replacement": "False"},
    {"LogicalResourceId": "SessionRole", "Action": "Modify", "Replacement": "False"},
    {"LogicalResourceId": "WebEndpoint", "Action": "Remove"},
    {"LogicalResourceId": "WebEndpoint", "Action": "Modify", "Replacement": "True"},
    {"LogicalResourceId": "StudioWorker", "Action": "Modify", "Replacement": "Conditional"},
    {"LogicalResourceId": "StudioData", "Action": "Remove"},
])
def test_prepare_change_allowlist_rejects_unsafe_changes(row):
    with pytest.raises(RuntimeError):
        review_changes([row], "StudioWorker")


def test_cutover_can_only_change_endpoint_without_replacement():
    review_changes([{
        "LogicalResourceId": "WebEndpoint", "Action": "Modify", "Replacement": "False",
    }], "StudioWorker", cutover=True)
    with pytest.raises(RuntimeError):
        review_changes([{
            "LogicalResourceId": "WebRevision", "Action": "Modify", "Replacement": "True",
        }], "StudioWorker", cutover=True)


def role_reevaluation():
    return {
        "LogicalResourceId": "WebRole", "Action": "Modify", "Replacement": "False",
        "Details": [{
            "Evaluation": "Dynamic", "ChangeSource": "ResourceAttribute",
            "CausingEntity": "StudioWorker.Arn",
            "Target": {"Attribute": "Properties", "Name": "Policies", "RequiresRecreation": "Never"},
        }],
    }


def test_worker_arn_reevaluation_requires_proven_unchanged_role_and_prepare_phase():
    row = role_reevaluation()
    review_changes([row], "StudioWorker", unchanged_web_role=True)
    with pytest.raises(RuntimeError, match="UnexpectedResourceChange:WebRole"):
        review_changes([row], "StudioWorker")
    with pytest.raises(RuntimeError, match="UnexpectedResourceChange:WebRole"):
        review_changes([row], "StudioWorker", unchanged_web_role=False)
    with pytest.raises(RuntimeError, match="UnexpectedResourceChange:WebRole"):
        review_changes([row], "StudioWorker", unchanged_web_role=True, cutover=True)
    with pytest.raises(RuntimeError, match="UnexpectedResourceChange:WebRole"):
        review_changes([row], "InvestigationWorker", unchanged_web_role=True)


@pytest.mark.parametrize("field,value", [
    ("Evaluation", "Static"),
    ("ChangeSource", "DirectModification"),
    ("CausingEntity", "OtherResource.Arn"),
    ("CausingEntity", "StudioWorker.Role"),
    ("Target", {"Attribute": "Properties", "Name": "AssumeRolePolicyDocument", "RequiresRecreation": "Never"}),
    ("Target", {"Attribute": "Properties", "Name": "Policies", "RequiresRecreation": "Conditionally"}),
    ("Target", {"Attribute": "Properties", "Name": "Policies", "RequiresRecreation": "Never", "Extra": "unknown"}),
])
def test_role_exception_rejects_policy_or_unknown_dependency_changes(field, value):
    row = role_reevaluation()
    row["Details"][0][field] = value
    with pytest.raises(RuntimeError, match="UnexpectedResourceChange:WebRole"):
        review_changes([row], "StudioWorker", unchanged_web_role=True)


def test_role_exception_checks_every_detail_and_rejects_empty_or_replacement_changes():
    row = role_reevaluation()
    extra = deepcopy(row["Details"][0])
    extra["ChangeSource"] = "DirectModification"
    row["Details"].append(extra)
    with pytest.raises(RuntimeError, match="UnexpectedResourceChange:WebRole"):
        review_changes([row], "StudioWorker", unchanged_web_role=True)
    for changes in [
        {"Details": []}, {"Replacement": "True"}, {"Replacement": "Conditional"}, {"Action": "Add"},
    ]:
        row = role_reevaluation()
        row.update(changes)
        with pytest.raises(RuntimeError, match="UnexpectedResourceChange:WebRole"):
            review_changes([row], "StudioWorker", unchanged_web_role=True)


def distribution_reevaluation():
    return {
        "LogicalResourceId": "WebDistribution", "Action": "Modify", "Replacement": "False",
        "Details": [{
            "Evaluation": "Dynamic", "ChangeSource": "ResourceAttribute",
            "CausingEntity": "WebEndpoint.DomainName",
            "Target": {"Attribute": "Properties", "Name": "DistributionConfig", "RequiresRecreation": "Never"},
        }],
    }


def test_cutover_distribution_reevaluation_requires_exact_unchanged_configuration_proof():
    row = distribution_reevaluation()
    review_changes([row], "StudioWorker", cutover=True, unchanged_distribution=True)
    with pytest.raises(RuntimeError, match="UnexpectedResourceChange:WebDistribution"):
        review_changes([row], "StudioWorker", cutover=True)
    with pytest.raises(RuntimeError, match="UnexpectedResourceChange:WebDistribution"):
        review_changes([row], "StudioWorker", cutover=True, unchanged_distribution=False)


@pytest.mark.parametrize("field,value", [
    ("Evaluation", "Static"),
    ("ChangeSource", "DirectModification"),
    ("CausingEntity", "OtherEndpoint.DomainName"),
    ("CausingEntity", "WebEndpoint.AuthType"),
    ("Target", {"Attribute": "Properties", "Name": "Tags", "RequiresRecreation": "Never"}),
    ("Target", {"Attribute": "Properties", "Name": "DistributionConfig", "RequiresRecreation": "Always"}),
])
def test_cutover_distribution_exception_rejects_actual_or_unrelated_changes(field, value):
    row = distribution_reevaluation()
    row["Details"][0][field] = value
    with pytest.raises(RuntimeError, match="UnexpectedResourceChange:WebDistribution"):
        review_changes([row], "StudioWorker", cutover=True, unchanged_distribution=True)


def test_cutover_distribution_exception_rejects_mixed_details_and_replacement():
    row = distribution_reevaluation()
    extra = deepcopy(row["Details"][0])
    extra["ChangeSource"] = "DirectModification"
    row["Details"].append(extra)
    with pytest.raises(RuntimeError, match="UnexpectedResourceChange:WebDistribution"):
        review_changes([row], "StudioWorker", cutover=True, unchanged_distribution=True)
    for changes in [{"Details": []}, {"Replacement": "True"}, {"Action": "Remove"}]:
        row = distribution_reevaluation()
        row.update(changes)
        with pytest.raises(RuntimeError, match="UnexpectedResourceChange:WebDistribution"):
            review_changes([row], "StudioWorker", cutover=True, unchanged_distribution=True)
