from __future__ import annotations

import io
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from finops_app.connectors.aws import AwsConnector
from finops_app.connectors.azure import AzureConnector
from finops_app.connectors.gcp import GcpConnector


def test_cloudformation_template_generation() -> None:
    tmpl = AwsConnector.generate_cloudformation_template(
        external_id="ext-test-123",
        s3_bucket="my-cur-bucket",
    )
    assert tmpl["AWSTemplateFormatVersion"] == "2010-09-09"
    role_props = tmpl["Resources"]["FinOpsCrossAccountRole"]["Properties"]
    trust_stmt = role_props["AssumeRolePolicyDocument"]["Statement"][0]
    assert trust_stmt["Condition"]["StringEquals"]["sts:ExternalId"]["Ref"] == "ExternalId"
    policy_stmts = role_props["Policies"][0]["PolicyDocument"]["Statement"]
    actions = [stmt["Action"] for stmt in policy_stmts]
    assert ["s3:ListBucket", "s3:GetBucketLocation"] in actions


def test_quick_create_url_generation() -> None:
    url = AwsConnector.generate_quick_create_url(
        external_id="ext-456",
        s3_bucket="cur-bucket-xyz",
        region="eu-west-1",
    )
    assert "console.aws.amazon.com/cloudformation" in url
    assert "region=eu-west-1" in url
    assert "param_ExternalId=ext-456" in url
    assert "param_ExportBucketName=cur-bucket-xyz" in url


def test_aws_verify_success() -> None:
    mock_boto_session = MagicMock()
    mock_sts = MagicMock()
    mock_s3 = MagicMock()

    mock_boto_session.client.side_effect = lambda svc, **kwargs: (
        mock_sts if svc == "sts" else mock_s3
    )

    mock_sts.assume_role.return_value = {
        "Credentials": {
            "AccessKeyId": "AKIA_TEMP",
            "SecretAccessKey": "SECRET_TEMP",
            "SessionToken": "TOKEN_TEMP",
        }
    }
    mock_s3.list_objects_v2.return_value = {"KeyCount": 1}

    conn = AwsConnector(
        role_arn="arn:aws:iam::123456789012:role/FinOpsRole",
        external_id="ext-abc",
        s3_bucket="billing-bucket",
        boto_session=mock_boto_session,
    )

    result = conn.verify()
    assert result.success is True
    assert "Connected successfully" in result.message
    assert result.details["bucket"] == "billing-bucket"
    mock_sts.assume_role.assert_called_once()


def test_aws_verify_access_denied() -> None:
    mock_boto_session = MagicMock()
    mock_sts = MagicMock()
    mock_boto_session.client.return_value = mock_sts

    mock_sts.assume_role.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "User is not authorized"}},
        "AssumeRole",
    )

    conn = AwsConnector(
        role_arn="arn:aws:iam::123456789012:role/FinOpsRole",
        external_id="ext-abc",
        s3_bucket="billing-bucket",
        boto_session=mock_boto_session,
    )

    result = conn.verify()
    assert result.success is False
    assert "Access Denied" in result.message
    assert result.details["error_code"] == "AccessDenied"


def test_aws_verify_bucket_not_found() -> None:
    mock_boto_session = MagicMock()
    mock_sts = MagicMock()
    mock_s3 = MagicMock()

    mock_boto_session.client.side_effect = lambda svc, **kwargs: (
        mock_sts if svc == "sts" else mock_s3
    )

    mock_sts.assume_role.return_value = {
        "Credentials": {
            "AccessKeyId": "AKIA_TEMP",
            "SecretAccessKey": "SECRET_TEMP",
            "SessionToken": "TOKEN_TEMP",
        }
    }
    mock_s3.list_objects_v2.side_effect = ClientError(
        {"Error": {"Code": "NoSuchBucket", "Message": "The specified bucket does not exist"}},
        "ListObjectsV2",
    )

    conn = AwsConnector(
        role_arn="arn:aws:iam::123456789012:role/FinOpsRole",
        external_id="ext-abc",
        s3_bucket="nonexistent-bucket",
        boto_session=mock_boto_session,
    )

    result = conn.verify()
    assert result.success is False
    assert "does not exist" in result.message


def test_aws_list_and_download_exports() -> None:
    mock_boto_session = MagicMock()
    mock_sts = MagicMock()
    mock_s3 = MagicMock()

    mock_boto_session.client.side_effect = lambda svc, **kwargs: (
        mock_sts if svc == "sts" else mock_s3
    )

    mock_sts.assume_role.return_value = {
        "Credentials": {
            "AccessKeyId": "AKIA_TEMP",
            "SecretAccessKey": "SECRET_TEMP",
            "SessionToken": "TOKEN_TEMP",
        }
    }

    mock_paginator = MagicMock()
    mock_s3.get_paginator.return_value = mock_paginator
    mock_paginator.paginate.return_value = [
        {
            "Contents": [
                {
                    "Key": "cur/2026-11/manifest.json",
                    "LastModified": datetime(2026, 11, 20, 10, 0, tzinfo=UTC),
                    "Size": 1024,
                },
                {
                    "Key": "cur/2026-11/billing_export_part1.csv.gz",
                    "LastModified": datetime(2026, 11, 25, 12, 0, tzinfo=UTC),
                    "Size": 500000,
                    "ETag": '"etag123"',
                },
                {
                    "Key": "cur/2026-10/billing_export.csv",
                    "LastModified": datetime(2026, 10, 31, 23, 59, tzinfo=UTC),
                    "Size": 1000000,
                    "ETag": '"etag456"',
                },
            ]
        }
    ]

    conn = AwsConnector(
        role_arn="arn:aws:iam::123456789012:role/FinOpsRole",
        external_id="ext-abc",
        s3_bucket="billing-bucket",
        s3_prefix="cur/",
        boto_session=mock_boto_session,
    )

    exports = conn.list_exports()
    # manifest.json excluded; sorted newest first
    assert len(exports) == 2
    assert exports[0].key == "cur/2026-11/billing_export_part1.csv.gz"
    assert exports[1].key == "cur/2026-10/billing_export.csv"

    mock_s3.get_object.return_value = {"Body": io.BytesIO(b"col1,col2\nval1,val2")}
    raw_bytes = conn.download_export("cur/2026-11/billing_export_part1.csv.gz")
    assert raw_bytes == b"col1,col2\nval1,val2"


def test_azure_and_gcp_stubs() -> None:
    azure = AzureConnector(
        storage_account="acc",
        container="cnt",
        client_id="cid",
        tenant_id="tid",
    )
    v_az = azure.verify()
    assert v_az.success is False
    assert "preview" in v_az.message
    assert azure.list_exports() == []
    with pytest.raises(NotImplementedError):
        azure.download_export("key")

    gcp = GcpConnector(
        project_id="p",
        dataset_id="d",
        table_name="t",
        service_account_email="sa@gcp.com",
    )
    v_gcp = gcp.verify()
    assert v_gcp.success is False
    assert "preview" in v_gcp.message
    assert gcp.list_exports() == []
    with pytest.raises(NotImplementedError):
        gcp.download_export("key")
