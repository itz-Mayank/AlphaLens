"""The explicit "macro data is not configured" provider —
`MACRO_PROVIDER=none` (the default). Returns an empty list rather than
raising, matching `NoneFundamentalsProvider`'s "unavailable, not
fabricated, not a crash" convention."""

from datetime import date

from app.providers.base import MacroDataProvider, MacroObservationData


class NoneMacroProvider(MacroDataProvider):
    def get_observations(
        self, series_id: str, *, start: date, end: date
    ) -> list[MacroObservationData]:
        return []
