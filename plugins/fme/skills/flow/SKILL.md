---
name: flow
description: Run, monitor and cancel FME Flow (formerly FME Server) jobs with the REST API or Safe's fmeflow CLI, choosing REST API V3 or V4 from the server build. Use for submitting workspaces, passing published parameters, polling job status, or scripting Flow from CI.
---

# FME Flow jobs

## Choose the API from the server build

FME Flow has two job APIs, and which one to call depends on the server. REST
API V4 arrived with FME Flow 2025.1. V3 is deprecated from 2025.1 and removed in
2026.1. Ask the server for its build before writing any request:

```
curl -s -H "Authorization: fmetoken token=$FME_FLOW_TOKEN" https://flow.example.com/fmeinfo/version
```

The JSON carries `buildNumber` and `buildString`. Older servers that don't
answer there report their build from `GET /fmerest/v3/info`.

Safe's own fmeflow CLI switches on these build numbers. Follow the same rules:

| Server build | Tokens and info | Job submission |
| --- | --- | --- |
| below 25208 | V3 | V3 |
| 25208 to 26017 | V4 | V3 |
| 26018 and above | V4 | V4 |

## Authentication

Both APIs take `Authorization: fmetoken token=<token>`. Read the token from an
environment variable such as `FME_FLOW_TOKEN`. Never write it into a script,
workspace or commit, and redact it from any output you show. The user creates
tokens in the FME Flow web interface, or the CLI generates one with
`fmeflow login --user`.

## Prefer the fmeflow CLI when it is installed

[fmeflow](https://github.com/safesoftware/fmeflow-cli) is Safe's CLI. It picks
V3 or V4 itself, which removes a whole class of mistakes. It installs as a
single binary from its releases page.

```
fmeflow login https://flow.example.com --token "$FME_FLOW_TOKEN"
fmeflow run --repository Samples --workspace austinApartments.fmw --wait
fmeflow run --repository Samples --workspace austinDownload.fmw \
  --published-parameter COORDSYS=TX83-CF \
  --published-parameter-list THEMES=railroad,airports
fmeflow run --repository Samples --workspace austinApartments.fmw --queue Queue1 --max-time-in-queue 120
fmeflow run --repository Samples --workspace austinApartments.fmw --file Landmarks-edited.sqlite --wait
fmeflow info
```

`--repository` and `--workspace` are required. `--wait` runs the job
synchronously. `login` saves the server URL, token and build to the CLI's
config file, so the token lives on disk from then on; tell the user. Use
`fmeflow jobs --help` and `fmeflow cancel --help` for listing and cancelling.

## REST API V4

For build 26018 and above.

Submit a job. `POST /fmeapiv4/jobs` queues it; `POST /fmeapiv4/jobs/sync` waits
and returns the result.

```
curl -s -X POST "https://flow.example.com/fmeapiv4/jobs" \
  -H "Authorization: fmetoken token=$FME_FLOW_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "repository": "Samples",
        "workspace": "austinDownload.fmw",
        "publishedParameters": {"COORDSYS": "TX83-CF", "THEMES": ["railroad", "airports"]},
        "queue": "Queue1"
      }'
```

The body is an object:

- `repository` and `workspace`.
- `publishedParameters`: a map of name to value. A list parameter takes an array.
- Optional: `queue`, `directives` (a map), `successTopics`, `failureTopics`,
  `maxJobRuntime` and `maxTimeInQueue` (seconds).
- `maxTotalLifeTime` (1 to 86400 seconds) covers queue plus run time. Safe's CLI
  sends it only for synchronous jobs.

The response carries the job `id`. A finished job reports `status`,
`statusMessage`, `featureOutputCount`, `timeQueued`, `timeStarted` and
`timeFinished`.

| Task | Request |
| --- | --- |
| One job | `GET /fmeapiv4/jobs/{id}` |
| List jobs | `GET /fmeapiv4/jobs` |
| Cancel | `POST /fmeapiv4/jobs/{id}/cancel` |

Every Flow server serves interactive V4 documentation at
`https://<host>/fmeapiv4/docs/index.html`, including a "Migrating from REST API
V3" section. Check it for anything not listed here, such as job logs and
filters, rather than guessing a path.

## REST API V3

For builds below 26018. V3 is removed in FME Flow 2026.1.

| Task | Request |
| --- | --- |
| Submit and return at once | `POST /fmerest/v3/transformations/submit/{repository}/{workspace}` |
| Submit and wait | `POST /fmerest/v3/transformations/transact/{repository}/{workspace}` |
| Run against an uploaded file (waits) | `POST /fmerest/v3/transformations/transactdata/{repository}/{workspace}`, with the file as the body |
| One job | `GET /fmerest/v3/transformations/jobs/id/{id}` |
| Job log | `GET /fmerest/v3/transformations/jobs/id/{id}/log` |
| Jobs by state | `GET /fmerest/v3/transformations/jobs/{active,completed,running,queued}` |
| Cancel a running job | `DELETE /fmerest/v3/transformations/jobs/running/{id}` |

In V3, published parameters are a list of name and value pairs, not a map:

```json
{
  "publishedParameters": [
    {"name": "COORDSYS", "value": "TX83-CF"},
    {"name": "THEMES", "value": ["railroad", "airports"]}
  ],
  "TMDirectives": {"tag": "Queue1", "description": "nightly load", "rtc": false},
  "NMDirectives": {"successTopics": ["load_ok"], "failureTopics": ["load_failed"]}
}
```

`TMDirectives` also accepts `ttc` (seconds until cancelled) and `ttl` (seconds
allowed in the queue). The CLI's `--node-manager-directive` flag fills in
`NMDirectives.directives`.

Moving a script from V3 to V4 means these changes:

- The path moves from `fmerest/v3/transformations/...` to `fmeapiv4/jobs`, and
  `repository` and `workspace` move from the path into the body.
- `publishedParameters` becomes a map.
- `TMDirectives.tag` becomes `queue`.
- Cancelling becomes a `POST` to `/cancel` instead of a `DELETE`.

## Writing job scripts

- The repository and workspace must already exist on Flow. Workbench's
  "Publish to FME Flow" does that. For scripts, see `fmeflow repositories --help`
  and `fmeflow workspaces --help`.
- Submit asynchronously and poll with a growing delay for anything that may run
  longer than the caller's HTTP timeout. CI runners and proxies often cut
  connections long before a large translation finishes.
- Treat `status` as data. Show `status` and `statusMessage` to the user, and look
  up the full set of states in the server's API documentation instead of
  hard-coding a list.
- Fail loudly on HTTP 401 or 403: the token is wrong, expired, or lacks
  permission on that repository.

## Reporting

Report the job id, the final `status` and `statusMessage`, and where the log
can be read. If the job was only submitted and never observed to finish, say so.
