from pathlib import Path

import yaml

from plugai_trade import backup, config, reference, updater


def test_backup_roundtrip(tmp_path):
    config.set_value("market", "US")
    msg = backup.create(tmp_path / "bk", passphrase="pw")
    f = next((tmp_path / "bk").glob("*.plugai"))
    config.set_value("market", "IN")
    assert "keys are not included" in msg
    assert "Restored" in backup.restore(f, passphrase="pw")
    assert config.get("market") == "US"


def test_update_diff(monkeypatch):
    new = reference.tables().copy()
    new = yaml.safe_load(yaml.safe_dump(new))
    new["india"]["contracts"]["NIFTY"]["lot"] = 75
    changes = updater.diff(reference.tables(), new)
    assert any(k == "india.contracts.NIFTY.lot" for k, *_ in changes)


def test_update_offline(monkeypatch):
    out = []
    assert updater.run(echo=out.append, url="http://127.0.0.1:9/none") == []
    assert "Could not reach" in out[0]
