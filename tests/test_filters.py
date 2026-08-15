from datetime import datetime, timezone, timedelta

from backend import filters


def test_full_set_exige_boite_et_papiers():
    assert filters.is_full_set("メーカー保証書／メーカー箱／冊子") is True
    assert filters.is_full_set("箱 ギャランティ 取扱説明書") is True
    assert filters.is_full_set("box and international warranty") is True


def test_pas_full_set_si_boite_seule_ou_papiers_seuls():
    assert filters.is_full_set("メーカー箱のみ") is False
    assert filters.is_full_set("保証書のみ") is False
    assert filters.is_full_set("") is False
    assert filters.is_full_set("本体のみ") is False


def test_full_set_mot_cle_direct():
    assert filters.is_full_set("フルセット") is True
    assert filters.is_full_set("付属品完備") is True


def test_negation_box_et_papiers_absents():
    # piège réel : "BOX無し 国際保証書無し" = SANS boîte, SANS garantie
    assert filters.is_full_set("メーカー純正BOX無し 国際保証書無し") is False
    assert filters.is_full_set("箱なし 保証書あり") is False  # boîte absente
    assert filters.is_full_set("純正箱あり 保証書なし") is False  # papiers absents


def test_negation_eloignee_et_manquant():
    # négation à distance ("は付属しません") et 欠品 (manquant)
    assert filters.is_full_set("純正箱あり 保証書は付属しません") is False
    assert filters.is_full_set("箱 欠品 / 保証書あり") is False


def test_recent_selon_age():
    today = datetime.now(timezone.utc)
    recent = (today - timedelta(days=30)).strftime("%Y/%m/%d")
    vieux = (today - timedelta(days=200)).strftime("%Y-%m-%d")
    assert filters.is_recent(recent, max_days=120) is True
    assert filters.is_recent(vieux, max_days=120) is False
    assert filters.is_recent("", max_days=120) is False
