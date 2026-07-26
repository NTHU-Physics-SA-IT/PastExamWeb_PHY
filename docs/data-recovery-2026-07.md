# July 2026 local data recovery assessment

This document records aggregate evidence from a local, isolated recovery
exercise. It does not authorize production access or adoption of recovered
data. Dumps, manifests, object keys, local absolute paths, credentials, and
generated reports remain outside Git.

## Preserved incident resources

Before recovery work, the accident-era local database and its PostgreSQL
volume were preserved and copied to a verified custom-format logical dump.
The original MinIO volume and `archive-bucket` were left mounted and unchanged;
a read-only manifest reported 28 objects totaling 37,089,497 bytes. Recovery
and clean-development environments used new containers, networks, databases,
volumes, and buckets.

## July 12 dump

The immutable dump restored successfully into a new read-only PostgreSQL
database at revision `c4d8e2f1a6b9`. Its principal row counts were:

| Relation | Rows |
| --- | ---: |
| users | 7 |
| courses | 91 |
| course submissions | 0 |
| archive submissions | 29 |
| archives | 21 |
| archive discussion messages | 5 |
| personal notifications | 1 |
| course categories | 6 |
| memes | 24 |

All ten restored foreign keys were valid and no explicit orphan was found.
The data also contains obvious test pollution: two high-ID users, three
generated courses/submissions, and a generated archive. Recovery therefore
requires record-level review rather than wholesale activation.

The restored database contained 50 storage-reference rows representing 32
distinct object keys. Of those distinct keys, 27 matched the preserved MinIO
manifest. Five database keys (six reference rows) had no object; four were
obvious test fixtures and one appeared to be a real submission object. MinIO
contained one object with no July 12 database reference; its modification time
was after the dump. In row terms, 44 of 50 references had a matching object.

## Upgrade rehearsal

A second independent restore was used for migration rehearsal. Read-only
preflight validated all 60 checks for the reviewed `c4d8e2f1a6b9` manifest.
The safe migration CLI upgraded it to `e3b7c1d9f5a2`; postflight passed all
695 checks.

Before/after row counts and primary-key ranges were identical:

| Relation | Count | Min ID | Max ID |
| --- | ---: | ---: | ---: |
| users | 7 | 1 | 816 |
| courses | 91 | 1 | 766 |
| course submissions | 0 | — | — |
| archive submissions | 29 | 37 | 73 |
| archives | 21 | 111 | 457 |
| archive discussion messages | 5 | 13 | 17 |
| personal notifications | 1 | 1 | 1 |
| course categories | 6 | 1 | 6 |

All 50 storage-reference rows were byte-for-byte equal after normalization,
all 33 head-schema foreign keys were validated, and MinIO was not contacted by
the migration.

## Decision boundary

The old dump is valuable enough for further selective recovery: it contains
real users, courses, submissions, archives, discussions, notification data,
and mostly matching files, and it can migrate safely. It is not suitable for
automatic replacement because it is two weeks older than some surviving
objects, contains test pollution, and has missing file references.

Reasonable next options for the owner are:

- keep the dump and reports as a forensic/reference source;
- authorize a later, separately reviewed selective recovery plan;
- use the clean-development stack to verify current behavior;
- recreate current content through the website, reusing only independently
  verified files where appropriate.

No recovered row or object was merged into the normal local database during
this exercise.
