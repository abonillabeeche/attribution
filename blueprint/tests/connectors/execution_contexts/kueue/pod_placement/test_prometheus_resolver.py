# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

from datetime import datetime, timezone

import pytest

from attribution_blueprint.connectors.execution_contexts.kueue.pod_placement.models import PlacementQuery
from attribution_blueprint.connectors.execution_contexts.kueue.pod_placement.prometheus_resolver import (
    PrometheusPlacementResolver,
)


def _job_workload(namespace="team-a", owner_name="train-job", owner_uid="job-uid-1"):
    return {
        "metadata": {
            "namespace": namespace,
            "ownerReferences": [
                {
                    "apiVersion": "batch/v1",
                    "kind": "Job",
                    "name": owner_name,
                    "uid": owner_uid,
                    "controller": True,
                }
            ],
        },
    }


def _jobset_workload(namespace="team-a", owner_name="train-jobset", owner_uid="jobset-uid-1"):
    return {
        "metadata": {
            "namespace": namespace,
            "ownerReferences": [
                {
                    "apiVersion": "jobset.x-k8s.io/v1alpha2",
                    "kind": "JobSet",
                    "name": owner_name,
                    "uid": owner_uid,
                    "controller": True,
                }
            ],
        }
    }


def _series(*, namespace, pod, uid, node, controller_uid="job-uid-1"):
    return {
        "metric": {
            "namespace": namespace,
            "pod": pod,
            "uid": uid,
            "node": node,
            "label_batch_kubernetes_io_controller_uid": controller_uid,
        }
    }


def _placement_query(
    workload_uid,
    *,
    namespace="team-a",
    owner_job_uids=("job-uid-1",),
    start_hour=0,
    end_hour=1,
):
    return PlacementQuery(
        workload_uid=workload_uid,
        namespace=namespace,
        owner_job_uids=frozenset(owner_job_uids),
        start_time=datetime(2026, 5, 1, start_hour, tzinfo=timezone.utc),
        end_time=datetime(2026, 5, 1, end_hour, tzinfo=timezone.utc),
    )


class TestConstructorValidation:
    def test_non_positive_timeout_rejected(self):
        with pytest.raises(ValueError, match="timeout_seconds"):
            PrometheusPlacementResolver(endpoint="https://prom.example", timeout_seconds=0)

    def test_negative_lookback_padding_rejected(self):
        with pytest.raises(ValueError, match="lookback_padding_seconds"):
            PrometheusPlacementResolver(endpoint="https://prom.example", lookback_padding_seconds=-1)

    def test_non_positive_batch_size_rejected(self):
        with pytest.raises(ValueError, match="batch_size"):
            PrometheusPlacementResolver(endpoint="https://prom.example", batch_size=0)

    def test_cluster_without_cluster_label_rejected(self):
        with pytest.raises(ValueError, match="cluster and cluster_label"):
            PrometheusPlacementResolver(endpoint="https://prom.example", cluster="c1")

    def test_cluster_label_without_cluster_rejected(self):
        with pytest.raises(ValueError, match="cluster and cluster_label"):
            PrometheusPlacementResolver(endpoint="https://prom.example", cluster_label="cluster")

    def test_cluster_and_cluster_label_together_accepted(self):
        source = PrometheusPlacementResolver(endpoint="https://prom.example", cluster="c1", cluster_label="cluster")
        assert source.cluster == "c1"
        assert source.cluster_label == "cluster"

    def test_invalid_cluster_label_rejected(self):
        with pytest.raises(ValueError, match="cluster_label"):
            PrometheusPlacementResolver(endpoint="https://prom.example", cluster="c1", cluster_label="not valid!")

    @pytest.mark.parametrize("field", ["pod_info_metric", "pod_labels_metric"])
    def test_invalid_metric_name_rejected(self, field):
        with pytest.raises(ValueError, match=field):
            PrometheusPlacementResolver(endpoint="https://prom.example", **{field: "not a metric!"})

    def test_invalid_controller_uid_label_rejected(self):
        with pytest.raises(ValueError, match="pod_controller_uid_label"):
            PrometheusPlacementResolver(
                endpoint="https://prom.example",
                pod_controller_uid_label="not valid!",
            )


