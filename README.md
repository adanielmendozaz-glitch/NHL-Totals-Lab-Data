# NHL Totals Lab Data Feed

Public data feed used by the Android WebView to avoid direct CORS failures.

V0.4.2 / schema 6 adds:
- MoneyPuck opponent-adjusted current-season rolling xG form.
- NHL official schedule window extended to 14 prior days for rest/travel/fatigue context.
- Existing rosters, boxscore context, skaters, team and goalie data remain compatible.

The feed is refreshed by GitHub Actions. MoneyPuck data is credited to MoneyPuck.com.
