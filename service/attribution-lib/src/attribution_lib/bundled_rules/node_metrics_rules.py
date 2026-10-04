# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""
Node metrics rules ported from attribution_lib/node_metrics.py check().

Threshold-based attribution on Prometheus metrics.  Each rule matches the
metric name inside the ``render_metric_body`` text and captures the numeric
value for threshold comparison in the processor.
"""

import common.node_metrics_spec

from attribution_lib.observation.inbound import Source as ObservationSource
from attribution_lib.rules import MetricSpec, declare_event_types, register_metric_spec

rule_author = "NVIDIA Attribution team"

register_metric_spec(
    ObservationSource.NODE_METRICS,
    MetricSpec(thresholds=common.node_metrics_spec.metric_thresholds),
)
declare_event_types("Attribution.node.bad", "Attribution.node.interesting")