class TestPlacementsForGuards:
    def _source(self):
        return PrometheusPlacementResolver(endpoint="https://prom.example")

    def test_unsupported_owner_kind_returns_empty(self):
        source = self._source()
        workload = {
            "metadata": {"namespace": "team-a"},
            "spec": {},
        }
        workload["metadata"]["ownerReferences"] = [{"kind": "CronJob", "name": "x", "uid": "u", "controller": True}]
        now = datetime(2026, 5, 1, tzinfo=timezone.utc)
        assert source.placements_for(workload, now, now, owner_job_uids=set()) == []

    def test_no_owner_returns_empty(self):
        source = self._source()
        workload = {"metadata": {"namespace": "team-a"}}
        now = datetime(2026, 5, 1, tzinfo=timezone.utc)
        assert source.placements_for(workload, now, now, owner_job_uids=set()) == []

    def test_missing_namespace_returns_empty(self, mocker):
        source = self._source()
        mocker.patch.object(source.client, "query")
        workload = _job_workload(namespace=None)
        now = datetime(2026, 5, 1, tzinfo=timezone.utc)
        assert source.placements_for(workload, now, now, owner_job_uids=set()) == []
        source.client.query.assert_not_called()

    def test_direct_job_without_owner_uid_returns_empty(self, mocker):
        source = self._source()
        mocker.patch.object(source.client, "query")
        workload = _job_workload(owner_uid=None)
        now = datetime(2026, 5, 1, tzinfo=timezone.utc)

        assert source.placements_for(workload, now, now, owner_job_uids=set()) == []
        source.client.query.assert_not_called()

    def test_jobset_without_child_job_uids_returns_empty(self, mocker):
        source = self._source()
        mocker.patch.object(source.client, "query")
        workload = _jobset_workload()
        now = datetime(2026, 5, 1, tzinfo=timezone.utc)

        assert source.placements_for(workload, now, now, owner_job_uids=set()) == []
        source.client.query.assert_not_called()

    def test_end_before_start_raises(self):
        source = self._source()
        workload = _job_workload()
        start = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
        end = datetime(2026, 5, 1, 11, 0, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="end_time precedes start_time"):
            source.placements_for(workload, start, end, owner_job_uids=set())


class TestUIDQueryConstruction:
    def test_single_job_uid_query_shape(self):
        """G6: last_over_time must wrap each raw metric individually (never
        the joined expression, never a subquery). G7: each side must be
        dedup-aggregated over its semantic identity labels before the join.
        `node!=""` on the info side excludes unscheduled samples."""
        source = PrometheusPlacementResolver(endpoint="https://prom.example")
        query = source._job_uids_query(
            namespace="team-a",
            owner_job_uids={"job-uid-1"},
            window_seconds=3600,
        )
        assert query == (
            "group by (namespace,pod,uid,label_batch_kubernetes_io_controller_uid) (last_over_time("
            'kube_pod_labels{namespace="team-a",'
            'label_batch_kubernetes_io_controller_uid="job-uid-1"}'
            "[3600s])) "
            "* on(namespace,pod,uid) group_left(node) "
            "group by (namespace,pod,uid,node) (last_over_time("
            'kube_pod_info{namespace="team-a",node!=""}'
            "[3600s]))"
        )

    def test_uid_query_includes_cluster_matcher_first(self):
        source = PrometheusPlacementResolver(endpoint="https://prom.example", cluster="prod", cluster_label="cluster")
        query = source._job_uids_query(
            namespace="team-a",
            owner_job_uids={"job-uid-1"},
            window_seconds=60,
        )
        assert 'kube_pod_info{cluster="prod",namespace="team-a",node!=""}' in query
        assert (
            'kube_pod_labels{cluster="prod",namespace="team-a",'
            'label_batch_kubernetes_io_controller_uid="job-uid-1"}'
        ) in query

    def test_uid_query_uses_custom_metric_and_label_names(self):
        source = PrometheusPlacementResolver(
            endpoint="https://prom.example",
            pod_info_metric="custom_pod_info",
            pod_labels_metric="custom_pod_labels",
            pod_controller_uid_label="controller_uid",
        )
        query = source._job_uids_query(
            namespace="team-a",
            owner_job_uids={"job-uid-1"},
            window_seconds=60,
        )
        assert "custom_pod_info{" in query
        assert 'custom_pod_labels{namespace="team-a",controller_uid="job-uid-1"}' in query

    def test_multiple_job_uids_use_sorted_escaped_regex(self):
        source = PrometheusPlacementResolver(endpoint="https://prom.example")
        query = source._job_uids_query(
            namespace="team-a",
            owner_job_uids={"job.uid-2", "job-uid-1"},
            window_seconds=1200,
        )
        assert 'label_batch_kubernetes_io_controller_uid=~"job-uid-1|job\\\\.uid-2"' in query

    def test_raw_metrics_are_windowed_before_the_join_not_the_joined_result(self):
        """G6 regression: `last_over_time` must appear once around each raw
        metric selector. It must NOT wrap the join itself (that structure
        is a subquery re-evaluated only at each step tick, which loses
        Pods that lived only between two ticks)."""
        source = PrometheusPlacementResolver(endpoint="https://prom.example")
        query = source._job_uids_query(
            namespace="team-a",
            owner_job_uids={"job-uid-1"},
            window_seconds=3600,
        )
        assert query.count("last_over_time(") == 2
        # The join operator must sit BETWEEN the two last_over_time(...)
        # results, not inside a last_over_time(...) itself.
        join_index = query.index("* on(namespace,pod,uid) group_left(node)")
        first_last_over_time_end = query.index("]))") + len("]))")
        assert join_index >= first_last_over_time_end
        assert not query.startswith("last_over_time((")

    def test_dedup_aggregation_wraps_each_side_before_the_join(self):
        """G7 regression: each side of the join must be pre-aggregated by
        its semantic identity (namespace/pod/uid[/node]) so duplicate
        exporter-replica series (differing only in instance/prometheus/
        replica labels on an HA/federated backend) collapse to one series
        per Pod before matching, instead of triggering a many-to-many
        matching error."""
        source = PrometheusPlacementResolver(endpoint="https://prom.example")
        query = source._job_uids_query(
            namespace="team-a",
            owner_job_uids={"job-uid-1"},
            window_seconds=60,
        )
        assert query.startswith("group by (namespace,pod,uid,label_batch_kubernetes_io_controller_uid) (last_over_time(")
        assert "group by (namespace,pod,uid,node) (last_over_time(" in query

    def test_dedup_aggregation_preserves_owner_uid_label(self):
        """Regression: a PromQL aggregation drops every label not named in
        its `by` clause. placements_for_many() reads
        `pod_controller_uid_label` back out of each result series to know
        which owner Job (and therefore which batched Workload query) it
        belongs to (see TestPlacementsForMany below) - if the left-hand
        aggregation drops that label, every real Prometheus result is
        silently discarded in the batched path even though the query
        itself succeeds."""
        source = PrometheusPlacementResolver(
            endpoint="https://prom.example",
            pod_controller_uid_label="custom_controller_uid",
        )
        query = source._job_uids_query(
            namespace="team-a",
            owner_job_uids={"job-uid-1"},
            window_seconds=60,
        )
        left_aggregation = query.split(" * on(namespace,pod,uid)")[0]
        assert left_aggregation.startswith("group by (")
        by_clause = left_aggregation[len("group by (") : left_aggregation.index(")")]
        by_labels = set(by_clause.split(","))
        assert source.pod_controller_uid_label in by_labels


