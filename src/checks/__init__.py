"""Integrity checks run against the temporary restored database.

One module per check (tables exist, row counts, checksums, ...), each a plain
function that can be unit-tested on its own.
"""
