"""Form definitions. Flask-WTF adds and checks the CSRF token on each."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    EmailField,
    FloatField,
    HiddenField,
    PasswordField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Email, Length, NumberRange, Optional

from finops_app.accounts import MAX_PASSWORD_LENGTH, ROLES
from finops_app.triage import NOTE_MAX, STATUS_LABELS

ROLE_CHOICES = [(r, r.capitalize()) for r in ROLES]
EMAIL_MAX = 320
NAME_MAX = 200


def _strip(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) else value


def _email_field() -> EmailField:
    return EmailField(
        "Email",
        filters=[_strip],
        validators=[
            DataRequired("Enter your email address."),
            Email("Enter a valid email address.", check_deliverability=False),
            Length(max=EMAIL_MAX),
        ],
    )


class LoginForm(FlaskForm):
    email = _email_field()
    password = PasswordField(
        "Password",
        validators=[DataRequired("Enter your password."), Length(max=MAX_PASSWORD_LENGTH)],
    )


class SignupForm(FlaskForm):
    name = StringField("Your name", filters=[_strip], validators=[Length(max=NAME_MAX)])
    email = _email_field()
    password = PasswordField("Password", validators=[DataRequired("Choose a password.")])
    org_name = StringField(
        "Organisation name",
        filters=[_strip],
        validators=[DataRequired("Name your organisation."), Length(max=NAME_MAX)],
    )


class AddMemberForm(FlaskForm):
    email = _email_field()
    role = SelectField("Role", choices=ROLE_CHOICES, default="viewer")


class ChangeRoleForm(FlaskForm):
    role = SelectField("Role", choices=ROLE_CHOICES)


class SwitchOrgForm(FlaskForm):
    org_id = HiddenField(validators=[DataRequired()])


class ConfirmForm(FlaskForm):
    """A form with only the CSRF token: sign out, remove member."""


class StatusForm(FlaskForm):
    status = SelectField("New status", choices=list(STATUS_LABELS.items()))
    snoozed_until = DateField("Snooze until", validators=[Optional()])
    note = TextAreaField("Note", filters=[_strip], validators=[Length(max=NOTE_MAX)])


class AwsConnectionForm(FlaskForm):
    name = StringField(
        "Connection Name",
        filters=[_strip],
        validators=[DataRequired("Enter a connection name."), Length(max=128)],
    )
    role_arn = StringField(
        "IAM Role ARN",
        filters=[_strip],
        validators=[DataRequired("Enter the IAM Role ARN."), Length(max=255)],
    )
    s3_bucket = StringField(
        "S3 Bucket Name",
        filters=[_strip],
        validators=[DataRequired("Enter the S3 bucket name."), Length(max=255)],
    )
    s3_prefix = StringField(
        "S3 Prefix (optional)", filters=[_strip], validators=[Optional(), Length(max=512)]
    )
    region = StringField(
        "AWS Region",
        default="us-east-1",
        filters=[_strip],
        validators=[DataRequired(), Length(max=64)],
    )


class BudgetForm(FlaskForm):
    scope_type = SelectField(
        "Scope",
        choices=[
            ("total", "Total Monthly Spend"),
            ("service", "Specific Service"),
            ("account", "Specific Account"),
        ],
        default="total",
    )
    scope_value = StringField(
        "Scope Value (optional)", filters=[_strip], validators=[Optional(), Length(max=255)]
    )
    monthly_amount = FloatField(
        "Monthly Budget ($)",
        validators=[
            DataRequired("Enter a budget amount."),
            NumberRange(min=0.01, message="Budget must be greater than zero."),
        ],
    )


class AlertConfigForm(FlaskForm):
    channel_type = SelectField(
        "Channel Type",
        choices=[("slack", "Slack Webhook"), ("email", "Email Address")],
        default="slack",
    )
    destination = StringField(
        "Destination (Webhook URL or Email)",
        filters=[_strip],
        validators=[DataRequired("Enter the webhook URL or email."), Length(max=512)],
    )
    notify_high_confidence = BooleanField("Notify on high-confidence waste findings", default=True)
    notify_budget_exceeded = BooleanField("Notify when forecast exceeds budget", default=True)
    notify_spend_spikes = BooleanField("Notify on day-over-day spend spikes", default=True)
    spike_threshold_percent = FloatField(
        "Spend Spike Threshold (%)",
        default=20.0,
        validators=[DataRequired(), NumberRange(min=1.0, max=1000.0)],
    )
    is_active = BooleanField("Active", default=True)
