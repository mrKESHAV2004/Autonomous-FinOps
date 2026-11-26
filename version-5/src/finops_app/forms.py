"""Form definitions. Flask-WTF adds and checks the CSRF token on each."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import EmailField, HiddenField, PasswordField, SelectField, StringField
from wtforms.validators import DataRequired, Email, Length

from finops_app.accounts import MAX_PASSWORD_LENGTH, ROLES

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