class TestPlacementsForMany:
    def test_shared_query_is_partitioned_by_job_uid(self, mocker):
        source = PrometheusPlacementResolver(endpoint="https://prom.example")
        mock_query = mocker.patch.object(
            source.client,
            "query",
            return_value=[
                _series(namespace="team-a", pod="pod-a", uid="pod-uid-a", node="node-a", controller_uid="job-a"),
                _series(namespace="team-a", pod="pod-b", uid="pod-uid-b", node="node-b", controller_uid="job-b"),
            ],
        )

        result = source.placements_for_many(
            [
                _placement_query("workload-a", owner_job_uids=("job-a",)),
                _placement_query("workload-b", owner_job_uids=("job-b",), end_hour=2),
            ]
        )

        mock_query.assert_called_once()
        assert 'label_batch_kubernetes_io_controller_uid=~"job-a|job-b"' in mock_query.call_args.kwargs["query"]
        assert result["workload-a"] == [
            {"pod_uid": "pod-uid-a", "pod_name": "pod-a", "node_name": "node-a", "source": "prometheus"}
        ]
        assert result["workload-b"] == [
            {"pod_uid": "pod-uid-b", "pod_name": "pod-b", "node_name": "node-b", "source": "prometheus"}
        ]

    def test_job_uids_are_split_into_bounded_batches(self, mocker):
        source = PrometheusPlacementResolver(endpoint="https://prom.example", batch_size=1)
        mock_query = mocker.patch.object(source.client, "query", return_value=[])

        source.placements_for_many(
            [
                _placement_query("workload-a", owner_job_uids=("job-a",)),
                _placement_query("workload-b", owner_job_uids=("job-b",)),
            ]
        )

        assert mock_query.call_count == 2
        assert {call.kwargs["name"] for call in mock_query.call_args_list} == {
            "kueue_pod_placement_batch_1",
            "kueue_pod_placement_batch_2",
        }

    def test_namespaces_are_queried_separately(self, mocker):
        source = PrometheusPlacementResolver(endpoint="https://prom.example")
        mock_query = mocker.patch.object(source.client, "query", return_value=[])

        source.placements_for_many(
            [
                _placement_query("workload-a", namespace="team-a", owner_job_uids=("job-a",)),
                _placement_query("workload-b", namespace="team-b", owner_job_uids=("job-b",)),
            ]
        )

        assert mock_query.call_count == 2
        queries = [call.kwargs["query"] for call in mock_query.call_args_list]
        assert any('namespace="team-a"' in query and '"job-a"' in query for query in queries)
        assert any('namespace="team-b"' in query and '"job-b"' in query for query in queries)

    def test_duplicate_workload_uid_is_rejected(self):
        source = PrometheusPlacementResolver(endpoint="https://prom.example")
        query = _placement_query("workload-a")

        with pytest.raises(ValueError, match="duplicate placement query"):
            source.placements_for_many([query, query])


