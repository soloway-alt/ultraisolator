// Pure row predicates for the ProcessTable filter bar, extracted from the
// component so the filter semantics are unit-testable without React.

export function processMatchesFilter(process, filter) {
  if (filter === 'all') {
    return true;
  }
  if (filter === 'game') {
    return Boolean(process.game)
      || process.status === 'game'
      || process.source === 'observed_game'
      || Boolean(process.tuning_state);
  }
  if (filter === 'protected') {
    return Boolean(process.protected) || process.status === 'protected';
  }
  return process.status === filter;
}

// `query` is expected pre-normalized (trimmed, lowercase) by the caller.
export function processMatchesQuery(process, query) {
  if (!query) {
    return true;
  }
  const haystack = `${process.pid || ''} ${process.name || ''} ${process.source || ''} ${process.status || ''}`.toLowerCase();
  return haystack.includes(query);
}
