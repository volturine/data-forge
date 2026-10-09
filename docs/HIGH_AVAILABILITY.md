# High availability

Run the same stack on two or three machines and the application survives the
loss of any one of them. This page describes what fails over, how, and what you
have to provide. It builds on [Deployment](DEPLOYMENT.md) and
[Compute hosts](COMPUTE_HOSTS.md).

## What runs on each machine

`docker/compose.multi-host.yaml` turns the production stack into one identical
unit per machine:

| Service                 | Per machine                                                       | Failover                                                                                                                                                                                                  |
| ----------------------- | ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| API replicas + ingress  | `DF_API_REPLICAS` stateless API containers behind a local nginx  | Any replica on any machine can serve any request; sessions, locks, jobs and notifications live in PostgreSQL. Point your DNS or load balancer at every machine (see below).                                   |
| Runtime coordinator     | one container, active on one machine, standby on the others       | A PostgreSQL session lease. If the active machine dies, PostgreSQL drops the session within about 11 seconds and a standby takes over with a new fenced generation.                                           |
| Worker manager          | one container, active on one machine, standby on the others       | Same lease mechanism. The new manager sweeps every Docker host, removes engine containers of the previous owner, rebuilds its placement accounting and restarts the warm reserve. Standbys serve the data plane. |
| Scheduler               | one container, all active                                         | Due schedules are claimed per namespace with claim tokens, so several schedulers never double-run one.                                                                                                       |
| Engines                 | placed on every daemon in `DF_ENGINE_DOCKER_HOSTS`                | Work on engines of a dead machine fails or is retried by the existing lease expiry recovery; the host is excluded from placement until its daemon answers again.                                             |
| PostgreSQL, object store| **outside** these stacks, shared                                  | Your responsibility: a managed PostgreSQL or a replicated cluster, and an S3-compatible store with its own redundancy. The bundled `postgres` and `rustfs` services are disabled by the override.            |

Active and standby are decided by two PostgreSQL session-level advisory locks,
one for the coordinator and one for the manager. The lease connections set
`tcp_keepalives_idle=5`, `tcp_keepalives_interval=2` and
`tcp_keepalives_count=3` on their own session, so the server notices a machine
that vanished without closing the connection and releases the lock on its own;
no server configuration is needed. Every Docker mutation of the active
manager first proves its lease is still held, and every coordinator
transaction is fenced by its generation, so a machine that was only paused or
partitioned cannot act after a takeover. The two leases are independent: the
coordinator may be active on machine A while the manager is active on B.

A standby coordinator and a standby worker report healthy to Docker, so the
API replicas and the scheduler of their machine start normally.

## Recipe

Machines `A` (10.0.0.1) and `B` (10.0.0.2) on a private network (a VPC, a
VLAN, or a WireGuard/Tailscale mesh). Internal gRPC and the Docker API are
not encrypted by the application; the network must be private.

1. **Provision shared services.** A PostgreSQL server reachable from both
   machines (connect the stack directly to PostgreSQL, not through a
   transaction-pooling PgBouncer: the leases are session-level advisory locks)
   and an S3-compatible object store. Put them in `DF_DATABASE_URL`,
   `DF_OBJECT_STORE_ENDPOINT` and `DF_ENGINE_OBJECT_STORE_ENDPOINT`.
2. **Expose each Docker daemon with TLS** on its private address
   (`tcp://10.0.0.x:2376`, Docker's "Protect the Docker daemon socket"). Copy
   the client certificates for both daemons to both machines under
   `docker/certs/<host-name>/{ca,cert,key}.pem` (`DF_COMPUTE_HOST_CERTS_DIR`).
   Pull `DF_ENGINE_IMAGE` on both machines.
3. **Describe both hosts** in `DF_ENGINE_DOCKER_HOSTS`, identically on both
   machines, so whichever manager is active places engines on both:

   ```bash
   DF_ENGINE_DOCKER_HOSTS='[
     {"name": "node-a", "docker_host": "tcp://10.0.0.1:2376", "connect_host": "10.0.0.1", "tls_cert_path": "/certs/node-a"},
     {"name": "node-b", "docker_host": "tcp://10.0.0.2:2376", "connect_host": "10.0.0.2", "tls_cert_path": "/certs/node-b"}
   ]'
   ```

   The engine network named by `DF_ENGINE_DOCKER_NETWORK` is created by the
   stack on each machine. Open the engines' published port range (Docker's
   `ip_local_port_range`, 32768-60999 by default) between the machines.
4. **List every coordinator address** in `DF_RUNTIME_COORDINATOR_TARGETS` as one
   gRPC `ipv4:` target, for example `ipv4:10.0.0.1:50051,10.0.0.2:50051`, and
   open port 50051 between the machines. Workers and schedulers try the
   addresses in order and skip the ones that refuse, which is what a standby
   does, so they always reach the active coordinator.
5. **Set `DF_NODE_ADDRESS`** on each machine to its own private address. It is
   the only value that differs between the two env files.
6. **Start the stack on every machine:**

   ```bash
   docker compose --env-file docker/env/prod.env -p dataforge-prod \
     -f docker/compose.yaml -f docker/compose.replicas.yaml \
     -f docker/compose.multi-host.yaml up -d
   ```

7. **Publish the entry point.** Each machine's ingress serves the whole
   application on `DF_API_PORT`. Put a load balancer or health-checked DNS in
   front of both machines (checking `/health/ready`); plain multi-address DNS
   also works, but browsers fail over between addresses slowly. Set
   `DF_API_REPLICA_TRUSTED_PROXY_HOPS` to the ingress plus that balancer.

## Verify

- `docker compose ... ps` on both machines shows `runtime` and `worker`
  healthy. The logs on one machine say `Runtime coordinator started` and
  `Worker manager lease acquired`; on the other,
  `Runtime coordinator standby waiting` and
  `Worker manager standby waiting for the active manager`.
- The runtime overview lists engines with `docker_host` values from both
  machines once there is enough work (or `COMPUTE_WARM_WORKERS` is at least 2).
- Drill: power off, or `docker compose ... stop runtime worker` on, the active
  machine. Within about 15 seconds the other machine logs the takeover, the
  API keeps answering throughout, and new previews run on the surviving host.
  Bring the machine back and its services return as standbys.

## Limits

- Recovery is a takeover, not a hand-off: work that was running on engines of
  the dead machine, or in the dying manager, is retried or fails through the
  existing lease expiry paths; nothing is lost durably.
- Only one coordinator and one manager are active at a time. This gives
  availability, not more coordinator or manager throughput; see
  [Capacity-First Runtime Optimization](prd/active/elastic-runtime-scale-out.md)
  for scale policy.
- PostgreSQL and the object store are the real foundation. Their availability
  bounds the application's.
