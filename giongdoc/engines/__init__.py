"""GiongDoc TTS engines: edge (online neural), macsay (macOS offline), custom (consented cloning)."""
from giongdoc.engines import registry
from giongdoc.engines.custom import CustomEngine, CustomEngineConfig
from giongdoc.engines.custom_voices import (
    CONSENT_CHECKBOX_VI,
    CONSENT_TEXT_VI,
    ConsentRecord,
    CustomVoiceRecord,
    CustomVoiceStore,
)
from giongdoc.engines.edge import EdgeEngine
from giongdoc.engines.macsay import MacSayEngine, parse_say_voices

__all__ = [
    "registry", "EdgeEngine", "MacSayEngine", "CustomEngine", "CustomEngineConfig",
    "CustomVoiceStore", "CustomVoiceRecord", "ConsentRecord", "CONSENT_TEXT_VI",
    "CONSENT_CHECKBOX_VI", "parse_say_voices",
]
