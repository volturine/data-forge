#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
INNER_DOCKER_BRIDGE=10.239.0.1/24
INNER_DOCKER_ADDRESS_POOL=10.240.0.0/16
export INNER_DOCKER_BRIDGE INNER_DOCKER_ADDRESS_POOL

TEST_TARGET="${TEST_TARGET:-${1:-}}"
case "$TEST_TARGET" in
    test-backend-unit|test-backend-integration|test-worker|test-scheduler|test-frontend|test-runtime-stability|test-e2e|test-e2e-capacity) ;;
    *)
        echo "Unknown or missing test target: ${TEST_TARGET}" >&2
        exit 2
        ;;
esac

total_cpus="${TEST_CPUS:-}"
if [ -n "$total_cpus" ] && ! awk -v value="$total_cpus" \
    'BEGIN { exit !(value ~ /^[0-9]+([.][0-9]+)?$/ && value >= 0.1) }'; then
    echo "TEST_CPUS must be a number of at least 0.1 so both services receive a meaningful CPU limit; got '${total_cpus}'." >&2
    exit 2
fi

case "${STRICT_TEST_TEARDOWN:-}" in
    1) strict_teardown=1 ;;
    0) strict_teardown=0 ;;
    '') if [ -n "${CI:-}" ]; then strict_teardown=0; else strict_teardown=1; fi ;;
    *)
        echo "STRICT_TEST_TEARDOWN must be 0 or 1 when set; got '${STRICT_TEST_TEARDOWN}'." >&2
        exit 2
        ;;
esac

for command in docker bash just; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "Required host command not found: ${command}" >&2
        exit 2
    fi
done
if ! docker compose version >/dev/null 2>&1; then
    echo 'Docker Compose v2 is required on the host.' >&2
    exit 2
fi

run_id="$(date +%Y%m%d%H%M%S)-$$-${RANDOM}"
TEST_IMAGE_TAG="$run_id"
project="dataforge-test-${run_id}"
artifacts_dir="${ROOT_DIR}/.test-artifacts/${run_id}"
mkdir -p "$artifacts_dir"

compose=(docker compose --project-name "$project" --file "$ROOT_DIR/docker/compose.tests.yaml")
docker_memory_bytes="$(docker info --format '{{.MemTotal}}' 2>/dev/null || true)"
if [[ ! "$docker_memory_bytes" =~ ^[0-9]+$ ]] || [ "$docker_memory_bytes" -le 0 ]; then
    echo 'Could not read available memory from the Docker daemon.' >&2
    exit 2
fi
available_mb=$((docker_memory_bytes / 1024 / 1024))
if [ -n "${TEST_MEMORY_MB:-}" ]; then
    memory_mb="$TEST_MEMORY_MB"
elif [[ "$TEST_TARGET" == test-e2e* ]]; then
    memory_mb=$((available_mb * 90 / 100))
else
    memory_mb=$((available_mb * 75 / 100))
fi
if [[ ! "$memory_mb" =~ ^[0-9]+$ ]] || [ "$memory_mb" -lt 1024 ]; then
    echo "TEST_MEMORY_MB must be an integer of at least 1024; got '${memory_mb}'." >&2
    exit 2
fi
if [ "$memory_mb" -gt "$available_mb" ]; then
    echo "TEST_MEMORY_MB (${memory_mb} MiB) exceeds Docker's available memory (${available_mb} MiB)." >&2
    exit 2
fi

case "$TEST_TARGET" in
    test-e2e*)
        runner_memory_mb=512
        dind_memory_mb=$((memory_mb - runner_memory_mb))
        if [ "$dind_memory_mb" -lt 512 ]; then
            echo "E2E needs at least 1024 MiB total; set TEST_MEMORY_MB higher (got ${memory_mb})." >&2
            exit 2
        fi
        ;;
    test-backend-unit|test-frontend)
        runner_memory_mb=$((memory_mb * 70 / 100))
        dind_memory_mb=$((memory_mb - runner_memory_mb))
        dind_cpu_fraction=0.3
        ;;
    *)
        runner_memory_mb=$((memory_mb * 50 / 100))
        dind_memory_mb=$((memory_mb - runner_memory_mb))
        dind_cpu_fraction=0.5
        ;;
esac

docker_cpus="$(docker info --format '{{.NCPU}}' 2>/dev/null || true)"
if [[ ! "$docker_cpus" =~ ^[1-9][0-9]*$ ]]; then
    docker_cpus=2
