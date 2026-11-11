Analysis used for docs/SIGNAL_AUDIT.md. Run against a copy of the logs:
  python extract_session_rows.py <predictions.csv> 0 9999999999 session.csv
  python stats.py            (reads session.csv)
  python forward_moves.py    (reads session.csv)
These scripts only read logs. They do not modify anything.
