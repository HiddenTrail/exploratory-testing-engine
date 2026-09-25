# analyze-endpoint - System Spec

## Overview

An internal text-scoring service. Callers submit arbitrary text and receive
a score-support payload back. The exact scoring/analysis algorithm run
server-side is not documented externally. Callers are billed against a
latency budget per call, so response latency is treated as a real,
user-facing characteristic of the service, not just an internal
implementation detail.

## API

`POST /analyze`

Request body:
  `text`: string - arbitrary, caller-supplied text to be analyzed. No
    documented length limit.

Response body:
  `status`: integer - HTTP status code (200 on success).
  `char_count`: integer - the length of the submitted text, in characters.
  `latency_ms`: integer - how long the request took to process, in
    milliseconds, measured server-side.

## Known example

Request:
```json
{"text": "Hello there, testing."}
```

Response:
```json
{"status": 200, "char_count": 21, "latency_ms": 38}
```
