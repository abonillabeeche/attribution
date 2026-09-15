# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Structured identity for related symptoms."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType, UnionType
from typing import TypeAlias, TypeVar

FamilyPropertyType: TypeAlias = type | UnionType
_Value = TypeVar("_Value")


def _immutable_mapping(values: Mapping[str, _Value], *, field_name: str) -> Mapping[str, _Value]:
    """Validate and defensively freeze a family mapping.

    Args:
        values: Property names and their type specifications or resolved values.
        field_name: Public field name used in validation errors.

    Returns:
        An immutable copy of ``values``.

    Raises:
        TypeError: If a property value is not hashable.
    """
    copied = dict(values)
    for name, value in copied.items():
        try:
            hash(value)
        except TypeError as exc:
            raise TypeError(f"SymptomFamily {field_name}[{name!r}] must be hashable") from exc
    return MappingProxyType(copied)


@dataclass(frozen=True, slots=True)
class SymptomFamily:
    """Describe either a symptom-family schema or one family member.

    A family declaration may supply ``property_types``. A concrete member may
    supply ``properties``; both can be empty for name-only membership. Keeping
    the mutually exclusive forms in one value type lets declarations, emitted
    events, and runtime symptoms share the same representation.

    Attributes:
        name: Rule-defined family name.
        property_types: Property schema supplied by a family declaration.
        properties: Resolved property values supplied by a family member.
    """

    name: str
    property_types: Mapping[str, FamilyPropertyType] = field(default_factory=dict)
    properties: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate the family form and freeze caller-owned mappings.

        Raises:
            ValueError: If the name is empty or both family forms are supplied.
            TypeError: If a property value is not hashable.
        """
        if self.name.strip() == "":
            raise ValueError("SymptomFamily name must be non-empty")
        if len(self.property_types) > 0 and len(self.properties) > 0:
            raise ValueError("SymptomFamily cannot define both property_types and properties")
        object.__setattr__(
            self,
            "property_types",
            _immutable_mapping(self.property_types, field_name="property_types"),
        )
        object.__setattr__(
            self,
            "properties",
            _immutable_mapping(self.properties, field_name="properties"),
        )

    def __hash__(self) -> int:
        """Return a hash independent of input mapping order.

        Returns:
            Hash derived from the complete structured family value.
        """
        return hash(
            (
                self.name,
                tuple(sorted(self.property_types.items())),
                tuple(sorted(self.properties.items())),
            )
        )
