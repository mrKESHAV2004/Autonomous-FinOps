"""AWS billing connector: assumes IAM role via STS and pulls CUR 2.0 / FOCUS exports from S3."""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

import boto3
from botocore.exceptions import ClientError

from finops_app.connectors.base import (
    BaseConnector,
    ConnectorVerificationResult,
    DiscoveredExport,
)

logger = logging.getLogger(__name__)

DEFAULT_APP_AWS_ACCOUNT = "123456789012"  # FinOps SaaS account ID for trust policy


class AwsConnector(BaseConnector):
    """Connects to AWS S3 using STS AssumeRole with external ID."""

    def __init__(
        self,
        *,
        role_arn: str,
        external_id: str,
        s3_bucket: str,
        s3_prefix: str = "",
        region: str = "us-east-1",
        boto_session: boto3.Session | None = None,
    ) -> None:
        self.role_arn = role_arn.strip()
        self.external_id = external_id.strip()
        self.s3_bucket = s3_bucket.strip()
        self.s3_prefix = s3_prefix.strip().lstrip("/") if s3_prefix else ""
        self.region = region.strip() or "us-east-1"
        self._session = boto_session or boto3.Session(region_name=self.region)

    def _get_s3_client(self) -> Any:
        """Assume the cross-account role and return an authenticated S3 client."""
        sts = self._session.client("sts", region_name=self.region)
        resp = sts.assume_role(
            RoleArn=self.role_arn,
            RoleSessionName="FinOpsBillingConnector",
            ExternalId=self.external_id,
            DurationSeconds=3600,
        )
        creds = resp["Credentials"]
        return self._session.client(
            "s3",
            region_name=self.region,
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )

    def verify(self) -> ConnectorVerificationResult:
        """Verify STS AssumeRole and S3 bucket read access."""
        try:
            s3 = self._get_s3_client()
            # Test listing the bucket with a 1-key limit
            resp = s3.list_objects_v2(
                Bucket=self.s3_bucket,
                Prefix=self.s3_prefix,
                MaxKeys=1,
            )
            key_count = resp.get("KeyCount", 0)
            return ConnectorVerificationResult(
                success=True,
                message=f"Connected successfully to s3://{self.s3_bucket}/{self.s3_prefix} ({key_count} object(s) checked)",
                details={
                    "bucket": self.s3_bucket,
                    "prefix": self.s3_prefix,
                    "role_arn": self.role_arn,
                },
            )
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "UnknownError")
            err_msg = e.response.get("Error", {}).get("Message", str(e))
            logger.warning("AWS verification failed (%s): %s", code, err_msg)
            if code in ("AccessDenied", "UnauthorizedOperation"):
                msg = (
                    f"Access Denied: Please check IAM Role trust policy allows external ID "
                    f"'{self.external_id}' and S3 policy grants s3:ListBucket / s3:GetObject on bucket '{self.s3_bucket}'."
                )
            elif code == "NoSuchBucket":
                msg = f"S3 Bucket '{self.s3_bucket}' does not exist or is in another region."
            else:
                msg = f"AWS connection failed ({code}): {err_msg}"
            return ConnectorVerificationResult(
                success=False,
                message=msg,
                details={"error_code": code, "error_message": err_msg},
            )
        except Exception as e:
            logger.exception("Unexpected error verifying AWS connection")
            return ConnectorVerificationResult(
                success=False,
                message=f"Connection verification failed: {e}",
            )

    def list_exports(self) -> list[DiscoveredExport]:
        """List billing export files in S3, sorted newest to oldest."""
        s3 = self._get_s3_client()
        paginator = s3.get_paginator("list_objects_v2")
        exports: list[DiscoveredExport] = []

        for page in paginator.paginate(Bucket=self.s3_bucket, Prefix=self.s3_prefix):
            for item in page.get("Contents", []):
                key = item["Key"]
                # Only include billing data files (CSV, CSV.GZ, parquet)
                lower_key = key.lower()
                if lower_key.endswith((".csv", ".csv.gz", ".parquet")) and not lower_key.endswith(
                    ("manifest.json", ".json")
                ):
                    exports.append(
                        DiscoveredExport(
                            key=key,
                            last_modified=item["LastModified"],
                            size_bytes=item["Size"],
                            etag=item.get("ETag", "").strip('"'),
                        )
                    )

        # Sort newest first
        exports.sort(key=lambda x: x.last_modified, reverse=True)
        return exports

    def download_export(self, key: str) -> bytes:
        """Download a billing export file from S3."""
        s3 = self._get_s3_client()
        resp = s3.get_object(Bucket=self.s3_bucket, Key=key)
        return resp["Body"].read()

    @classmethod
    def generate_cloudformation_template(
        cls,
        *,
        external_id: str,
        s3_bucket: str,
        app_aws_account_id: str = DEFAULT_APP_AWS_ACCOUNT,
        role_name: str = "FinOpsReadOnlyRole",
    ) -> dict[str, Any]:
        """Generate a CloudFormation template dict to create the cross-account role."""
        return {
            "AWSTemplateFormatVersion": "2010-09-09",
            "Description": "IAM role for Autonomous-FinOps read-only billing export access",
            "Parameters": {
                "ExternalId": {
                    "Type": "String",
                    "Default": external_id,
                    "Description": "Unique external ID provided by FinOps.AI",
                },
                "ExportBucketName": {
                    "Type": "String",
                    "Default": s3_bucket,
                    "Description": "Name of the S3 bucket where FOCUS / CUR 2.0 is exported",
                },
            },
            "Resources": {
                "FinOpsCrossAccountRole": {
                    "Type": "AWS::IAM::Role",
                    "Properties": {
                        "RoleName": role_name,
                        "AssumeRolePolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Principal": {"AWS": f"arn:aws:iam::{app_aws_account_id}:root"},
                                    "Action": "sts:AssumeRole",
                                    "Condition": {
                                        "StringEquals": {"sts:ExternalId": {"Ref": "ExternalId"}}
                                    },
                                }
                            ],
                        },
                        "Policies": [
                            {
                                "PolicyName": "FinOpsBillingReadPolicy",
                                "PolicyDocument": {
                                    "Version": "2012-10-17",
                                    "Statement": [
                                        {
                                            "Effect": "Allow",
                                            "Action": [
                                                "s3:ListBucket",
                                                "s3:GetBucketLocation",
                                            ],
                                            "Resource": {
                                                "Fn::Sub": "arn:aws:s3:::${ExportBucketName}"
                                            },
                                        },
                                        {
                                            "Effect": "Allow",
                                            "Action": ["s3:GetObject"],
                                            "Resource": {
                                                "Fn::Sub": "arn:aws:s3:::${ExportBucketName}/*"
                                            },
                                        },
                                    ],
                                },
                            }
                        ],
                    },
                }
            },
            "Outputs": {
                "RoleArn": {
                    "Description": "Paste this ARN into Autonomous-FinOps",
                    "Value": {"Fn::GetAtt": ["FinOpsCrossAccountRole", "Arn"]},
                }
            },
        }

    @classmethod
    def generate_quick_create_url(
        cls,
        *,
        external_id: str,
        s3_bucket: str,
        region: str = "us-east-1",
        app_aws_account_id: str = DEFAULT_APP_AWS_ACCOUNT,
    ) -> str:
        """Generate an AWS Console URL with query parameters for CloudFormation creation."""
        base_url = f"https://console.aws.amazon.com/cloudformation/home?region={region}#/stacks/create/review"
        params = {
            "stackName": "AutonomousFinOpsIntegration",
            "param_ExternalId": external_id,
            "param_ExportBucketName": s3_bucket,
        }
        return f"{base_url}?{urllib.parse.urlencode(params)}"
