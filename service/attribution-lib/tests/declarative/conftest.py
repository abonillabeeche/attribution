# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

from contextlib import contextmanager

from attribution_lib.declarative.context import _using_rules_engine
from attribution_lib.rules_engine import RuleEngine


@contextmanager
def _with_engine():
    """Provide an engine that is active for rule registration."""
    engine = RuleEngine()
    with _using_rules_engine(engine):
        yield engine
