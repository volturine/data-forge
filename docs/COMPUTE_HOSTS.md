# Compute hosts

The worker service is the manager: it owns Docker access and places compute
workers on one or more Docker daemons. By default it uses the single daemon
named by `DF_COMPUTE_WORKER_DOCKER_HOST` (the socket mounted into the worker
service). `DF_COMPUTE_WORKER_DOCKER_HOSTS` turns that into a list, so compute
workers can run on several machines while the manager, API, PostgreSQL, and
RustFS stay where they are.

## How placement works

- The manager probes every host at start-up and every
  `DF_COMPUTE_WORKER_DOCKER_HOST_HEALTH_INTERVAL_SECONDS` (default 15): daemon ping,
  the compute-worker image, the compute-worker network, and the daemon's CPU count.
- Each launch picks the healthy host with the lowest
  `placed containers / daemon CPUs`; ties go to the host with fewer containers,
  then to configuration order. A host's `max_workers` caps what it receives.
  `COMPUTE_WORKERS` and `COMPUTE_WARM_WORKERS` stay the only cluster-wide
  budgets, so the per-host caps must add up to at least `COMPUTE_WORKERS`.
- A failed probe, a Docker API error, or a container that is still running
  but never answers takes the host out of placement for 30 seconds and the
  launch moves to the next host. A half-started container on the failing host
  is removed. A compute worker that exits during start-up is that worker's failure,
  not the host's: that launch fails without trying other hosts or excluding
  the one it ran on. The launch fails only when every host fails.
- Start-up reconciliation sweeps every reachable host for leftover containers
  of this deployment; an unreachable host is logged and re-probed later.
- The host a container runs on is recorded as `docker_host` on the compute-worker row
  and shown in the runtime overview.

Compute workers only reach the object store; they never talk to PostgreSQL or
the API. A remote host needs the compute-worker image,
a Docker API the manager can reach, and a route to RustFS.

## Add a host

1. **Expose the daemon.** On the new machine either enable the Docker TCP
   socket with TLS (`tcp://<ip>:2376`, see Docker's "Protect the Docker daemon
   socket") or allow SSH from the worker container
   (`ssh://<user>@<ip>`, the user must be in the `docker` group). A plain
   `tcp://<ip>:2375` is acceptable only on a private network: Docker API access
   is root on that machine.
2. **Pull the compute-worker image** on that machine with the exact reference used in
   `DF_COMPUTE_WORKER_IMAGE`. The manager refuses a host where the image or the compute-worker
   network is missing.
3. **Create the compute-worker network** there:
   `docker network create <DF_COMPUTE_WORKER_DOCKER_NETWORK>`. Compute workers on a remote host
   still get their RPC port published on that host, so the network only has to
   exist; it does not need to reach the manager.
4. **Open the route to the object store.** Engines on the host must reach the
   endpoint you give as `object_store_endpoint` (or the worker's own
   `OBJECT_STORE_ENDPOINT` when omitted). `http://rustfs:9000` is Compose DNS and
   does not resolve from another machine, so publish RustFS on the manager's
   machine and use that address, for example `http://10.0.0.1:9000`.
5. **Open the compute-worker ports** from the manager container to the host:
   compute workers publish an ephemeral port in the daemon's `ip_local_port_range`
   (Docker's default 32768-60999). The manager dials `connect_host:<port>`.
6. **Describe the host** in `DF_COMPUTE_WORKER_DOCKER_HOSTS` and restart the worker:

```bash
DF_COMPUTE_WORKER_DOCKER_HOSTS='[
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
| `connect_host`          | remote   | Address the manager dials for the compute worker's published RPC port. Required for every non-`unix://` host. Empty on a local socket means Docker DNS on the compute-worker network. |
| `compute_worker_network` | no       | Defaults to `DF_COMPUTE_WORKER_DOCKER_NETWORK`.                                                                                                                           |
| `object_store_endpoint` | no       | Endpoint handed to compute workers on this host. Defaults to `COMPUTE_WORKER_OBJECT_STORE_ENDPOINT`, then the manager's `OBJECT_STORE_ENDPOINT`.                            |
| `max_workers`           | no       | Hard cap of containers on this host. `0` (default) means bounded only by `COMPUTE_WORKERS`. The caps must add up to at least `COMPUTE_WORKERS` (or one host must stay uncapped); the worker refuses to start otherwise. |
| `tls_cert_path`         | no       | Directory with `ca.pem`, `cert.pem` and `key.pem` for a TLS `tcp://` daemon. Mount it into the worker container.                                                   |

Fields left out fall back to the single-host variables, so the entry for the
local socket is just a name and `docker_host`. Mount TLS certificates and SSH
keys into the worker container with an extra `volumes:` entry on the `worker`
service; the manager reads `~/.ssh` for `ssh://` hosts.

An empty `DF_COMPUTE_WORKER_DOCKER_HOSTS` keeps the single-host behavior.
Deprecated `DF_ENGINE_*` and `ENGINE_*` environment names remain accepted for
one release and emit a warning when read. The old JSON field `engine_network`
also remains accepted for one release; use `compute_worker_network` in new
host entries.

## Verify

- Worker log at start-up: one `Docker host ready name=<name> …` line per host, or
  the reason it was skipped. With no reachable host the worker fails readiness.
- Runtime overview: each compute-worker row shows its `docker_host`.
- `docker ps --filter label=io.dataforge.docker-host=<name>` on the host lists
  the containers placed there. Containers also carry the
  `io.dataforge.deployment` label so a host can serve several deployments.

## Remove a host

Delete its entry and restart the worker manager. Running compute workers on that host finish
their current work and are reaped on their idle TTL; start-up reconciliation
does not reach a host that is no longer configured, so remove leftovers there
with `docker ps -a --filter label=io.dataforge.deployment=<id>` if the worker
was not shut down cleanly first.
