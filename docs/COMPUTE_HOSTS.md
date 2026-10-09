# Compute hosts

The worker manager places compute (engine) containers on one or more Docker
daemons. By default it uses the single daemon named by `DF_ENGINE_DOCKER_HOST`
(the socket mounted into the worker container). `DF_ENGINE_DOCKER_HOSTS` turns
that into a list, so engines can run on two or three machines while the
manager, API, PostgreSQL and RustFS stay where they are. To also survive the
loss of a machine, run the whole stack on each one as described in
[High availability](HIGH_AVAILABILITY.md); the host list below is the same in
both setups.

## How placement works

- The manager probes every host at start-up and every
  `DF_ENGINE_DOCKER_HOST_HEALTH_INTERVAL_SECONDS` (default 15): daemon ping,
  the engine image, the engine network and the daemon's CPU count.
- Each launch picks the healthy host with the lowest
  `placed containers / daemon CPUs`; ties go to the host with fewer containers,
  then to configuration order. A host's `max_workers` caps what it receives.
  `COMPUTE_WORKERS` and `COMPUTE_WARM_WORKERS` stay the only cluster-wide
  budgets, so the per-host caps must add up to at least `COMPUTE_WORKERS`.
- A failed probe, a Docker API error, or a container that is still running
  but never answers takes the host out of placement for 30 seconds and the
  launch moves to the next host. A half-started container on the failing host
  is removed. An engine that exits during start-up is the engine's failure,
  not the host's: that launch fails without trying other hosts or excluding
  the one it ran on. The launch fails only when every host fails.
- Start-up reconciliation sweeps every reachable host for leftover containers
  of this deployment; an unreachable host is logged and re-probed later.
- The host a container runs on is recorded as `docker_host` on the engine row
  and shown in the runtime overview.

Engines only ever reach the object store; they never talk to PostgreSQL or the
API. That is what makes a remote host cheap to add: it needs the engine image,
a Docker API the manager can reach, and a route to RustFS.

## Add a host

1. **Expose the daemon.** On the new machine either enable the Docker TCP
   socket with TLS (`tcp://<ip>:2376`, see Docker's "Protect the Docker daemon
   socket") or allow SSH from the worker container
   (`ssh://<user>@<ip>`, the user must be in the `docker` group). A plain
   `tcp://<ip>:2375` is acceptable only on a private network: Docker API access
   is root on that machine.
2. **Pull the engine image** on that machine with the exact reference used in
   `DF_ENGINE_IMAGE`. The manager refuses a host where the image or the engine
   network is missing.
3. **Create the engine network** there:
   `docker network create <DF_ENGINE_DOCKER_NETWORK>`. Engines on a remote host
   still get their RPC port published on that host, so the network only has to
   exist; it does not need to reach the manager.
4. **Open the route to the object store.** Engines on the host must reach the
   endpoint you give as `object_store_endpoint` (or the worker's own
   `OBJECT_STORE_ENDPOINT` when omitted). `http://rustfs:9000` is Compose DNS and
   does not resolve from another machine, so publish RustFS on the manager's
   machine and use that address, for example `http://10.0.0.1:9000`.
5. **Open the engine ports** from the worker container to the host:
   engines publish an ephemeral port in the daemon's `ip_local_port_range`
   (Docker's default 32768-60999). The manager dials `connect_host:<port>`.
6. **Describe the host** in `DF_ENGINE_DOCKER_HOSTS` and restart the worker:

```bash
DF_ENGINE_DOCKER_HOSTS='[
  {"name": "local", "docker_host": "unix:///var/run/docker.sock"},
  {"name": "node-b", "docker_host": "tcp://10.0.0.5:2376", "connect_host": "10.0.0.5",
   "object_store_endpoint": "http://10.0.0.1:9000", "max_workers": 8,
   "tls_cert_path": "/certs/node-b"},
  {"name": "node-c", "docker_host": "ssh://dataforge@10.0.0.6", "connect_host": "10.0.0.6",
   "object_store_endpoint": "http://10.0.0.1:9000"}
]'
```

| Field                   | Required | Meaning                                                                                                                                                           |
| ----------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`                  | yes      | Unique label, lowercase letters, digits, `.`, `_`, `-`. Used in logs, labels and the overview.                                                                    |
| `docker_host`           | yes      | `unix://`, `tcp://`, `ssh://`, `http://` or `https://` daemon endpoint.                                                                                           |
| `connect_host`          | remote   | Address the worker dials for the engine's published RPC port. Required for every non-`unix://` host. Empty on a local socket means Docker DNS on the engine network. |
| `engine_network`        | no       | Defaults to `DF_ENGINE_DOCKER_NETWORK`.                                                                                                                           |
| `object_store_endpoint` | no       | Endpoint handed to engines on this host. Defaults to `ENGINE_OBJECT_STORE_ENDPOINT`, then the worker's `OBJECT_STORE_ENDPOINT`.                                    |
| `max_workers`           | no       | Hard cap of containers on this host. `0` (default) means bounded only by `COMPUTE_WORKERS`. The caps must add up to at least `COMPUTE_WORKERS` (or one host must stay uncapped); the worker refuses to start otherwise. |
| `tls_cert_path`         | no       | Directory with `ca.pem`, `cert.pem` and `key.pem` for a TLS `tcp://` daemon. Mount it into the worker container.                                                   |

Fields left out fall back to the single-host variables, so the entry for the
local socket is just a name and `docker_host`. Mount TLS certificates and SSH
keys into the worker container with an extra `volumes:` entry on the `worker`
service; the manager reads `~/.ssh` for `ssh://` hosts.

An empty `DF_ENGINE_DOCKER_HOSTS` keeps the single-host behaviour exactly as
before. `ENGINE_CONNECT_HOST` (dev and E2E) is still honoured as the default
`connect_host`.

## Verify

- Worker log at start-up: one `Docker host ready name=<name> …` line per host, or
  the reason it was skipped. With no reachable host the worker fails readiness.
- Runtime overview: each engine row shows its `docker_host`.
- `docker ps --filter label=io.dataforge.docker-host=<name>` on the host lists
  the containers placed there. Containers also carry the
  `io.dataforge.deployment` label so a host can serve several deployments.

## Remove a host

Delete its entry and restart the worker. Running engines on that host finish
their current work and are reaped on their idle TTL; start-up reconciliation
does not reach a host that is no longer configured, so remove leftovers there
with `docker ps -a --filter label=io.dataforge.deployment=<id>` if the worker
was not shut down cleanly first.
