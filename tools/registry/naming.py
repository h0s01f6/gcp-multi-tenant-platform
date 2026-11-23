"""Naming rules for registry-derived names (registry/naming-rules.md, review K18)."""
import re

CUSTOMER_RE = re.compile(r"^[a-z][a-z0-9]{2,9}$")      # 3-10 chars, no hyphens
PRODUCT_RE = re.compile(r"^[a-z][a-z0-9]{1,10}$")      # 2-11 chars, no hyphens
COHORT_RE = re.compile(r"^v[0-9]{1,3}$")
ENVS = ("dev", "stg", "uat", "prd")
SA_ID_RE = re.compile(r"^[a-z]([-a-z0-9]*[a-z0-9])$")  # Google IAM service-account ID
SA_MIN, SA_MAX = 6, 30
MYSQL_NAME_MAX = 32
SA_SUFFIXES = {"app": "", "ro": "-ro", "mig": "-mig"}


def env_tier(env):
    return "prd" if env == "prd" else "nonprd"


def tenant_sa_id(customer, product, env, purpose="app"):
    return f"{customer}-{product}-{env}{SA_SUFFIXES[purpose]}"


def derived_names(customer, product, env):
    return {
        "sa_ids": [tenant_sa_id(customer, product, env, p) for p in SA_SUFFIXES],
        "mysql_roles": [f"r_{customer}_{product}_{r}" for r in ("app", "ddl", "ro")],
        "database": f"{customer}_{product}",
        "namespace": f"{customer}-{product}-{env}",
    }


def validate_names(customer, product, env):
    """Return a list of error strings for one (customer, product, env); empty = valid."""
    errors = []
    if not CUSTOMER_RE.match(customer):
        errors.append(f"customer slug '{customer}' must match {CUSTOMER_RE.pattern}")
    if not PRODUCT_RE.match(product):
        errors.append(f"product slug '{product}' must match {PRODUCT_RE.pattern}")
    if env not in ENVS:
        errors.append(f"environment '{env}' must be one of {ENVS}")
    names = derived_names(customer, product, env)
    for sa in names["sa_ids"]:
        if not (SA_MIN <= len(sa) <= SA_MAX) or not SA_ID_RE.match(sa):
            errors.append(f"service-account ID '{sa}' ({len(sa)} chars) violates IAM rules (6-30, {SA_ID_RE.pattern})")
        if len(sa) > MYSQL_NAME_MAX:
            errors.append(f"MySQL username '{sa}' exceeds {MYSQL_NAME_MAX} chars")
    for role in names["mysql_roles"]:
        if len(role) > MYSQL_NAME_MAX:
            errors.append(f"MySQL role '{role}' exceeds {MYSQL_NAME_MAX} chars")
    return errors
