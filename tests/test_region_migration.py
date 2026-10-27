import pytest

from aws_inventory.config import Settings


def test_migrated_runtime_keeps_seoul_separate_from_app_region(monkeypatch):
    monkeypatch.setenv("EXPECTED_ACCOUNT_ID", "111122223333")
    monkeypatch.setenv("APP_REGION", "us-east-1")
    monkeypatch.setenv("TARGET_REGION", "ap-northeast-2")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    settings = Settings.from_env()
    assert settings.app_region == "us-east-1"
    assert settings.target_region == "ap-northeast-2"


def test_old_oregon_application_configuration_is_rejected():
    with pytest.raises(ValueError, match="APP_REGION"):
        Settings(expected_account_id="111122223333", app_region="us-west-2")


def test_migration_does_not_allow_querying_the_application_region():
    with pytest.raises(ValueError, match="TARGET_REGION"):
        Settings(expected_account_id="111122223333", app_region="us-east-1", target_region="us-east-1")