class TestPlacementsForDispatch:
    def test_job_owner_uses_owner_uid(self, mocker):
        source = PrometheusPlacementResolver(endpoint="https://prom.example")
        mock_query = mocker.patch.object(
            source.client,
            "query",
            return_value=[_series(namespace="team-a", pod="p1", uid="u1", node="n1")],
        )
        workload = _job_workload(namespace="team-a", owner_name="train-job")
        now = datetime(2026, 5, 1, tzinfo=timezone.utc)
        placements = source.placements_for(workload, now, now, owner_job_uids=set())

        assert placements == [{"pod_uid": "u1", "pod_name": "p1", "node_name": "n1", "source": "prometheus"}]
        kwargs = mock_query.call_args.kwargs
        assert kwargs["name"] == "kueue_job_pod_placement"
        assert 'label_batch_kubernetes_io_controller_uid="job-uid-1"' in kwargs["query"]
        assert "label_replace" not in kwargs["query"]

    def test_jobset_owner_uses_child_job_uids(self, mocker):
        source = PrometheusPlacementResolver(endpoint="https://prom.example")
        mock_query = mocker.patch.object(
            source.client,
            "query",
            return_value=[_series(namespace="team-a", pod="p1", uid="u1", node="n1")],
        )
        workload = _jobset_workload(namespace="team-a", owner_name="train-jobset")
        now = datetime(2026, 5, 1, tzinfo=timezone.utc)
        placements = source.placements_for(
            workload,
            now,
            now,
            owner_job_uids={"child-job-uid-2", "child-job-uid-1"},
        )

        assert placements == [{"pod_uid": "u1", "pod_name": "p1", "node_name": "n1", "source": "prometheus"}]
        kwargs = mock_query.call_args.kwargs
        assert kwargs["name"] == "kueue_jobset_pod_placement"
        assert (
            'label_batch_kubernetes_io_controller_uid=~"child-job-uid-1|child-job-uid-2"'
            in kwargs["query"]
        )
        assert "train-jobset" not in kwargs["query"]


class TestPlacementsFromResult:
    def test_multiple_pods_sorted_by_uid(self):
        result = [
            _series(namespace="ns", pod="p2", uid="u2", node="n2"),
            _series(namespace="ns", pod="p1", uid="u1", node="n1"),
        ]
        placements = PrometheusPlacementResolver._placements_from_result(result, "ns")
        assert [p["pod_uid"] for p in placements] == ["u1", "u2"]
        assert placements[0] == {"pod_uid": "u1", "pod_name": "p1", "node_name": "n1", "source": "prometheus"}

    def test_series_from_other_namespace_dropped(self):
        result = [_series(namespace="other-ns", pod="p1", uid="u1", node="n1")]
        assert PrometheusPlacementResolver._placements_from_result(result, "ns") == []

    @pytest.mark.parametrize("missing_label", ["uid", "pod", "node"])
    def test_series_missing_required_label_dropped(self, missing_label):
        series = _series(namespace="ns", pod="p1", uid="u1", node="n1")
        del series["metric"][missing_label]
        assert PrometheusPlacementResolver._placements_from_result([series], "ns") == []

    def test_duplicate_uid_same_placement_deduped(self):
        result = [
            _series(namespace="ns", pod="p1", uid="u1", node="n1"),
            _series(namespace="ns", pod="p1", uid="u1", node="n1"),
        ]
        placements = PrometheusPlacementResolver._placements_from_result(result, "ns")
        assert len(placements) == 1

    def test_conflicting_placement_for_same_uid_raises(self):
        result = [
            _series(namespace="ns", pod="p1", uid="u1", node="n1"),
            _series(namespace="ns", pod="p1", uid="u1", node="n2"),
        ]
        with pytest.raises(ValueError, match="conflicting placement"):
            PrometheusPlacementResolver._placements_from_result(result, "ns")
