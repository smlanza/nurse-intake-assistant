from types import MappingProxyType
from typing import Final, Mapping


SAFE_HOSTED_SETTINGS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "APP_MODE": "mock",
        "AI_PROVIDER": "mock",
        "AGENT_PROVIDER": "mock",
        "SPEECH_PROVIDER": "mock",
        "EMAIL_PROVIDER": "mock",
        "SMS_PROVIDER": "mock",
        "DEMO_SUPPRESS_NOTIFICATIONS": "true",
    }
)
REMOTE_BUILD_SETTING: Final = "SCM_DO_BUILD_DURING_DEPLOYMENT"
REMOTE_BUILD_VALUE: Final = "true"
