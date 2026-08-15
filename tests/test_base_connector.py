import pytest

from backend.connectors import base


def test_watch_normalise_les_champs_et_construit_uid():
    w = base.watch(
        boutique="Jackroad", reference="Ref. 126610LN",
        url="https://x.jp/item/1", prix_ttc=1100000,
    )
    assert w["boutique"] == "Jackroad"
    assert w["prix_ttc"] == 1100000
    assert w["uid"] == "Jackroad:126610LN:https://x.jp/item/1"
    assert w["images"] == []


def test_strip_html():
    assert base.strip_html("<p>Bon&nbsp;état</p>") == "Bon état"


def test_base_connector_collect_non_implemente():
    c = base.BaseConnector({"boutique": "X"})
    with pytest.raises(NotImplementedError):
        list(c.collect("full"))


class _FakeConnector(base.BaseConnector):
    """Connecteur factice : 3 items, dont 1 déjà en base."""
    def __init__(self, entry):
        super().__init__(entry)
        self.fetched = []

    def brands_to_scan(self):
        return ["x"]

    def iter_listing(self, brand):
        for i in (1, 2, 3):
            yield {"vendue": False, "id": i, "ref": f"R{i}"}

    def item_uid(self, item):
        return base.make_uid(self.boutique, item["ref"], f"/i/{item['id']}")

    def build_detail(self, item):
        self.fetched.append(item["id"])   # trace des fiches réellement ouvertes
        return base.watch(boutique=self.boutique, reference=item["ref"],
                          url=f"/i/{item['id']}", raw={"accessoires": "箱 保証書"})


def test_item_uid_saute_les_deja_en_base_sans_fetch():
    c = _FakeConnector({"boutique": "F", "full_set_only": False, "max_age_days": None})
    c.seen_uids = {base.make_uid("F", "R2", "/i/2")}   # item 2 déjà en base
    out = list(c.collect("full"))
    assert c.fetched == [1, 3]              # l'item 2 n'a PAS été ouvert
    assert {w["reference"] for w in out} == {"R1", "R3"}


def test_collect_parallele_meme_resultat_et_skip():
    entry = {"boutique": "F", "full_set_only": False, "max_age_days": None,
             "max_workers": 4}
    c = _FakeConnector(entry)
    c.seen_uids = {base.make_uid("F", "R2", "/i/2")}   # item 2 déjà en base
    out = list(c.collect("full"))
    assert sorted(c.fetched) == [1, 3]              # parallèle : item 2 sauté
    assert {w["reference"] for w in out} == {"R1", "R3"}


def test_examinees_memorisees_puis_reprise_instantanee():
    persisted = set()
    entry = {"boutique": "F", "full_set_only": False, "max_age_days": None}
    # 1er passage : ouvre les 3, les mémorise via le sink
    c1 = _FakeConnector(entry)
    c1.seen_sink = persisted.add
    list(c1.collect("full"))
    assert sorted(c1.fetched) == [1, 2, 3]
    assert len(persisted) == 3
    # 2e passage (reprise) avec les uids mémorisés : n'ouvre RIEN
    c2 = _FakeConnector(entry)
    c2.seen_uids = set(persisted)
    assert list(c2.collect("full")) == []
    assert c2.fetched == []
