# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import json
from datetime import datetime, timedelta, timezone

import pytest
from attribution_lib.observation.inbound import (
    Format as LibFormat,
    Source,
)

from app.util import TimeInterval
from app.v1.legacy_formats import _raw_loki_unpack, extract_body_and_node
from app.v1.observation import ObservationContextV1, ObservationFormat, ObservationV1
from tests.conftest import make_up_attributor_info

JOB_START = datetime(2025, 4, 15, 10, 0, tzinfo=timezone.utc)
JOB_END = datetime(2025, 4, 15, 11, 0, tzinfo=timezone.utc)
# Later than the job end, so a year-less timestamp proves it took its year from the job, not from here.
DECLARED_END = datetime(2026, 1, 10, tzinfo=timezone.utc)
TS_NS = 1744734437830498765
# The legacy float-seconds conversion rounded to the nearest microsecond.
TS_NS_LEGACY = 1744734437830499000


def _node(hostname: str) -> list[dict[str, str]]:
    return [{"kind": "node", "hostname": hostname}]


def _job_window(ji):
    return ji.job_start_time, ji.job_end_time


def _interest_window(ji):
    return ji.interest_start_time, ji.interest_end_time


@pytest.mark.parametrize(
    ("source", "format", "body", "expected_entries", "expected_window"),
    [
        (
            Source.APPLOG,
            ObservationFormat.RAW_LOG_LINES,
            "[E1231 23:57:09.5 ProcessGroupNCCL.cpp:1923] 3: watchdog timeout\nno timestamp",
            [
                {"body": "[E1231 23:57:09.5 ProcessGroupNCCL.cpp:1923] 3: watchdog timeout", "ts": 1735689429 * 10**9},
                {"body": "no timestamp", "ts": None},
            ],
            lambda ji: (None, None),
        ),
        (
            Source.APPLOG,
            ObservationFormat.LOKI_DICT_LIST,
            [{"timestamp": str(TS_NS), "line": json.dumps({"body": "0: line"})}],
            [{"body": "0: line", "ts": TS_NS_LEGACY}],
            lambda ji: (None, None),
        ),
        (
            Source.APPLOG,
            ObservationFormat.RAW_LOKI_STREAMS,
            [
                {
                    "stream": {"node_name": "node1", "pod": "worker-0"},
                    "values": [[str(TS_NS), json.dumps({"body": "0: line", "attributes": {"hostname": "node2"}})]],
                }
            ],
            [
                {
                    "body": "0: line",
                    "ts": TS_NS_LEGACY,
                    "resources": [{"kind": "node", "hostname": "node1"}, {"kind": "replica", "name": "worker-0"}],
                }
            ],
            lambda ji: (None, None),
        ),
        (
            Source.SYSLOG,
            ObservationFormat.LOKI_DICT_LIST,
            [{"timestamp": TS_NS, "node": "node2", "body": "kernel: Xid"}],
            [{"body": "kernel: Xid", "ts": TS_NS_LEGACY, "resources": _node("node2")}],
            _interest_window,
        ),
        (
            Source.HEALTH_CHECK,
            ObservationFormat.LOKI_DICT_LIST,
            [{"timestamp": 1744734437830, "node": "node3", "body": "check failed"}],
            [{"body": "check failed", "ts": 1744734437830000000, "resources": _node("node3")}],
            lambda ji: (ji.interest_start_time, ji.interest_end_time + timedelta(minutes=10)),
        ),
        (
            Source.HEALTH_CHECK,
            ObservationFormat.RAW_LOKI_STREAMS,
            [{"stream": {"pod": "ignored"}, "values": [[str(TS_NS), "Apr 15 10:00:00 node3 check failed"]]}],
            [{"body": "Apr 15 10:00:00 node3 check failed", "ts": TS_NS_LEGACY}],
            lambda ji: (ji.interest_start_time, ji.interest_end_time + timedelta(minutes=10)),
        ),
        (
            Source.UFMLOG,
            ObservationFormat.UFMLOG,
            [{"body": "(node4) node is Down", "node": "fabric-manager", "timestamp": TS_NS}],
            [{"body": "(node4) node is Down", "ts": TS_NS_LEGACY}],
            _job_window,
        ),
        (
            Source.NODE_METRICS,
            ObservationFormat.PROMETHEUS_METRICS,
            [{"timestamp": 1744734437, "value": "1", "metric": "m", "labels": {}, "node": "node5", "threshold": 5}],
            [
                {
                    "body": (
                        "time: 1744734437, metric_name: m, metric_value: 1, threshold: None, "
                        "cluster: None, node: node5, component: None"
                    ),
                    "ts": 1744734437 * 10**9,
                    "resources": _node("node5"),
                }
            ],
            _job_window,
        ),
        (
            Source.CSP_EVENT,
            ObservationFormat.CSP_EVENT_LIST,
            [
                {
                    "hostname": "node6",
                    "termination_timestamp_s": 1718452800.123456,
                    "category": "HOST_FAILURE",
                    "reason": "BAD_GPU",
                    "version": 1,
                    "source_event": {
                        "source": "s",
                        "event_id": "e",
                        "event_created_at": "t",
                        "event_region": "r",
                        "hostname": "node6",
                        "fault_id": "f",
                    },
                }
            ],
            [
                {
                    "body": (
                        "csp_event: category=HOST_FAILURE, reason=BAD_GPU, status=, source_event="
                        '{"event_created_at":"t","event_id":"e","event_region":"r","fault_id":"f",'
                        '"hostname":"node6","source":"s"}'
                    ),
                    "ts": 1718452800123456000,
                    "resources": _node("node6"),
                }
            ],
            lambda ji: (ji.job_start_time, None),
        ),
    ],
)
def test_legacy_body_converts_to_entry_timeseries_over_the_source_window(
    source, format, body, expected_entries, expected_window
):
    job_info = make_up_attributor_info("v1", job_start_time=JOB_START, job_end_time=JOB_END).to_lib_jobinfo()
    observation = ObservationV1(
        context=ObservationContextV1(
            time_interval=TimeInterval(start=JOB_START, end=DECLARED_END), source=source, format=format
        ),
        body=body if isinstance(body, str) else json.dumps(body),
    )

    lib_observation = observation.to_lib_observation(job_info)

    assert lib_observation.lines == [{"resources": None} | entry for entry in expected_entries]
    assert lib_observation.context.format is LibFormat.ENTRY_TIMESERIES
    lib_window = lib_observation.context.time_interval
    assert (lib_window.start, lib_window.end) == expected_window(job_info)


