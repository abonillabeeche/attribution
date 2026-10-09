// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { OutcomeKey } from '@/interfaces/attribution'
import { OUTCOMES } from '@/lib/attribution-data'
import { Badge } from '@/components/ui/badge'
import { cn, markInRow } from '@/lib/utils'

// The house StatusDots sm mark (a -500 fill inside a -400 edge), painted from
// the data-outcome tone in globals.css rather than per-status color classes.
export function OutcomeDot({ outcome }: { outcome: OutcomeKey }) {
  return (
    <span
      data-slot="outcome-dot"
      data-outcome={outcome}
      aria-hidden="true"
      className={cn('inline-block size-2 shrink-0 rounded-[2px] border border-(--tone-edge) bg-(--tone)', markInRow)}
    />
  )
}

// Color stays on the dot: the label is neutral text on an outline badge, so the
// badge never reads as a status fill (and never matches the solid zinc-subtle
// evidence badge in shape).
export function OutcomeBadge({ outcome, label, className }: { outcome: OutcomeKey; label?: string; className?: string }) {
  return (
    <Badge variant="outline" data-outcome={outcome} className={cn('gap-1.5', className)}>
      <OutcomeDot outcome={outcome} />
      {label || OUTCOMES[outcome].label}
    </Badge>
  )
}
