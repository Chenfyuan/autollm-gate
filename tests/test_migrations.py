"""Alembic 迁移：新库可升级到最新；v0.1 旧库（create_all 建表、无 alembic_version）可原地升级并保留数据。"""
import asyncio, sqlite3, subprocess, sys
from autollm_admin.migrate import migrate


def test_fresh_db_migrates(tmp_path):
    url = f"sqlite:///{tmp_path}/a.db"
    asyncio.run(migrate(url))
    cols = {r[1] for r in sqlite3.connect(f"{tmp_path}/a.db").execute("pragma table_info(tenants)")}
    assert {"reserved_micro", "rpm_limit"} <= cols
    asyncio.run(migrate(url))  # 幂等


def test_v01_db_upgrades_in_place(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("""
      CREATE TABLE tenants (id VARCHAR(32) PRIMARY KEY, name VARCHAR(200) NOT NULL, balance_micro BIGINT NOT NULL,
        monthly_token_limit BIGINT, markup_pct FLOAT, active BOOLEAN NOT NULL, created_at DATETIME NOT NULL);
      CREATE TABLE api_keys (id VARCHAR(32) PRIMARY KEY, tenant_id VARCHAR(32) NOT NULL REFERENCES tenants(id), name VARCHAR(200) NOT NULL,
        prefix VARCHAR(16) NOT NULL, key_hash VARCHAR(64) NOT NULL UNIQUE, active BOOLEAN NOT NULL, created_at DATETIME NOT NULL, last_used_at DATETIME);
      CREATE TABLE upstream_keys (id VARCHAR(32) PRIMARY KEY, tenant_id VARCHAR(32), provider VARCHAR(32) NOT NULL, enc_key TEXT NOT NULL,
        hint VARCHAR(16) NOT NULL, active BOOLEAN NOT NULL, created_at DATETIME NOT NULL);
      CREATE TABLE usage (id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id VARCHAR(32) NOT NULL, api_key_id VARCHAR(32), model VARCHAR(100) NOT NULL,
        provider VARCHAR(32) NOT NULL, key_source VARCHAR(16) NOT NULL, strategy VARCHAR(32) NOT NULL, prompt_tokens INTEGER NOT NULL,
        completion_tokens INTEGER NOT NULL, cost_micro BIGINT NOT NULL, charge_micro BIGINT NOT NULL, latency_ms INTEGER NOT NULL,
        status VARCHAR(16) NOT NULL, created_at DATETIME NOT NULL);
      CREATE TABLE settings (key VARCHAR(64) PRIMARY KEY, value VARCHAR(200) NOT NULL);
      CREATE TABLE topups (id VARCHAR(32) PRIMARY KEY, tenant_id VARCHAR(32) NOT NULL, amount_micro BIGINT NOT NULL, channel VARCHAR(32) NOT NULL,
        status VARCHAR(16) NOT NULL, external_id VARCHAR(128), note VARCHAR(500) NOT NULL, created_at DATETIME NOT NULL, paid_at DATETIME);
      INSERT INTO tenants VALUES ('t1', '老客户', 5000000, NULL, NULL, 1, '2026-10-01 00:00:00');
    """)
    con.commit(); con.close()
    asyncio.run(migrate(f"sqlite:///{db}"))
    con = sqlite3.connect(db)
    assert con.execute("select name, balance_micro, reserved_micro from tenants").fetchone() == ("老客户", 5000000, 0)
    assert con.execute("select version_num from alembic_version").fetchone()[0] == "0003_v03"
