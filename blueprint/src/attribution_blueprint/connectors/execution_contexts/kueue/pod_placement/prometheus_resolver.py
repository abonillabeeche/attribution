# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from loguru import logger

from attribution_blueprint.connectors.auth import Auth
from attribution_blueprint.connectors.execution_contexts.kueue.helpers import (
    controller_owner,
)
from attribution_blueprint.connectors.execution_contexts.kueue.pod_placement.models import PlacementQuery, PodPlacement
from attribution_blueprint.connectors.metrics.promql.client import (
    PrometheusClient,
    promql_string,
    re2_escape,
)
from attribution_blueprint.types import assert_aware

_PROMQL_METRIC_IDENTIFIER = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_PROMQL_LABEL_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class PrometheusPlacementResolver:
    """Recover Job and JobSet Pod placements from retained kube-state-metrics."""

    def __init__(
        self,
        *,
        endpoint: str,
        auth: Auth | None = None,
        timeout_seconds: float = 60.0,
        lookback_padding_seconds: int = 300,
        cluster: str | None = None,
        cluster_label: str | None = None,
        pod_info_metric: str = "kube_pod_info",
        pod_labels_metric: str = "kube_pod_labels",
        pod_controller_uid_label: str = "label_batch_kubernetes_io_controller_uid",
        batch_size: int = 20,
    ):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if lookback_padding_seconds < 0:
            raise ValueError("lookback_padding_seconds must not be negative")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if bool(cluster) != bool(cluster_label):
            raise ValueError("cluster and cluster_label must be configured together")
        if cluster_label is not None and not _PROMQL_LABEL_IDENTIFIER.fullmatch(cluster_label):
            raise ValueError(f"cluster_label is not a valid PromQL label name: {cluster_label!r}")
        for field, value in (
            ("pod_info_metric", pod_info_metric),
            ("pod_labels_metric", pod_labels_metric),
        ):
            if not _PROMQL_METRIC_IDENTIFIER.fullmatch(value):
                raise ValueError(f"{field} is not a valid PromQL metric name: {value!r}")
        if not _PROMQL_LABEL_IDENTIFIER.fullmatch(pod_controller_uid_label):
            raise ValueError(
                f"pod_controller_uid_label is not a valid PromQL label name: {pod_controller_uid_label!r}"
            )

        self.client = PrometheusClient(
            endpoint=endpoint,
            auth=auth,
            timeout_seconds=timeout_seconds,
        )
        self.lookback_padding_seconds = lookback_padding_seconds
        self.cluster = cluster
        self.cluster_label = cluster_label
        self.pod_info_metric = pod_info_metric
        self.pod_labels_metric = pod_labels_metric
        self.pod_controller_uid_label = pod_controller_uid_label
        self.batch_size = batch_size

    def placements_for_many(self, queries: list[PlacementQuery]) -> dict[str, list[PodPlacement]]:
        """Collect shared UID batches, then partition placements by Workload."""
        by_workload: dict[str, dict[str, PodPlacement]] = {}
        by_namespace: dict[str, list[PlacementQuery]] = defaultdict(list)
        for query in queries:
            if query.workload_uid in by_workload:
                raise ValueError(f"duplicate placement query for Workload UID {query.workload_uid}")
            start = assert_aware(query.start_time, "placement start_time")
            end = assert_aware(query.end_time, "placement end_time")
            if end < start:
                raise ValueError("placement end_time precedes start_time")
            by_workload[query.workload_uid] = {}
            if query.namespace and query.owner_job_uids:
                by_namespace[query.namespace].append(query)

        now = datetime.now(timezone.utc)
        for namespace, namespace_queries in sorted(by_namespace.items()):
            all_job_uids = sorted({uid for query in namespace_queries for uid in query.owner_job_uids})
            workload_uids_by_job_uid: dict[str, set[str]] = defaultdict(set)
            for query in namespace_queries:
                for job_uid in query.owner_job_uids:
                    workload_uids_by_job_uid[job_uid].add(query.workload_uid)

            for batch_index in range(0, len(all_job_uids), self.batch_size):
                batch = set(all_job_uids[batch_index : batch_index + self.batch_size])
                batch_queries = [query for query in namespace_queries if batch.intersection(query.owner_job_uids)]
                query_start = min(
                    query.start_time - timedelta(seconds=self.lookback_padding_seconds) for query in batch_queries
                )
                query_end = min(
                    now,
                    max(query.end_time + timedelta(seconds=self.lookback_padding_seconds) for query in batch_queries),
                )
                window_seconds = max(1, int((query_end - query_start).total_seconds()))
                promql = self._job_uids_query(
                    namespace=namespace,
                    owner_job_uids=batch,
                    window_seconds=window_seconds,
                )
                try:
                    result = self.client.query(
                        name=f"kueue_pod_placement_batch_{batch_index // self.batch_size + 1}",
                        query=promql,
                        timestamp=int(query_end.timestamp()),
                    )
                except Exception as error:
                    logger.warning(
                        f"Prometheus placement batch failed for namespace {namespace!r} "
                        f"and {len(batch)} Job UIDs: {error}"
                    )
                    continue

                for series in result:
                    labels = series.get("metric") or {}
                    owner_job_uid = labels.get(self.pod_controller_uid_label)
                    pod_uid = labels.get("uid")
                    pod_name = labels.get("pod")
                    node_name = labels.get("node")
                    if (
                        labels.get("namespace") != namespace
                        or owner_job_uid not in batch
                        or not all((pod_uid, pod_name, node_name))
                    ):
                        continue
                    placement: PodPlacement = {
                        "pod_uid": pod_uid,
                        "pod_name": pod_name,
                        "node_name": node_name,
                        "source": "prometheus",
                    }
                    for workload_uid in workload_uids_by_job_uid[owner_job_uid]:
                        previous = by_workload[workload_uid].setdefault(pod_uid, placement)
                        if previous != placement:
                            raise ValueError(f"Prometheus returned conflicting placement for Pod UID {pod_uid}")

        return {
            workload_uid: [placements[pod_uid] for pod_uid in sorted(placements)]
            for workload_uid, placements in by_workload.items()
        }

    def placements_for(
        self,
        workload: dict,
        start_time: datetime,
        end_time: datetime,
        *,
        owner_job_uids: set[str],
    ) -> list[PodPlacement]:
        """Return retained placements for a Job- or JobSet-owned Workload."""
        owner = controller_owner(workload)
        if owner is None or owner.get("kind") not in {"Job", "JobSet"}:
            return []

        metadata = workload.get("metadata") or {}
        namespace = metadata.get("namespace")
        if not namespace:
            return []
        owner_kind = owner["kind"]
        if owner_kind == "Job":
            owner_uid = owner.get("uid")
            job_uids = {owner_uid} if owner_uid else set()
        else:
            job_uids = owner_job_uids
        if not job_uids:
            return []

        start = assert_aware(start_time, "placement start_time")
        end = assert_aware(end_time, "placement end_time")
        if end < start:
            raise ValueError("placement end_time precedes start_time")
        now = datetime.now(timezone.utc)
        query_end = min(now, end + timedelta(seconds=self.lookback_padding_seconds))
        query_start = start - timedelta(seconds=self.lookback_padding_seconds)
        window_seconds = max(1, int((query_end - query_start).total_seconds()))

        query = self._job_uids_query(
            namespace=namespace,
            owner_job_uids=job_uids,
            window_seconds=window_seconds,
        )
        result = self.client.query(
            name=f"kueue_{owner_kind.lower()}_pod_placement",
            query=query,
            timestamp=int(query_end.timestamp()),
        )
        return self._placements_from_result(result, namespace)

    def _job_uids_query(
        self,
        *,
        namespace: str,
        owner_job_uids: set[str],
        window_seconds: int,
    ) -> str:
        # `node!=""` excludes samples for a Pod that hasn't been scheduled
        # yet, so an unscheduled sample can never masquerade as a recovered
        # placement.
        pod_matchers = [*self._base_matchers(namespace), 'node!=""']
        sorted_uids = sorted(owner_job_uids)
        if not sorted_uids:
            raise ValueError("owner_job_uids must not be empty")
        if len(sorted_uids) == 1:
            uid_matcher = f"{self.pod_controller_uid_label}={promql_string(sorted_uids[0])}"
        else:
            uid_pattern = "|".join(re2_escape(uid) for uid in sorted_uids)
            uid_matcher = f"{self.pod_controller_uid_label}=~{promql_string(uid_pattern)}"
        labels_matchers = [
            *self._base_matchers(namespace),
            uid_matcher,
        ]
        pod_selector = f"{self.pod_info_metric}{{{','.join(pod_matchers)}}}"
        labels_selector = f"{self.pod_labels_metric}{{{','.join(labels_matchers)}}}"

        # Window each raw metric independently, THEN join — never wrap the
        # join itself in a subquery. A subquery re-evaluates its inner
        # expression (here, the whole join) only at each step tick; a Pod
        # that existed only briefly between two ticks would then never
        # produce a joined sample, even though its raw kube_pod_labels/
        # kube_pod_info samples are still in storage. last_over_time on each
        # raw metric first retains that history regardless of tick timing.
        labels_last = f"last_over_time({labels_selector}[{window_seconds}s])"
        pod_last = f"last_over_time({pod_selector}[{window_seconds}s])"

        # Aggregate away exporter-identity labels (instance/prometheus/
        # replica/scrape-target labels an HA or federated backend such as
        # Thanos/Mimir can attach) before matching, keeping only the
        # semantic identity each side needs. Without this, two otherwise-
        # identical retained series for the same Pod produce a
        # "many-to-many matching not allowed" error and the whole batch's
        # recovery is lost. A genuine conflict (the same Pod UID reported
        # on two different nodes) still yields two distinct groups on the
        # right and correctly fails the join rather than silently picking
        # one node over the other.
        #
        # pod_controller_uid_label must be kept in the left side's `by`
        # clause: a PromQL aggregation drops every label not named in it,
        # and placements_for_many() reads that label back out of the
        # result to know which owner Job (and therefore which batched
        # Workload query) each joined series belongs to. Dropping it here
        # would silently discard every real result in the batched path.
        labels_deduped = f"group by (namespace,pod,uid,{self.pod_controller_uid_label}) ({labels_last})"
        pod_deduped = f"group by (namespace,pod,uid,node) ({pod_last})"

        return f"{labels_deduped} * on(namespace,pod,uid) group_left(node) {pod_deduped}"

    def _base_matchers(self, namespace: str) -> list[str]:
        matchers = [f"namespace={promql_string(namespace)}"]
        if self.cluster_label is not None and self.cluster is not None:
            matchers.insert(0, f"{self.cluster_label}={promql_string(self.cluster)}")
        return matchers

    @staticmethod
    def _placements_from_result(result: list[dict], namespace: str) -> list[PodPlacement]:
        by_uid: dict[str, PodPlacement] = {}
        for series in result:
            labels = series.get("metric") or {}
            pod_uid = labels.get("uid")
            pod_name = labels.get("pod")
            node_name = labels.get("node")
            if labels.get("namespace") != namespace or not all((pod_uid, pod_name, node_name)):
                continue
            placement: PodPlacement = {
                "pod_uid": pod_uid,
                "pod_name": pod_name,
                "node_name": node_name,
                "source": "prometheus",
            }
            previous = by_uid.setdefault(pod_uid, placement)
            if previous != placement:
                raise ValueError(f"Prometheus returned conflicting placement for Pod UID {pod_uid}")
        return [by_uid[uid] for uid in sorted(by_uid)]
