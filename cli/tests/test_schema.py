"""foundry.schema.json must accept everything manifest.py actually parses.

The schema once rejected the exact sshTunnel/devProdGuard/run blocks that
`foundry run dev` consumes (additionalProperties: false with the fields
undeclared) — an adopter authoring valid config saw it flagged in-editor.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "foundry.schema.json"


@pytest.fixture(scope="module")
def validator() -> Draft7Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema)


def _errors(validator: Draft7Validator, doc: dict) -> list[str]:
    return [
        f"{'/'.join(map(str, e.path))}: {e.message}"
        for e in validator.iter_errors(doc)
    ]


def test_minimal_manifest_validates(validator: Draft7Validator) -> None:
    doc = {"schemaVersion": "0.7.0", "name": "acme-platform", "services": {}}
    assert _errors(validator, doc) == []


def test_full_run_dev_service_validates(validator: Draft7Validator) -> None:
    """A multi-repo service manifest using every run-dev feature the CLI
    parses: sshTunnel (with AWS autowire), devProdGuard, sidecars, run block
    with debug/script/strictMode/object healthCheck."""
    doc = {
        "schemaVersion": "0.7.0",
        "name": "acme-svc",
        "services": {
            "api": {
                "scope": "internal",
                "stack": {"type": "backend", "framework": "spring-boot", "language": "java"},
                "enabled": True,
                "sshTunnel": {
                    "localPort": 15432,
                    "remoteHost": "${DB_PRIVATE_HOST}",
                    "remotePort": 5432,
                    "host": "${BASTION_HOST}",
                    "user": "ec2-user",
                    "password": "./.foundry/bastion-key.pem",
                    "bastionTag": "acme-prod-bastion",
                    "keySecret": "acme-prod/bastion/ssh-key",
                    "credentialsSecret": "acme-prod/api/credentials",
                    "injectEnv": {"PGUSER": "username"},
                    "awsRegion": "us-east-2",
                },
                "devProdGuard": {"env": {"SCHEDULER_ENABLED": "false"}},
                "sidecars": {
                    "openfga": {
                        "command": "docker",
                        "args": ["compose", "up", "openfga"],
                        "port": 4000,
                        "healthPath": "/healthz",
                        "readyPatterns": ["starting HTTP server"],
                    }
                },
                "run": {
                    "port": 8091,
                    "actuatorPort": 8092,
                    "args": ["-Dspring-boot.run.profiles=local"],
                    "env": {"FOO": "bar"},
                    "script": "mvn spring-boot:run",
                    "debug": {"port": 5005, "suspend": False},
                    "strictMode": {"enabled": True, "strictHealthPorts": False},
                    "healthCheck": {"path": "/actuator/health", "expectedStatus": 200},
                },
            }
        },
    }
    assert _errors(validator, doc) == []


def test_multi_tunnel_service_validates(validator: Draft7Validator) -> None:
    doc = {
        "schemaVersion": "0.7.0",
        "name": "acme-svc",
        "services": {
            "api": {
                "sshTunnels": {
                    "authService": {
                        "localPort": 18080, "remoteHost": "auth.internal",
                        "remotePort": 443, "host": "${BASTION_HOST}",
                        "env": {"AUTH_BASE_URL": "http://localhost:${localPort}"},
                    },
                    "db": {
                        "localPort": 15432, "remoteHost": "${DB_HOST}",
                        "remotePort": 5432, "host": "${BASTION_HOST}",
                        "credentialsSecret": "acme-prod/api/db",
                        "injectEnv": {"DB_USER": "username"},
                    },
                }
            }
        },
    }
    assert _errors(validator, doc) == []


def test_legacy_string_healthcheck_still_accepted(validator: Draft7Validator) -> None:
    doc = {
        "schemaVersion": "0.7.0",
        "name": "acme-svc",
        "services": {"web": {"run": {"port": 3000, "healthCheck": "/health"}}},
    }
    assert _errors(validator, doc) == []


def test_unknown_service_key_still_rejected(validator: Draft7Validator) -> None:
    doc = {
        "schemaVersion": "0.7.0",
        "name": "acme-svc",
        "services": {"api": {"definitelyNotAField": 1}},
    }
    assert _errors(validator, doc) != []
