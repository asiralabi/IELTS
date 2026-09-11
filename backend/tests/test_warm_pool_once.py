import asyncio
import sys
import types

from app.config import settings
from tools import warm_pool_once


def test_ci_with_empty_database_url_fails_before_importing_database(monkeypatch, capsys):
    monkeypatch.setenv("CI", "1")
    monkeypatch.setattr(settings, "database_url", "   ")
    monkeypatch.setattr(sys, "argv", ["warm_pool_once.py", "--report-only"])
    monkeypatch.setitem(sys.modules, "app.database", types.ModuleType("app.database"))

    assert asyncio.run(warm_pool_once.main()) == 2
    assert "POOL_DATABASE_URL" in capsys.readouterr().err
