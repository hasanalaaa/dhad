//! Sweep-line span index and deterministic conflict resolution — ports of
//! `dhad.spans.FrozenSpanIndex` and `dhad.match.dedupe`.

use crate::rules::RuleMatch;
use std::collections::BTreeMap;

/// Immutable overlap oracle over possibly-overlapping char spans.
pub struct FrozenSpanIndex {
    starts: Vec<usize>,
    max_ends: Vec<usize>,
}

impl FrozenSpanIndex {
    pub fn new(mut spans: Vec<(usize, usize)>) -> Self {
        spans.sort_unstable();
        let starts = spans.iter().map(|(s, _)| *s).collect();
        let mut max_ends = Vec::with_capacity(spans.len());
        let mut running = 0usize;
        for (index, (_, end)) in spans.iter().enumerate() {
            running = if index == 0 { *end } else { running.max(*end) };
            max_ends.push(running);
        }
        Self { starts, max_ends }
    }

    pub fn len(&self) -> usize {
        self.starts.len()
    }

    pub fn is_empty(&self) -> bool {
        self.starts.is_empty()
    }

    /// True when [start, end) strictly overlaps any stored span.
    pub fn overlaps(&self, start: usize, end: usize) -> bool {
        let index = self.starts.partition_point(|s| *s < end);
        index > 0 && self.max_ends[index - 1] > start
    }
}

fn severity_rank(severity: &str) -> i32 {
    match severity {
        "error" => 3,
        "warning" => 2,
        _ => 1,
    }
}

/// Growing index over winner spans. Because accepted spans are disjoint, the
/// predecessor and successor in a balanced map are sufficient to answer an
/// overlap query. Lookup and insertion are both worst-case `O(log n)`.
struct DisjointSpanIndex {
    spans: BTreeMap<usize, usize>,
}

impl DisjointSpanIndex {
    fn new() -> Self {
        Self {
            spans: BTreeMap::new(),
        }
    }

    fn overlaps(&self, start: usize, end: usize) -> bool {
        if self
            .spans
            .range(..=start)
            .next_back()
            .is_some_and(|(_, stored_end)| *stored_end > start)
        {
            return true;
        }
        self.spans
            .range((std::ops::Bound::Excluded(start), std::ops::Bound::Unbounded))
            .next()
            .is_some_and(|(stored_start, _)| *stored_start < end)
    }

    fn insert(&mut self, start: usize, end: usize) {
        self.spans.insert(start, end);
    }

    #[cfg(test)]
    fn len(&self) -> usize {
        self.spans.len()
    }
}

/// Port of `dhad.match.dedupe`: global winner selection by priority,
/// confidence, severity, replacement presence, span length, then position —
/// returned in source order. Comparison keys mirror the Python sort exactly.
pub fn dedupe_indices(matches: &[RuleMatch]) -> Vec<usize> {
    let mut ranked: Vec<usize> = (0..matches.len()).collect();
    ranked.sort_by(|left, right| {
        let a = &matches[*left];
        let b = &matches[*right];
        b.priority
            .cmp(&a.priority)
            .then(
                b.confidence
                    .partial_cmp(&a.confidence)
                    .expect("confidence is finite"),
            )
            .then(severity_rank(&b.severity).cmp(&severity_rank(&a.severity)))
            .then((!b.replacements.is_empty()).cmp(&!a.replacements.is_empty()))
            .then(b.length.cmp(&a.length))
            .then(a.offset.cmp(&b.offset))
            .then(a.rule_id.cmp(&b.rule_id))
    });
    let mut kept: Vec<usize> = Vec::new();
    let mut winners = DisjointSpanIndex::new();
    for index in ranked {
        let candidate = &matches[index];
        let start = candidate.offset;
        let end = candidate.offset + candidate.length;
        if !winners.overlaps(start, end) {
            winners.insert(start, end);
            kept.push(index);
        }
    }
    kept.sort_by(|left, right| {
        let a = &matches[*left];
        let b = &matches[*right];
        a.offset
            .cmp(&b.offset)
            .then((a.offset + a.length).cmp(&(b.offset + b.length)))
            .then(a.rule_id.cmp(&b.rule_id))
    });
    kept
}

pub fn dedupe(matches: Vec<RuleMatch>) -> Vec<RuleMatch> {
    let indices = dedupe_indices(&matches);
    let mut slots: Vec<Option<RuleMatch>> = matches.into_iter().map(Some).collect();
    indices
        .into_iter()
        .map(|index| slots[index].take().expect("winner index is unique"))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::DisjointSpanIndex;

    #[test]
    fn ordered_insertions_are_backed_by_a_logarithmic_index() {
        let mut index = DisjointSpanIndex::new();
        for start in (0..8192).step_by(2) {
            assert!(!index.overlaps(start, start + 1));
            index.insert(start, start + 1);
        }
        assert_eq!(index.len(), 4096);
    }
}
