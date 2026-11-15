"""Vercel installs the API's dependencies from pyproject.toml (it prefers it over requirements.txt), while Docker
and CI use requirements.txt. If the two drift, a deployment can start without a package the code imports."""

import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]


def _requirements() -> list[str]:
    lines = (BACKEND / "requirements.txt").read_text(encoding="utf8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def test_pyproject_dependencies_match_requirements_txt():
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf8"))["project"]
    assert sorted(project["dependencies"]) == sorted(_requirements())


def test_every_runtime_import_is_declared():
    declared = {
        d.split("[")[0].split(">")[0].split("<")[0].split("=")[0].strip().lower().replace("_", "-")
        for d in _requirements()
    }
    for needed in (
        "fastapi",
        "uvicorn",
        "pydantic",
        "sqlalchemy",
        "asyncpg",
        "alembic",
        "cryptography",
        "argon2-cffi",
        "pyjwt",
        "httpx",
        "langchain-core",
        "langchain-openai",
        "pinecone",
    ):
        assert needed in declared, needed
