"""Stage 6 – Ansible layout for MIG products (syntax, wiring, templates; ansible itself is not installed here)."""
import pathlib

import jinja2
import yaml

from tests.conftest import ROOT

A = ROOT / "ansible"


def test_all_yaml_parses():
    for f in A.rglob("*.yml"):
        yaml.safe_load(f.read_text())


def test_playbooks_use_existing_roles():
    for pb in (A / "playbooks").glob("*.yml"):
        for play in yaml.safe_load(pb.read_text()):
            for role in play.get("roles", []):
                assert (A / "roles" / role / "tasks" / "main.yml").exists(), role


def test_handlers_exist_for_notifications():
    for role in (A / "roles").iterdir():
        tasks = yaml.safe_load((role / "tasks" / "main.yml").read_text())
        handlers = {h["name"] for h in yaml.safe_load((role / "handlers" / "main.yml").read_text())}
        for t in tasks:
            if "notify" in t:
                assert t["notify"] in handlers


def test_templates_render():
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(A / "roles" / "app" / "templates")),
                             undefined=jinja2.StrictUndefined)
    defaults = yaml.safe_load((A / "roles" / "app" / "defaults" / "main.yml").read_text())
    vars_ = {**defaults, "product": "ledger", "app_version": "4.2.1"}
    unit = env.get_template("app.service.j2").render(**vars_)
    assert "ExecStart=/opt/app/bin/ledger --port 8080" in unit and "NoNewPrivileges=true" in unit
    loader = env.get_template("load-config.sh.j2").render(**vars_)
    assert "metadata.google.internal" in loader and "password" not in loader.lower()


def test_no_ssh_keys_or_secrets_in_ansible():
    for f in A.rglob("*"):
        if f.is_file():
            t = f.read_text().lower()
            assert "private_key" not in t and "begin rsa" not in t


def test_configure_play_is_rolling_and_targets_one_product_env():
    play = yaml.safe_load((A / "playbooks" / "configure.yml").read_text())[0]
    assert play["serial"] == "20%" and play["max_fail_percentage"] == 0
    assert play["hosts"] == "product_{{ product }}:&env_{{ env }}"