class TestExtractBodyAndNode:
    """Tests for extract_body_and_node covering all three envelope formats."""

    def test_raw_envelope_body_and_attributes(self):
        """Raw log envelope format: top-level 'body' + attributes.hostname."""
        parsed = {"body": "some syslog line", "attributes": {"hostname": "node-01"}}
        body, node = extract_body_and_node(parsed, None, '{"body":"..."}')
        assert body == "some syslog line"
        assert node == "node-01"

    def test_lepton_message(self):
        """Lepton format: top-level 'message', no attributes."""
        parsed = {"message": "lepton log line"}
        body, node = extract_body_and_node(parsed, None, '{"message":"..."}')
        assert body == "lepton log line"
        assert node is None

    def test_cloudevents_fm_log(self):
        """CloudEvents envelope: data.message + data.hostname."""
        raw = '{"data":{"hostname":"nvswitch-01","message":"nmxc-fm: Lost connection to GPU gpuGUID 0xabc"}}'
        parsed = json.loads(raw)
        body, node = extract_body_and_node(parsed, None, raw)
        assert "Lost connection to GPU" in body
        assert "gpuGUID 0xabc" in body
        assert node == "nvswitch-01"

    def test_cloudevents_does_not_overwrite_existing_node(self):
        """When node is already known, data.hostname should not overwrite it."""
        parsed = {"data": {"hostname": "nvswitch-01", "message": "fm log"}}
        body, node = extract_body_and_node(parsed, "already-set", "{}")
        assert body == "fm log"
        assert node == "already-set"

    def test_attributes_does_not_overwrite_existing_node(self):
        """When node is already known, attributes.hostname should not overwrite it."""
        parsed = {"body": "log line", "attributes": {"hostname": "attr-node"}}
        body, node = extract_body_and_node(parsed, "stream-node", "{}")
        assert body == "log line"
        assert node == "stream-node"

    def test_unknown_format_falls_back_to_raw_payload(self):
        """Unknown JSON structure falls back to the raw payload string."""
        raw = '{"specversion":"1.0","type":"event","data":{"severity":"INFO"}}'
        parsed = json.loads(raw)
        body, node = extract_body_and_node(parsed, None, raw)
        assert body == raw
        assert node is None

    def test_data_not_dict_falls_back_to_raw(self):
        """data field is a string, not a dict - skip CloudEvents path, fall back to raw."""
        raw = '{"data":"just a string"}'
        parsed = json.loads(raw)
        body, node = extract_body_and_node(parsed, None, raw)
        assert body == raw

    def test_raw_loki_unpack_cloudevents(self):
        """Integration: raw Loki unpacking correctly unpacks a CloudEvents FM log."""
        raw = json.dumps(
            {
                "data": {
                    "hostname": "nvswitch-02",
                    "message": "nmxc-fm: Lost connection to GPU gpuGUID 0xdef",
                }
            }
        )
        result = _raw_loki_unpack(1000000000, raw, None, None)
        assert "Lost connection to GPU" in result["body"]
        assert result["node"] == "nvswitch-02"

    def test_raw_loki_unpack_preserves_existing_node(self):
        """Raw Loki unpacking should not clobber node from stream labels."""
        raw = json.dumps({"body": "some log", "attributes": {"hostname": "attr-node"}})
        result = _raw_loki_unpack(1000000000, raw, "stream-node", None)
        assert result["node"] == "stream-node"
