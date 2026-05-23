import json

from qgis_udp_nav_plugin.model.feed_config import FeedConfig
from qgis_udp_nav_plugin.settings import store as store_module


class _MemorySettings:
    def __init__(self, storage: dict):
        self._storage = storage

    def value(self, key: str, default=""):
        return self._storage.get(key, default)

    def setValue(self, key: str, value) -> None:
        self._storage[key] = value


def _patch_settings_backend(monkeypatch):
    storage: dict = {}

    def factory():
        return _MemorySettings(storage)

    monkeypatch.setattr(store_module, "QgsSettings", factory)
    return storage


def test_load_feeds_returns_default_when_empty(monkeypatch) -> None:
    _patch_settings_backend(monkeypatch)

    settings = store_module.SettingsStore()
    feeds = settings.load_feeds()

    assert len(feeds) == 1
    assert feeds[0].feed_id == "feed-1"
    assert feeds[0].name == "Feed 1"


def test_load_feeds_returns_default_when_payload_is_invalid_json(monkeypatch) -> None:
    storage = _patch_settings_backend(monkeypatch)
    storage[store_module.SettingsStore.FEEDS_KEY] = "{not-json"

    settings = store_module.SettingsStore()
    feeds = settings.load_feeds()

    assert len(feeds) == 1
    assert feeds[0].feed_id == "feed-1"


def test_load_feeds_filters_invalid_entries_and_keeps_valid(monkeypatch) -> None:
    storage = _patch_settings_backend(monkeypatch)
    valid = FeedConfig(feed_id="feed-a", name="Feed A").to_dict()
    invalid_missing_name = {"feed_id": "feed-b"}
    invalid_type = "not-a-dict"
    storage[store_module.SettingsStore.FEEDS_KEY] = json.dumps(
        [valid, invalid_missing_name, invalid_type]
    )

    settings = store_module.SettingsStore()
    feeds = settings.load_feeds()

    assert len(feeds) == 1
    assert feeds[0].feed_id == "feed-a"
    assert feeds[0].name == "Feed A"


def test_save_feeds_persists_serialized_payload(monkeypatch) -> None:
    storage = _patch_settings_backend(monkeypatch)
    settings = store_module.SettingsStore()

    feeds = [
        FeedConfig(feed_id="feed-a", name="Feed A"),
        FeedConfig(feed_id="feed-b", name="Feed B", port=20220),
    ]
    settings.save_feeds(feeds)

    raw = storage[store_module.SettingsStore.FEEDS_KEY]
    payload = json.loads(raw)

    assert len(payload) == 2
    assert payload[0]["feed_id"] == "feed-a"
    assert payload[1]["port"] == 20220


def test_load_vessel_profiles_filters_invalid_entries(monkeypatch) -> None:
    storage = _patch_settings_backend(monkeypatch)
    storage[store_module.SettingsStore.VESSEL_PROFILES_KEY] = json.dumps(
        {
            "A": {"length": 10},
            "": {"length": 5},
            "B": "not-dict",
        }
    )

    settings = store_module.SettingsStore()
    profiles = settings.load_vessel_profiles()

    assert profiles == {"A": {"length": 10}}


def test_save_vessel_profiles_filters_invalid_entries(monkeypatch) -> None:
    storage = _patch_settings_backend(monkeypatch)
    settings = store_module.SettingsStore()

    settings.save_vessel_profiles(
        {
            "A": {"length": 10},
            "": {"length": 5},
            "B": "not-dict",
        }
    )

    raw = storage[store_module.SettingsStore.VESSEL_PROFILES_KEY]
    payload = json.loads(raw)

    assert payload == {"A": {"length": 10}}


def test_load_startup_mode_defaults_when_invalid(monkeypatch) -> None:
    storage = _patch_settings_backend(monkeypatch)
    storage[store_module.SettingsStore.STARTUP_MODE_KEY] = "invalid"

    settings = store_module.SettingsStore()

    assert settings.load_startup_mode() == store_module.SettingsStore.DEFAULT_STARTUP_MODE


def test_save_startup_mode_normalizes_invalid_to_default(monkeypatch) -> None:
    storage = _patch_settings_backend(monkeypatch)
    settings = store_module.SettingsStore()

    settings.save_startup_mode("unsupported")

    assert (
        storage[store_module.SettingsStore.STARTUP_MODE_KEY]
        == store_module.SettingsStore.DEFAULT_STARTUP_MODE
    )


def test_startup_mode_roundtrip_accepts_supported_values(monkeypatch) -> None:
    _patch_settings_backend(monkeypatch)
    settings = store_module.SettingsStore()

    settings.save_startup_mode("all")

    assert settings.load_startup_mode() == "all"
