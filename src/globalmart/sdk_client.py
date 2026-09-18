"""The single place that touches credentials.

No other module reads ``TargetProfile.token``. Keeping the surface at one function is
what lets a test assert that a secret never reaches a repr, a report or an exception.
"""

from __future__ import annotations

from gooddata_sdk import GoodDataSdk

from globalmart.config import TargetProfile


def make_sdk(profile: TargetProfile) -> GoodDataSdk:
    """Build an SDK client for a target profile."""
    return GoodDataSdk.create(host_=profile.host, token_=profile.token)