fi
total_cpus="${total_cpus:-$docker_cpus}"
if ! awk -v value="$total_cpus" 'BEGIN { exit !(value ~ /^[0-9]+([.][0-9]+)?$/ && value >= 0.1) }'; then
    echo "TEST_CPUS must be a number of at least 0.1 so both services receive a meaningful CPU limit; got '${total_cpus}'." >&2
    exit 2
fi
if [[ "$TEST_TARGET" == test-e2e* ]]; then
    runner_cpus="$(awk -v value="$total_cpus" 'BEGIN { allocation=value * 0.2; if (allocation > 0.5) allocation=0.5; printf "%.2f", allocation }')"
    dind_cpus="$(awk -v total="$total_cpus" -v runner="$runner_cpus" 'BEGIN { printf "%.2f", total - runner }')"
else
    dind_cpus="$(awk -v value="$total_cpus" -v fraction="$dind_cpu_fraction" 'BEGIN { printf "%.2f", value * fraction }')"
    runner_cpus="$(awk -v total="$total_cpus" -v dind="$dind_cpus" 'BEGIN { printf "%.2f", total - dind }')"
fi
if ! awk -v dind="$dind_cpus" -v runner="$runner_cpus" \
    'BEGIN { exit !(dind >= 0.01 && runner >= 0.01) }'; then
    echo "TEST_CPUS=${total_cpus} rounds to an unusable Compose limit (dind=${dind_cpus}, runner=${runner_cpus}); both limits must be at least 0.01." >&2
    exit 2
fi
export DIND_MEMORY_MB="$dind_memory_mb" RUNNER_MEMORY_MB="$runner_memory_mb"
export DIND_CPUS="$dind_cpus" RUNNER_CPUS="$runner_cpus"
if [[ "$TEST_TARGET" == "test-e2e" ]]; then
    E2E_LOAD_PROBE_CPUS="$(python3 "$ROOT_DIR/scripts/e2e/load_probe_cpu_budget.py" "$DIND_CPUS")"
    export E2E_LOAD_PROBE_CPUS
    echo "50-tab load-probe CPU budget: ${E2E_LOAD_PROBE_CPUS} vCPU (min(3.0, 40% of DIND ${DIND_CPUS}))"
fi
if [[ "$TEST_TARGET" == test-e2e* ]]; then
    export E2E_API_WORKERS="${E2E_API_WORKERS:-${WORKERS:-}}"
    # Prefer worktree-local settings; otherwise use the main checkout's .env
    # when its common Git directory has the standard <workspace>/.git layout.
    # Compose interpolates secrets into the runner at startup; the image build
    # context excludes .env, so nothing secret is baked into images.
    env_file="$ROOT_DIR/.env"
    if [[ ! -f "$env_file" ]]; then
        common_git_dir="$(git -C "$ROOT_DIR" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
        if [[ "$(basename "$common_git_dir")" == .git ]]; then
            env_file="$(dirname "$common_git_dir")/.env"
        fi
    fi
    if [[ -f "$env_file" ]]; then
        set -a; source "$env_file"; set +a
    fi
fi
export TEST_IMAGE_TAG TEST_TARGET
{
    printf 'project=%s\ntarget=%s\ntotal_memory_mb=%s\ndind_memory_mb=%s\nrunner_memory_mb=%s\ntotal_cpus=%s\ndind_cpus=%s\nrunner_cpus=%s\n' \
        "$project" "$TEST_TARGET" "$memory_mb" "$dind_memory_mb" "$runner_memory_mb" \
        "$total_cpus" "$dind_cpus" "$runner_cpus"
} > "$artifacts_dir/resources.txt"

status=0
compose_down_attempted=0
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

compose_down() {
    if [ "$compose_down_attempted" -eq 1 ]; then
        return
    fi
    compose_down_attempted=1

    # Removing the DinD enclave's multi-GB docker-data volume can take well
    # over a minute on shared GitHub-hosted runners, so the bound is generous.
    local down_status=0
    if command -v timeout >/dev/null 2>&1; then
        timeout --signal=TERM --kill-after=5s 90s \
            "${compose[@]}" down --timeout 10 --volumes --remove-orphans \
            > "$artifacts_dir/compose-down.log" 2>&1 || down_status=$?
    else
        "${compose[@]}" down --timeout 10 --volumes --remove-orphans \
            > "$artifacts_dir/compose-down.log" 2>&1 || down_status=$?
    fi
    if [ "$down_status" -eq 0 ]; then
        return
    fi
    local message="Test Compose cleanup failed (exit ${down_status}); see ${artifacts_dir}/compose-down.log."
    # Leftovers accumulate on developer machines, so local runs fail on a
    # teardown failure by default. CI runners are ephemeral or cleaned by a
    # runner-level post-step, so there a passing run stays green and only warns.
    if [ "$strict_teardown" -eq 1 ]; then
        echo "$message" >&2
        if [ "$status" -eq 0 ]; then
            status=$down_status
        fi
    else
        echo "Warning: ${message} The test result is unaffected." >&2
        if [ -n "${GITHUB_ACTIONS:-}" ]; then
            echo "::warning title=Test Compose cleanup failed::${message}"
        fi
    fi
}

