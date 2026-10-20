from app.models.port import Puerto


def test_kind_defaults_to_physical():
    p = Puerto(interface="GE0/0/1")
    assert p.kind == "physical"


def test_to_dict_from_dict_round_trips_kind():
    p = Puerto(interface="Eth-Trunk2", kind="aggregate")
    data = p.to_dict()
    assert data["kind"] == "aggregate"
    restored = Puerto.from_dict(data)
    assert restored.kind == "aggregate"


def test_from_dict_defaults_kind_when_missing():
    data = Puerto(interface="GE0/0/1").to_dict()
    del data["kind"]
    restored = Puerto.from_dict(data)
    assert restored.kind == "physical"
