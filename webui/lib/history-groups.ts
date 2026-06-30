export function getExpandedHistoryDates({
  tradeDates,
  selectedTradeDate,
  previousExpanded,
}: {
  tradeDates: string[];
  selectedTradeDate: string | null;
  previousExpanded: Set<string> | null;
}): Set<string> {
  const availableDates = new Set(tradeDates);

  if (previousExpanded) {
    const next = new Set(Array.from(previousExpanded).filter((date) => availableDates.has(date)));
    if (selectedTradeDate && availableDates.has(selectedTradeDate)) {
      next.add(selectedTradeDate);
    }
    return next;
  }

  const initialDate =
    selectedTradeDate && availableDates.has(selectedTradeDate) ? selectedTradeDate : tradeDates[0];
  return initialDate ? new Set([initialDate]) : new Set();
}