finalize() {
    local exit_status=$?
    trap - EXIT
    trap 'status=130; compose_down; exit 130' INT
    trap 'status=143; compose_down; exit 143' TERM
    local interrupted=0
    if [ "$exit_status" -eq 130 ] || [ "$exit_status" -eq 143 ]; then
        interrupted=1
        compose_down
        echo 'Interrupted test run; prioritized Compose cleanup over container diagnostics.' >&2
    fi
    local service container_id
    if [ "$interrupted" -eq 0 ]; then
        for service in docker runner; do
            container_id="$("${compose[@]}" ps --all --quiet "$service" 2>/dev/null | head -n 1 || true)"
            if [ -z "$container_id" ]; then
                continue
            fi
            docker events --since "$started_at" --until "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
                --filter type=container --filter event=oom --filter "container=${container_id}" \
                --format '{{json .}}' >> "$artifacts_dir/outer-docker-oom-events.jsonl" 2>&1 || true
            docker inspect --format \
                'OOMKilled={{.State.OOMKilled}} ExitCode={{.State.ExitCode}} Status={{.State.Status}} MemoryBytes={{.HostConfig.Memory}} NanoCPUs={{.HostConfig.NanoCpus}} Privileged={{.HostConfig.Privileged}}' \
                "$container_id" > "$artifacts_dir/${service}.inspect.txt" 2>&1 || true
            docker inspect --format '{{json .State}}' "$container_id" \
                > "$artifacts_dir/${service}.state.json" 2>&1 || true
            docker logs "$container_id" > "$artifacts_dir/${service}.log" 2>&1 || true
            if [ "$service" = docker ]; then
                docker exec "$container_id" sh -c '
                    for path in /sys/fs/cgroup/memory.events /sys/fs/cgroup/memory/memory.oom_control; do
                        if [ -r "$path" ]; then
                            printf "%s\\n" "$path"
                            cat "$path"
                        fi
                    done
                ' > "$artifacts_dir/docker-cgroup-memory-events.txt" 2>&1 || true
            fi
            if [ "$service" = runner ]; then
                docker cp "${container_id}:/app/.test-artifacts/." "$artifacts_dir/" \
                    >/dev/null 2>&1 || true
                for package in backend worker scheduler frontend; do
                    mkdir -p "$artifacts_dir/${package}-tests"
                    docker cp "${container_id}:/app/packages/${package}/tests/.artifacts/." \
                        "$artifacts_dir/${package}-tests/" >/dev/null 2>&1 || true
                done
            fi
        done
        if [ "$exit_status" -ne 0 ]; then
            daemon_id="$("${compose[@]}" ps --all --quiet docker 2>/dev/null | head -n 1 || true)"
            if [ -n "$daemon_id" ]; then
                local inner_dir inner_ids inner_id inner_artifact
                inner_dir="$artifacts_dir/inner"
                mkdir -p "$inner_dir"
                if inner_ids="$(docker exec "$daemon_id" docker ps --all --quiet --no-trunc 2> "$inner_dir/list-error.log")"; then
                    printf '%s\n' "$inner_ids" > "$inner_dir/container-ids.txt"
                    while IFS= read -r inner_id; do
                        if [ -z "$inner_id" ]; then
                            continue
                        fi
                        inner_artifact="$inner_dir/${inner_id:0:12}"
                        mkdir -p "$inner_artifact"
                        docker exec "$daemon_id" docker inspect --format '{{.Name}}' "$inner_id" \
                            > "$inner_artifact/name.txt" 2>&1 || true
                        docker exec "$daemon_id" docker inspect --format '{{json .State}}' "$inner_id" \
                            > "$inner_artifact/state.json" 2>&1 || true
                        docker exec "$daemon_id" docker inspect --format '{{json .Config.Labels}}' "$inner_id" \
                            > "$inner_artifact/labels.json" 2>&1 || true
                        docker exec "$daemon_id" docker logs --timestamps "$inner_id" \
                            > "$inner_artifact/container.log" 2>&1 || true
                    done <<< "$inner_ids"
                fi
            fi
        fi
        "${compose[@]}" logs --no-color > "$artifacts_dir/compose.log" 2>&1 || true
        compose_down
    else
        printf 'Container diagnostics skipped after signal; Compose teardown was attempted first.\n' \
            > "$artifacts_dir/compose.log"
    fi
    if docker image inspect "dataforge-test-runner:${TEST_IMAGE_TAG}" >/dev/null 2>&1; then
        if ! docker image rm "dataforge-test-runner:${TEST_IMAGE_TAG}" \
            > "$artifacts_dir/test-runner-image-remove.log" 2>&1; then
            echo "Test runner image cleanup failed; see ${artifacts_dir}/test-runner-image-remove.log." >&2
            if [ "$status" -eq 0 ]; then
                status=1
            fi
        fi
    fi
    trap - INT TERM
    if [ "$exit_status" -eq 0 ] && [ "$status" -ne 0 ]; then
        exit_status=$status
    fi
    echo "Test artifacts: ${artifacts_dir}"
    exit "$exit_status"
}
trap finalize EXIT
trap 'status=130; exit 130' INT
trap 'status=143; exit 143' TERM

echo "Building test runner image (Python 3.14.6, uv, Bun, Docker CLI/Compose, just)."
docker build --file docker/Dockerfile.tests --tag "dataforge-test-runner:${TEST_IMAGE_TAG}" . \
    2>&1 | tee "$artifacts_dir/build.log"

echo "Running ${TEST_TARGET} in isolated Compose project ${project} (${memory_mb} MiB, ${total_cpus} CPUs)."
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if "${compose[@]}" up --detach --wait --wait-timeout 150 docker; then
    daemon_id="$("${compose[@]}" ps --all --quiet docker 2>/dev/null | head -n 1 || true)"
    if [ -z "$daemon_id" ] || ! docker exec "$daemon_id" test -S /var/run/docker.sock; then
        echo 'The private Docker daemon did not create its Unix socket.' >&2
        status=1
    else
        outer_network="$(docker network ls \
            --filter "label=com.docker.compose.project=${project}" \
            --filter 'label=com.docker.compose.network=default' \
            --format '{{.Name}}' | head -n 1 || true)"
        if [ -z "$outer_network" ]; then
            echo 'Could not find this run’s outer Compose network for the CIDR overlap check.' >&2
            status=1
        else
            TEST_OUTER_NETWORK_SUBNETS="$(docker network inspect \
                --format '{{range .IPAM.Config}}{{.Subnet}},{{end}}' "$outer_network" 2>/dev/null || true)"
            TEST_OUTER_NETWORK_SUBNETS="${TEST_OUTER_NETWORK_SUBNETS%,}"
            if [ -z "$TEST_OUTER_NETWORK_SUBNETS" ]; then
                echo 'Could not read this run’s outer Compose network subnets.' >&2
                status=1
            else
                export TEST_OUTER_NETWORK_SUBNETS
                if "${compose[@]}" up --no-deps --abort-on-container-exit --exit-code-from runner runner; then
                    status=0
                else
                    status=$?
                fi
            fi
        fi
    fi
else
    status=$?
fi
daemon_id="$("${compose[@]}" ps --all --quiet docker 2>/dev/null | head -n 1 || true)"
if [ -z "$daemon_id" ]; then
    echo 'The private Docker daemon container is missing after the test run.' >&2
    [ "$status" -ne 0 ] || status=1
else
    daemon_state="$(docker inspect --format '{{.State.Running}} {{.State.OOMKilled}} {{.State.ExitCode}}' "$daemon_id" 2>/dev/null || true)"
    read -r daemon_running daemon_oom_killed daemon_exit_code <<< "$daemon_state" || true
    if [ "$daemon_running" != true ] || [ "$daemon_oom_killed" = true ]; then
        echo "The private Docker daemon stopped (running=${daemon_running:-unknown}, oom_killed=${daemon_oom_killed:-unknown}, exit=${daemon_exit_code:-unknown})." >&2
        [ "$status" -ne 0 ] || status=1
    elif ! docker exec "$daemon_id" docker info >/dev/null 2>&1; then
        echo 'The private Docker daemon is running but no longer responds on its Unix socket.' >&2
        [ "$status" -ne 0 ] || status=1
    fi
fi
exit "$status"
